"""Send Codex, Claude, and Gemini CLI usage to the CYD through USB serial."""
from __future__ import annotations

import asyncio
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import serial
from serial.tools import list_ports

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from daemon.claude_usage_daemon_windows import AuthError, poll_api, read_token
from daemon.codex_usage_daemon_windows import read_codex_payload
from daemon.usage_common import append_history_record

BAUDRATE = 115200
UPDATE_SECONDS = 5
CLAUDE_REFRESH_SECONDS = 60
GEMINI_REFRESH_SECONDS = 60

MUTEX_BRIDGE_NAME = "Local\\TokenDeckUsbBridge"


def _acquire_singleton_mutex():
    """Create and hold the named mutex tokendeck_gui.py's is_bridge_running()
    checks for. Returning early (not re-acquiring on retry) is intentional:
    Windows releases the mutex automatically when this process exits or
    crashes, so no explicit CloseHandle/cleanup is needed. The handle is
    returned (not just discarded) only so the caller can keep a reference
    alive for the life of the process — ctypes does not auto-close it.
    """
    try:
        return ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_BRIDGE_NAME)
    except Exception:
        return None


def _activity_roots() -> dict[str, Path]:
    """Locations written when each local assistant receives a prompt."""
    home = Path.home()
    return {
        "codex": home / ".codex" / "sessions",
        "claude": home / ".claude" / "sessions",
        "gemini": home / ".gemini" / "antigravity-cli" / "conversations",
    }


def _latest_codex_user_message(root: Path) -> float:
    """Return the timestamp of the most recent *user* message in Codex logs.

    Codex keeps appending tool output after a prompt. File mtime would therefore
    make background work look newer than a prompt sent to another assistant.
    """
    latest = -1.0
    try:
        files = sorted(root.rglob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)[:8]
    except OSError:
        return latest
    for path in files:
        try:
            with path.open(encoding="utf-8") as records:
                for line in records:
                    record = json.loads(line)
                    payload = record.get("payload", {})
                    if payload.get("type") != "message" or payload.get("role") != "user":
                        continue
                    timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp()
                    latest = max(latest, timestamp)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
    return latest


def activity_markers(roots: dict[str, Path] | None = None) -> dict[str, float]:
    """Return local activity markers without looking at prompt content."""
    markers: dict[str, float] = {}
    for provider, root in (roots or _activity_roots()).items():
        if provider == "codex":
            markers[provider] = _latest_codex_user_message(root)
            continue
        newest_mtime = -1.0
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                newest_mtime = max(newest_mtime, mtime)
        except OSError:
            continue
        markers[provider] = newest_mtime
    return markers


class ActivityMonitor:
    """Report a provider only when a new local activity record appears."""

    def __init__(self, roots: dict[str, Path] | None = None):
        self.roots = roots
        self.seen = activity_markers(roots)

    def poll(self) -> str:
        current = activity_markers(self.roots)
        changed = [(marker, provider) for provider, marker in current.items()
                   if marker > self.seen.get(provider, -1.0)]
        self.seen = current
        return max(changed)[1] if changed else ""


def last_active_provider(roots: dict[str, Path] | None = None) -> str:
    """Compatibility helper: return the provider with the newest current marker."""
    markers = activity_markers(roots)
    return max(markers, key=markers.get, default="")


def find_port() -> str | None:
    """Return the CYD's CH340 port; never select the PC's built-in COM ports."""
    ports = list(list_ports.comports())
    ch340 = [port.device for port in ports if port.vid == 0x1A86 and port.pid in (0x7523, 0x55D4)]
    if ch340:
        return ch340[0]
    usb_serial = [port.device for port in ports if port.vid is not None and port.pid is not None]
    return usb_serial[0] if len(usb_serial) == 1 else None


def _minutes_until(reset_time: str, now: float) -> int:
    """Convert Antigravity's ISO reset time into the firmware's minutes field."""
    reset_at = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
    return max(0, int((reset_at.timestamp() - now) / 60))


def parse_antigravity_usage(output: str, *, now: float | None = None) -> dict | None:
    """Extract only the Gemini Models group from `agy -p /usage --output-format json`."""
    try:
        command = json.loads(output).get("command", {})
        groups = command.get("data", {}).get("groups", [])
        gemini = next(group for group in groups if group.get("name", "").lower() == "gemini models")
        buckets = {bucket.get("window"): bucket for bucket in gemini.get("buckets", [])}
        weekly = buckets["weekly"]
        five_hours = buckets["5h"]
        timestamp = time.time() if now is None else now
        weekly_remaining = float(weekly["remaining_fraction"])
        five_hour_remaining = float(five_hours["remaining_fraction"])
        return {
            "p": "gemini",
            "s": round((1 - five_hour_remaining) * 100, 1),
            "sr": _minutes_until(five_hours["reset_time"], timestamp),
            "w": round((1 - weekly_remaining) * 100, 1),
            "wr": _minutes_until(weekly["reset_time"], timestamp),
            "st": "allowed",
            "ok": True,
            "t": int(timestamp),
        }
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError):
        return None


