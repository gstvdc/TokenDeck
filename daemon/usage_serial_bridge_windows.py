"""Send Codex, Claude, and Gemini CLI usage to the CYD through USB serial."""
from __future__ import annotations

import asyncio
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

BAUDRATE = 115200
UPDATE_SECONDS = 5
CLAUDE_REFRESH_SECONDS = 60
GEMINI_REFRESH_SECONDS = 60


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


def get_target_brightness() -> int:
    """Return target display brightness percentage (10..100), default 80%."""
    config_file = _REPO_ROOT / "daemon" / "device_config.json"
    try:
        if config_file.exists():
            with config_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                val = int(data.get("brightness", 80))
                return max(10, min(100, val))
    except Exception:
        pass
    return 80


def payloads(claude_payload: dict | None, gemini_payload: dict | None,
             active_provider: str = "", brightness_pwm: int | None = None) -> list[dict]:
    codex = read_codex_payload() or {"ok": False}
    codex["p"] = "codex"
    claude = dict(claude_payload or {"ok": False})
    claude["p"] = "claude"
    gemini = dict(gemini_payload or {"ok": False})
    gemini["p"] = "gemini"
    if active_provider:
        for payload in (codex, claude, gemini):
            payload["a"] = active_provider
    if brightness_pwm is not None:
        for payload in (codex, claude, gemini):
            payload["brt"] = brightness_pwm
    return [codex, claude, gemini]


def main() -> None:
    print("TokenDeck USB bridge iniciado. Pressione Ctrl+C para parar.")
    device: serial.Serial | None = None
    claude_payload: dict | None = None
    gemini_payload: dict | None = None
    activity_monitor = ActivityMonitor()
    active_provider = ""
    next_claude = 0.0
    next_gemini = 0.0
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
                    print(f"CYD conectada em {port}.")
                    time.sleep(0.25)
                except serial.SerialException as exc:
                    print(f"Não foi possível abrir {port}: {exc}")
                    device = None
                    time.sleep(UPDATE_SECONDS)
                    continue

            now = time.monotonic()
            if now >= next_claude:
                try:
                    token = read_token()
                    claude_payload = asyncio.run(poll_api(token)) if token else None
                except AuthError:
                    claude_payload = None
                except Exception as exc:
                    print(f"Claude poll error: {exc}")
                    claude_payload = None
                next_claude = now + CLAUDE_REFRESH_SECONDS

            if now >= next_gemini:
                gemini_payload = read_gemini_payload()
                next_gemini = now + GEMINI_REFRESH_SECONDS

            try:
                target_pct = get_target_brightness()
                target_pwm = int(round(target_pct * 255.0 / 100.0))

                detected_provider = activity_monitor.poll()
                if detected_provider:
                    active_provider = detected_provider
                current_payloads = payloads(claude_payload, gemini_payload, active_provider, target_pwm)
                for payload in current_payloads:
                    device.write(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
                device.flush()
                last_sent_brightness_pwm = target_pwm
                try:
                    status_path = _REPO_ROOT / "daemon" / "latest_status.json"
                    status_data = {
                        "updated_at": time.time(),
                        "active_provider": active_provider,
                        "port": port,
                        "brightness": target_pct,
                        "payloads": {p["p"]: p for p in current_payloads},
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
