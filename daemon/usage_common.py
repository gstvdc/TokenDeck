#!/usr/bin/env python3
"""Shared logic between claude_usage_daemon.py (macOS/Linux) and
claude_usage_daemon_windows.py (Windows).

Both daemons poll the same Anthropic API endpoint and speak the same BLE GATT
protocol to the same "Clawdmeter" firmware; only token discovery, BLE device
acquisition, and OS-level details (Keychain, WinRT retry quirks, hour-format
detection) differ per platform, so those stay in the platform-specific files.
"""

from __future__ import annotations

import calendar
import datetime
import json
import re
import time
from pathlib import Path

import httpx

DEVICE_NAME = "Clawdmeter"
SERVICE_UUID = "4c41555a-4465-7669-6365-000000000001"
RX_CHAR_UUID = "4c41555a-4465-7669-6365-000000000002"
REQ_CHAR_UUID = "4c41555a-4465-7669-6365-000000000004"

POLL_INTERVAL = 60
TICK = 5

API_URL = "https://api.anthropic.com/v1/messages"
API_HEADERS_TEMPLATE = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "oauth-2025-04-20",
    "Content-Type": "application/json",
    "User-Agent": "claude-code/2.1.5",
}
API_BODY = {
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 1,
    "messages": [{"role": "user", "content": "hi"}],
}


class TokenExpired(Exception):
    """Raised by poll_api on a genuine 401/403 — the access token is dead.

    Neither daemon ever refreshes it (pure free-ride: Claude Code owns
    refreshing); the caller just signals "No data" to the device until the
    CLI re-seeds the token. Platform modules may subclass this to keep their
    own exception name (e.g. Windows' AuthError) for backward compatibility.
    """


def _extract_access_token(blob: str) -> str | None:
    """Pull the accessToken out of a credentials blob.

    Claude Code stores credentials as a JSON object; the blob may also be
    nested ({"claudeAiOauth": {"accessToken": "..."}}). Fall back to a regex
    match so unexpected shapes still work, and finally treat the blob as a
    raw token if nothing else matches.
    """
    blob = blob.strip()
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        tok = data.get("accessToken")
        if isinstance(tok, str) and tok.strip():
            return tok
        for v in data.values():
            if isinstance(v, dict):
                tok = v.get("accessToken")
                if isinstance(tok, str) and tok.strip():
                    return tok
    m = re.search(r'"accessToken"\s*:\s*"([^"]+)"', blob)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_\-.~+/=]{20,}", blob):
        return blob
    return None


def read_chime_setting(config_file: Path) -> str:
    """Read the `chime` option from the config file. One of: off|on.

    Defaults to "off" (the device stays silent) so existing setups are
    unaffected until the user opts in.
    """
    try:
        if config_file.exists():
            for line in config_file.read_text().splitlines():
                line = line.split("#", 1)[0].strip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip().lower() == "chime":
                    val = val.strip().lower()
                    if val in ("off", "on"):
                        return val
    except OSError:
        pass
    return "off"


def read_clock_setting(config_file: Path) -> str:
    """Read the `clock` option from the config file. One of: off|auto|12|24.

    Defaults to "off" (no clock; the device keeps showing "Usage") so
    existing setups are unaffected until the user opts in.
    """
    try:
        if config_file.exists():
            for line in config_file.read_text().splitlines():
                line = line.split("#", 1)[0].strip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip().lower() == "clock":
                    val = val.strip().lower()
                    if val in ("off", "auto", "12", "24"):
                        return val
    except OSError:
        pass
    return "off"


def add_chime_field(payload: dict, config_file: Path) -> None:
    """Add "c":1 to the payload when the config opts in, so the firmware may
    sound the session-reset chime. Omitted entirely when chime is off."""
    if read_chime_setting(config_file) == "on":
        payload["c"] = 1


def add_clock_fields(payload: dict, config_file: Path, detect_hour_format) -> None:
    """Add wall-clock fields to the payload when the config opts in.

    "t"  = local wall-clock epoch (UTC epoch shifted by the tz offset) so the
           device can show the time without an RTC.
    "tf" = 12 or 24, the hour format the device should render.

    ``detect_hour_format`` is a zero-arg callable returning 12 or 24 — each
    platform detects this differently (macOS: `defaults read`; Windows: the
    registry), so the caller supplies it.
    """
    clock = read_clock_setting(config_file)
    if clock == "off":
        return
    tf = 24 if clock == "24" else 12 if clock == "12" else detect_hour_format()
    payload["t"] = int(time.time()) + time.localtime().tm_gmtoff
    payload["tf"] = tf


