"""
TokenDeck — Desktop App (GPU-Accelerated WebView2)
Painel nativo com aceleração por hardware (GPU) via Microsoft Edge WebView2 e PyWebView.
Executa a animação de Expanding Cards em 60-144 FPS suaves com transição por hover (onMouseEnter).
"""

from __future__ import annotations

import asyncio
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import webview

# Adiciona a raiz do repositório ao sys.path para importar os módulos do daemon
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from daemon.claude_usage_daemon_windows import AuthError, poll_api, read_token
from daemon.codex_usage_daemon_windows import read_codex_payload
from daemon.usage_serial_bridge_windows import (
    activity_markers,
    find_port,
    read_gemini_payload,
)

MUTEX_BRIDGE_NAME = "Local\\TokenDeckUsbBridge"


def is_bridge_running() -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenMutexW(0x00100000, False, MUTEX_BRIDGE_NAME)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # Verifica também o mutex legado para compatibilidade
        handle_legacy = kernel32.OpenMutexW(0x00100000, False, "Local\\TokenMeterUsbBridge")
        if handle_legacy:
            kernel32.CloseHandle(handle_legacy)
            return True
    except Exception:
        pass
    return False


def stop_bridge_process() -> bool:
    try:
        ps_cmd = (
            '$procs = Get-CimInstance Win32_Process | '
            'Where-Object { $_.CommandLine -like "*usage_serial_bridge_windows.py*" }; '
            'foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force }'
        )
        no_window_flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            timeout=8,
            capture_output=True,
            creationflags=no_window_flag,
        )
        return True
    except Exception:
        return False


class TokenDeckBridgeApi:
    """API em Python exposta diretamente para o JavaScript via window.pywebview.api."""

    def __init__(self):
        self.cached_claude: dict | None = None
        self.next_claude_poll = 0.0
        self.active_cyd_provider = "gemini"

    def read_cached_status(self) -> dict | None:
        status_file = _REPO_ROOT / "daemon" / "latest_status.json"
        try:
            if status_file.exists():
                with status_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    if time.time() - data.get("updated_at", 0) < 15:
                        return data
        except Exception:
            pass
        return None

    def get_brightness(self) -> int:
        config_file = _REPO_ROOT / "daemon" / "device_config.json"
        try:
            if config_file.exists():
                with config_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    return max(10, min(100, int(data.get("brightness", 80))))
        except Exception:
            pass
        return 80

    def set_brightness(self, level: int) -> dict:
        """Define o brilho da tela do ESP32 CYD (10..100%)."""
        val = max(10, min(100, int(level)))
        config_file = _REPO_ROOT / "daemon" / "device_config.json"
        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with config_file.open("w", encoding="utf-8") as f:
                json.dump({"brightness": val, "updated_at": time.time()}, f, indent=2)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "brightness": val}

        pwm = int(round(val * 255.0 / 100.0))
        bridge_active = is_bridge_running()

        # Se a bridge não estiver ativa, tenta enviar o comando direto via COM
        if not bridge_active:
            port = find_port()
            if port:
                try:
                    import serial
                    with serial.Serial(port=port, baudrate=115200, timeout=1, write_timeout=1) as ser:
                        ser.dtr = False
                        ser.rts = False
                        ser.write(f'{{"brt":{pwm}}}\n'.encode("utf-8"))
                        ser.flush()
                except Exception:
                    pass

        return {"ok": True, "brightness": val, "pwm": pwm, "bridge_active": bridge_active}

    def get_status(self) -> dict:
        """Coleta o estado dos 3 modelos, porta serial e bridge."""
        port = find_port()
        bridge_active = is_bridge_running()
        markers = activity_markers()
        last_active = max(markers, key=markers.get, default="") if markers else ""
        if last_active:
            self.active_cyd_provider = last_active

        cached = self.read_cached_status()
        brightness = self.get_brightness()
        if cached and bridge_active:
            payloads = cached.get("payloads", {})
            codex_data = payloads.get("codex", {})
            claude_data = payloads.get("claude", {})
            gemini_data = payloads.get("gemini", {})
            active_provider = cached.get("active_provider") or self.active_cyd_provider
            source_mode = "Sincronizado via Bridge USB (COM4)"
            if "brightness" in cached:
                brightness = cached["brightness"]
        else:
            source_mode = "Consulta Direta (Modo App)"
            codex_data = read_codex_payload() or {"ok": False}
            gemini_data = read_gemini_payload() or {"ok": False}

            now_m = time.monotonic()
            if now_m >= self.next_claude_poll:
                try:
                    token = read_token()
                    if token:
                        self.cached_claude = asyncio.run(poll_api(token))
                    else:
                        self.cached_claude = None
                except Exception:
                    self.cached_claude = None
                self.next_claude_poll = now_m + 60
            claude_data = self.cached_claude or {"ok": False}
            active_provider = self.active_cyd_provider

        return {
            "port": port,
            "bridge_active": bridge_active,
            "active_provider": active_provider,
            "source_mode": source_mode,
            "brightness": brightness,
            "codex": codex_data,
            "claude": claude_data,
            "gemini": gemini_data,
            "markers": markers,
            "timestamp": time.time(),
        }

    def toggle_bridge(self) -> bool:
        if is_bridge_running():
            stop_bridge_process()
            time.sleep(0.8)
            return False
        else:
            bridge_script = _REPO_ROOT / "daemon" / "usage_serial_bridge_windows.py"
            pythonw = _REPO_ROOT / "daemon" / ".venv" / "Scripts" / "pythonw.exe"
            if not pythonw.exists():
                pythonw = Path(sys.executable).with_name("pythonw.exe")
            if not pythonw.exists():
                pythonw = Path(sys.executable)

            no_window_flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            subprocess.Popen(
                [str(pythonw), str(bridge_script)],
                cwd=str(_REPO_ROOT),
                creationflags=no_window_flag,
            )
            time.sleep(1.0)
            return is_bridge_running()

    def flash_firmware(self) -> bool:
        record_cmd = _REPO_ROOT / "tokendeck-record.cmd"
        if not record_cmd.exists():
            return False

        if is_bridge_running():
            stop_bridge_process()
            time.sleep(1.0)

        subprocess.Popen(
            ["cmd.exe", "/c", "start", "Gravar Firmware CYD", str(record_cmd)],
            shell=True,
            cwd=str(_REPO_ROOT),
        )
        return True


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TokenDeck.Studio.Monitor")
    except Exception:
        pass

    api = TokenDeckBridgeApi()
    html_path = _REPO_ROOT / "gui" / "index.html"
    icon_path = _REPO_ROOT / "assets" / "tokendeck.ico"

    # Cria uma janela nativa com motor WebView2 (aceleração por GPU cravada a 120 FPS)
    window = webview.create_window(
        title="TokenDeck — Multi-Model AI Usage Monitor",
        url=str(html_path.resolve()),
        js_api=api,
        width=1160,
        height=720,
        min_size=(960, 580),
        background_color="#0d1117",
    )

    webview.start(debug=False, icon=str(icon_path.resolve()) if icon_path.exists() else None)


if __name__ == "__main__":
    main()
