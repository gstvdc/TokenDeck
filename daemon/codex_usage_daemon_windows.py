"""Send local Codex usage-window data to a paired Clawdmeter over BLE.

This reads only ``rate_limits`` from the newest local Codex session JSONL.
It never reads or transmits prompts, responses, or authentication tokens.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path

from bleak import BleakClient
from bleak.exc import BleakError

# Permite executar este arquivo diretamente a partir de qualquer diretório.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from daemon.claude_usage_daemon_windows import (
    POLL_INTERVAL,
    Session,
    acquire_target,
    log,
)


def _session_root() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"


def _recent_session_files(root: Path | None = None, limit: int = 5) -> list[Path]:
    root = root or _session_root()
    try:
        files = sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        return files[:limit]
    except (OSError, ValueError):
        return []


def _latest_session_file(root: Path | None = None) -> Path | None:
    files = _recent_session_files(root, limit=1)
    return files[0] if files else None


def _last_rate_limits(path: Path) -> dict | None:
    """Return only the last token_count.rate_limits object with primary usage in a JSONL file."""
    latest = None
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if '"rate_limits"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = record.get("payload", {})
                limits = payload.get("rate_limits")
                if payload.get("type") == "token_count" and isinstance(limits, dict):
                    primary = limits.get("primary")
                    if isinstance(primary, dict) and primary.get("used_percent") is not None:
                        latest = limits
    except OSError:
        return None
    return latest


def _minutes_until(epoch: object, now: float) -> int:
    try:
        return max(0, int((float(epoch) - now + 59) // 60))
    except (TypeError, ValueError):
        return -1


def read_codex_payload(root: Path | None = None, now: float | None = None) -> dict | None:
    for path in _recent_session_files(root):
        limits = _last_rate_limits(path)
        if not limits:
            continue

        primary = limits.get("primary") or {}
        secondary = limits.get("secondary") or {}
        if primary.get("used_percent") is None:
            continue

        now = time.time() if now is None else now
        payload = {
            "p": "codex",
            "s": float(primary.get("used_percent", 0)),
            "sr": _minutes_until(primary.get("resets_at"), now),
            "w": float(secondary.get("used_percent", 0)),
            "wr": _minutes_until(secondary.get("resets_at"), now),
            "st": "limited" if limits.get("rate_limit_reached_type") else "allowed",
            "acct": limits.get("plan_type") or "unknown",
            "ok": True,
            "t": int(now) + getattr(time.localtime(), "tm_gmtoff", 0),
            "tf": 24,
        }
        return payload
    return None


async def connect_and_send(device, stop_event: asyncio.Event) -> bool:
    client = BleakClient(device, address_type="random", use_cached_services=False)
    try:
        await client.connect()
        if not client.is_connected:
            return False
        log("Codex: connected")
        session = Session(client)
        await session.setup_refresh_subscription()

        while client.is_connected and not stop_event.is_set():
            payload = read_codex_payload()
            if payload:
                if not await session.write_payload(payload):
                    return False
            else:
                log("Codex: no local rate-limit record yet")
                await session.write_payload({"p": "codex", "ok": False})

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass
        return True
    except (BleakError, OSError, asyncio.TimeoutError) as exc:
        log(f"Codex connection failed: {exc}")
        return False
    finally:
        try:
            await client.disconnect()
        except (BleakError, OSError, AssertionError):
            pass


async def main() -> None:
    stop_event = asyncio.Event()
    if sys.platform != "win32":
        raise RuntimeError("This daemon requires native Windows BLE")

    def stop(*_args) -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)

    log("=== Codex Usage Daemon (BLE, Windows) ===")
    while not stop_event.is_set():
        device = await acquire_target()
        if device is not None:
            await connect_and_send(device, stop_event)
        if not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