def read_gemini_payload() -> dict:
    """Read Gemini quota via Antigravity's non-interactive, read-only /usage command."""
    agy = shutil.which("agy") or shutil.which("agy.exe")
    if not agy:
        return {"p": "gemini", "ok": False, "st": "unavailable"}
    try:
        no_window_flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        result = subprocess.run(
            [agy, "-p", "/usage", "--output-format", "json"],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
            creationflags=no_window_flag,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"p": "gemini", "ok": False, "st": "unavailable"}
    payload = parse_antigravity_usage(result.stdout)
    return payload or {"p": "gemini", "ok": False, "st": "unavailable"}


DEVICE_CONFIG_FILE = _REPO_ROOT / "daemon" / "device_config.json"
HISTORY_FILE = _REPO_ROOT / "daemon" / "history.jsonl"
HISTORY_INTERVAL_SECONDS = 300  # one sample every 5 minutes


def _read_device_config() -> dict:
    try:
        if DEVICE_CONFIG_FILE.exists():
            with DEVICE_CONFIG_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def get_target_brightness(config: dict | None = None) -> int:
    """Return target display brightness percentage (10..100), default 80%."""
    data = config if config is not None else _read_device_config()
    try:
        return max(10, min(100, int(data.get("brightness", 80))))
    except (TypeError, ValueError):
        return 80


def get_clock_mode(config: dict | None = None) -> str:
    """Return the clock display mode: off|24|12."""
    data = config if config is not None else _read_device_config()
    mode = data.get("clock", "off")
    return mode if mode in ("off", "24", "12") else "off"


def get_enabled_providers(config: dict | None = None) -> dict:
    """Return which providers should be sent to the CYD (default: all on)."""
    data = config if config is not None else _read_device_config()
    enabled = data.get("enabled_providers", {})
    return {
        "codex": bool(enabled.get("codex", True)),
        "claude": bool(enabled.get("claude", True)),
        "gemini": bool(enabled.get("gemini", True)),
    }


def _clock_fields(clock_mode: str) -> dict:
    """"t"/"tf" fields the firmware reads to drive its title-bar clock."""
    if clock_mode not in ("24", "12"):
        return {}
    return {"t": int(time.time()) + time.localtime().tm_gmtoff, "tf": 24 if clock_mode == "24" else 12}


def _append_history(payload_list: list[dict]) -> None:
    """Append one usage sample per provider to the local history log.

    Delegates to usage_common.append_history_record, which locks a sibling
    .lock file around the read-modify-write so this (the bridge, running as
    its own process) never races tokendeck_gui.py's direct-query fallback,
    which can write the same file concurrently.
    """
    record: dict = {"ts": time.time()}
    for payload in payload_list:
        provider = payload.get("p")
        if provider not in ("claude", "codex", "gemini"):
            continue
        record[provider] = {"s": payload.get("s"), "w": payload.get("w")} if payload.get("ok") else None
    append_history_record(HISTORY_FILE, record)


def payloads(claude_payload: dict | None, gemini_payload: dict | None,
             active_provider: str = "", brightness_pwm: int | None = None,
             enabled: dict | None = None, clock_mode: str = "off") -> list[dict]:
    enabled = enabled or {"codex": True, "claude": True, "gemini": True}

    if enabled.get("codex", True):
        codex = read_codex_payload() or {"ok": False}
    else:
        codex = {"ok": False, "st": "disabled"}
    codex["p"] = "codex"

    if enabled.get("claude", True):
        claude = dict(claude_payload or {"ok": False})
    else:
        claude = {"ok": False, "st": "disabled"}
    claude["p"] = "claude"

    if enabled.get("gemini", True):
        gemini = dict(gemini_payload or {"ok": False})
    else:
        gemini = {"ok": False, "st": "disabled"}
    gemini["p"] = "gemini"

    result = [codex, claude, gemini]
    if active_provider:
        for payload in result:
            payload["a"] = active_provider
    if brightness_pwm is not None:
        for payload in result:
            payload["brt"] = brightness_pwm
    clock_extra = _clock_fields(clock_mode)
    if clock_extra:
        for payload in result:
            payload.update(clock_extra)
    return result


