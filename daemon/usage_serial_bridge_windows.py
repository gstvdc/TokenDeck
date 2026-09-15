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
        "gemini": home / ".gemini" / "antigravity-ide" / "conversations",
    }


def last_active_provider(roots: dict[str, Path] | None = None) -> str:
    """Return the assistant whose conversation record was written most recently.

    This observes local activity only; it does not inspect terminal contents or
    transmit prompts. A command that creates a conversation update therefore
    becomes visible on the display within the bridge's next five-second cycle.
    """
    newest_provider = ""
    newest_mtime = -1.0
    for provider, root in (roots or _activity_roots()).items():
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                if mtime > newest_mtime:
                    newest_provider, newest_mtime = provider, mtime
        except OSError:
            continue
    return newest_provider


def find_port() -> str | None:
    """Return the CYD's CH340 port; never select the PC's built-in COM ports."""
    ports = list(list_ports.comports())
    ch340 = [port.device for port in ports if port.vid == 0x1A86 and port.pid in (0x7523, 0x55D4)]
    if ch340:
        return ch340[0]
    usb_serial = [port.device for port in ports if port.vid is not None and port.pid is not None]
    return usb_serial[0] if len(usb_serial) == 1 else None


def _seconds_until(reset_time: str, now: float) -> int:
    """Convert Antigravity's ISO reset time into the firmware's seconds field."""
    reset_at = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
    return max(0, int(reset_at.timestamp() - now))


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
            "sr": _seconds_until(five_hours["reset_time"], timestamp),
            "w": round((1 - weekly_remaining) * 100, 1),
            "wr": _seconds_until(weekly["reset_time"], timestamp),
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
        result = subprocess.run(
            [agy, "-p", "/usage", "--output-format", "json"],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"p": "gemini", "ok": False, "st": "unavailable"}
    payload = parse_antigravity_usage(result.stdout)
    return payload or {"p": "gemini", "ok": False, "st": "unavailable"}


def payloads(claude_payload: dict | None, gemini_payload: dict | None,
             active_provider: str = "") -> list[dict]:
    codex = read_codex_payload() or {"ok": False}
    codex["p"] = "codex"
    claude = dict(claude_payload or {"ok": False})
    claude["p"] = "claude"
    gemini = dict(gemini_payload or {"ok": False})
    gemini["p"] = "gemini"
    if active_provider:
        for payload in (codex, claude, gemini):
            payload["a"] = active_provider
    return [codex, claude, gemini]


def main() -> None:
    print("TokenMeter USB bridge iniciado. Pressione Ctrl+C para parar.")
    device: serial.Serial | None = None
    claude_payload: dict | None = None
    gemini_payload: dict | None = None
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
                active_provider = last_active_provider()
                for payload in payloads(claude_payload, gemini_payload, active_provider):
                    device.write(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
                device.flush()
            except (serial.SerialException, OSError) as exc:
                print(f"Conexão USB perdida: {exc}")
                device.close()
                device = None
            time.sleep(UPDATE_SECONDS)
    except KeyboardInterrupt:
        print("\nTokenMeter USB bridge finalizado.")
    finally:
        if device is not None and device.is_open:
            device.close()


if __name__ == "__main__":
    main()