def _billing_period_info(now: float, reset_ts: str) -> dict:
    """Fraction of billing period elapsed (tp, 0-100) and period length in days (pd).

    Billing periods are assumed calendar-monthly: period_end is the reset
    timestamp, period_start is the same day/time one calendar month earlier.
    The rate-limit headers expose only the reset timestamp, not the period
    length, so the monthly window is an assumption — but a documented one:
    Enterprise spend-limit `period` "the only value today is monthly" (Claude
    Enterprise Admin API reference). Revisit if that ever changes.
    """
    try:
        period_end = float(reset_ts)
    except ValueError:
        return {"tp": 0, "pd": 30, "rd": ""}
    if period_end <= 0:
        # reset_ts defaults to "0" whenever the overage-reset header is
        # absent. fromtimestamp(0) is 1970; stepping one month back lands in
        # 1969, and datetime.timestamp() raises OSError for pre-1970 dates on
        # Windows — bail to the neutral default instead.
        return {"tp": 0, "pd": 30, "rd": ""}
    try:
        dt_end = datetime.datetime.fromtimestamp(period_end)
        prev_month = dt_end.month - 1 or 12
        prev_year = dt_end.year if dt_end.month > 1 else dt_end.year - 1
        prev_day = min(dt_end.day, calendar.monthrange(prev_year, prev_month)[1])
        dt_start = dt_end.replace(year=prev_year, month=prev_month, day=prev_day)
        period_start = dt_start.timestamp()
    except (OSError, OverflowError, ValueError):
        # Garbage/out-of-range reset_ts (e.g. a far-future header) must never
        # crash the daemon thread — degrade to the safe default instead
        # (field report: OSError(22) killed the poll loop on Windows).
        return {"tp": 0, "pd": 30, "rd": ""}
    period_len = period_end - period_start
    if period_len <= 0:
        return {"tp": 0, "pd": 30, "rd": ""}
    pct_val = (now - period_start) / period_len * 100
    return {
        "tp": max(0, min(100, int(round(pct_val)))),
        "pd": int(round(period_len / 86400)),
        "rd": f"{dt_end.strftime('%b')} {dt_end.day}",
    }


async def poll_api(token: str, *, expired_exc: type[Exception] = TokenExpired,
                    extra_fields=None, log=None) -> dict | None:
    """Poll the Anthropic API for rate-limit utilization and shape it into the
    wire payload the firmware expects.

    ``expired_exc`` lets each platform raise its own exception type (e.g.
    Windows' AuthError) on a genuine 401/403 while sharing this body.
    ``extra_fields``, if given, is called with the built payload dict so the
    caller can add platform-detected fields (chime/clock) before it's sent.
    ``log``, if given, replaces the module's default print-only logger (the
    Windows daemon passes its own, which also writes a rotating file — the
    only diagnostic trail once running headless under pythonw.exe).
    """
    _log = log or _default_log
    headers = dict(API_HEADERS_TEMPLATE)
    headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(API_URL, headers=headers, json=API_BODY)
    except httpx.HTTPError as e:
        _log(f"API call failed: {e}")
        return None
    if resp.status_code in (401, 403):
        _log(f"API HTTP {resp.status_code}: {resp.text[:200]}")
        raise expired_exc(resp.status_code)
    if resp.status_code >= 400:
        _log(f"API HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    def hdr(name: str, default: str = "0") -> str:
        return resp.headers.get(name, default)

    now = time.time()

    def reset_minutes(reset_ts: str) -> int:
        try:
            r = float(reset_ts)
        except ValueError:
            return 0
        mins = (r - now) / 60.0
        return int(round(mins)) if mins > 0 else 0

    def pct(util: str) -> int:
        try:
            return int(round(float(util) * 100))
        except ValueError:
            return 0

    # Pro/Max accounts expose 5h/7d windows; Enterprise/overage use a single
    # spending-limit model reported via overage-utilization.
    if resp.headers.get("anthropic-ratelimit-unified-5h-utilization"):
        payload = {
            "s": pct(hdr("anthropic-ratelimit-unified-5h-utilization")),
            "sr": reset_minutes(hdr("anthropic-ratelimit-unified-5h-reset")),
            "w": pct(hdr("anthropic-ratelimit-unified-7d-utilization")),
            "wr": reset_minutes(hdr("anthropic-ratelimit-unified-7d-reset")),
            "st": hdr("anthropic-ratelimit-unified-5h-status", "unknown"),
            "acct": "pro",
            "ok": True,
        }
    else:
        reset_ts = hdr("anthropic-ratelimit-unified-overage-reset")
        payload = {
            "s": pct(hdr("anthropic-ratelimit-unified-overage-utilization")),
            "sr": reset_minutes(reset_ts),
            "w": 0,
            "wr": 0,
            "st": hdr("anthropic-ratelimit-unified-status", "unknown"),
            "acct": "ent",
            **_billing_period_info(now, reset_ts),
            "ok": True,
        }
    if extra_fields is not None:
        extra_fields(payload)
    return payload


def _default_log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