def main() -> None:
    print("TokenDeck USB bridge iniciado. Pressione Ctrl+C para parar.")
    # Held for the life of this process so tokendeck_gui.py's
    # is_bridge_running() can detect us; Windows releases it automatically
    # on exit/crash. Keep the reference even though it's unused — letting it
    # go out of scope doesn't close the handle, but naming it documents why
    # this call exists here.
    _singleton_mutex = _acquire_singleton_mutex()
    device: serial.Serial | None = None
    claude_payload: dict | None = None
    gemini_payload: dict | None = None
    activity_monitor = ActivityMonitor()
    active_provider = ""
    next_claude = 0.0
    next_gemini = 0.0
    next_history = 0.0
    # Visible health signal for the GUI (see "reconnects" in latest_status.json):
    # this device runs unattended for long stretches, so a climbing count here
    # is the first sign of a flaky cable/port before the user notices a blank
    # CYD screen. The first successful open is a connect, not a reconnect.
    connect_count = 0
    try:
        while True:
            if device is None or not device.is_open:
                port = find_port()
                if not port:
                    print("CYD não encontrada; conecte o cabo USB de dados.")
                    time.sleep(UPDATE_SECONDS)
                    continue
                try:
                    # On many CYD boards the CH340 DTR/RTS lines are wired to EN/BOOT.
                    # Set them inactive before opening so attaching the bridge does not
                    # reset the ESP32 or put it into its bootloader.
                    device = serial.Serial()
                    device.port = port
                    device.baudrate = BAUDRATE
                    device.timeout = 1
                    device.write_timeout = 2
                    device.dtr = False
                    device.rts = False
                    device.open()
                    connect_count += 1
                    print(f"CYD conectada em {port}.")
                    time.sleep(0.25)
                except serial.SerialException as exc:
                    print(f"Não foi possível abrir {port}: {exc}")
                    device = None
                    time.sleep(UPDATE_SECONDS)
                    continue

            now = time.monotonic()
            device_config = _read_device_config()
            enabled_providers = get_enabled_providers(device_config)
            clock_mode = get_clock_mode(device_config)

            if enabled_providers["claude"] and now >= next_claude:
                try:
                    token = read_token()
                    claude_payload = asyncio.run(poll_api(token)) if token else None
                except AuthError:
                    claude_payload = None
                except Exception as exc:
                    print(f"Claude poll error: {exc}")
                    claude_payload = None
                next_claude = now + CLAUDE_REFRESH_SECONDS

            if enabled_providers["gemini"] and now >= next_gemini:
                gemini_payload = read_gemini_payload()
                next_gemini = now + GEMINI_REFRESH_SECONDS

            try:
                target_pct = get_target_brightness(device_config)
                target_pwm = int(round(target_pct * 255.0 / 100.0))

                detected_provider = activity_monitor.poll()
                if detected_provider and enabled_providers.get(detected_provider, True):
                    active_provider = detected_provider
                current_payloads = payloads(
                    claude_payload, gemini_payload, active_provider, target_pwm,
                    enabled=enabled_providers, clock_mode=clock_mode,
                )
                for payload in current_payloads:
                    device.write(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
                device.flush()
                last_sent_brightness_pwm = target_pwm

                now_wall = time.time()
                if now_wall >= next_history:
                    _append_history(current_payloads)
                    next_history = now_wall + HISTORY_INTERVAL_SECONDS
                try:
                    status_path = _REPO_ROOT / "daemon" / "latest_status.json"
                    status_data = {
                        "updated_at": time.time(),
                        "active_provider": active_provider,
                        "port": port,
                        "brightness": target_pct,
                        "payloads": {p["p"]: p for p in current_payloads},
                        "reconnects": max(0, connect_count - 1),
                    }
                    status_path.write_text(json.dumps(status_data, indent=2), encoding="utf-8")
                except Exception:
                    pass
            except (serial.SerialException, OSError) as exc:
                print(f"Conexão USB perdida: {exc}")
                device.close()
                device = None

            # Sleep in short slices so user brightness slider updates react instantly (< 300ms)
            sleep_slices = int(UPDATE_SECONDS / 0.3)
            for _ in range(sleep_slices):
                time.sleep(0.3)
                if device is not None and device.is_open:
                    cur_pct = get_target_brightness()
                    cur_pwm = int(round(cur_pct * 255.0 / 100.0))
                    if cur_pwm != last_sent_brightness_pwm:
                        try:
                            device.write(json.dumps({"brt": cur_pwm}, separators=(",", ":")).encode() + b"\n")
                            device.flush()
                            last_sent_brightness_pwm = cur_pwm
                        except (serial.SerialException, OSError):
                            break
    except KeyboardInterrupt:
        print("\nTokenDeck USB bridge finalizado.")
    finally:
        if device is not None and device.is_open:
            device.close()


if __name__ == "__main__":
    main()
