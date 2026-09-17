"""
TokenDeck — Desktop App (GPU-Accelerated WebView2)
Painel nativo com aceleração por hardware (GPU) via Microsoft Edge WebView2 e PyWebView.
Executa a animação de Expanding Cards em 60-144 FPS suaves com transição por hover (onMouseEnter).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
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
DEVICE_CONFIG_FILE = _REPO_ROOT / "daemon" / "device_config.json"
HISTORY_FILE = _REPO_ROOT / "daemon" / "history.jsonl"
HISTORY_LOG_INTERVAL = 300  # seconds; mirrors usage_serial_bridge_windows.py's own sampling rate


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
        self.last_history_write = 0.0

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

    def _read_device_config(self) -> dict:
        try:
            if DEVICE_CONFIG_FILE.exists():
                with DEVICE_CONFIG_FILE.open("r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _write_device_config(self, patch: dict) -> dict:
        """Merge ``patch`` into device_config.json, preserving unrelated keys."""
        data = self._read_device_config()
        data.update(patch)
        data["updated_at"] = time.time()
        try:
            DEVICE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with DEVICE_CONFIG_FILE.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    def get_brightness(self) -> int:
        data = self._read_device_config()
        try:
            return max(10, min(100, int(data.get("brightness", 80))))
        except (TypeError, ValueError):
            return 80

    def get_device_config(self) -> dict:
        """Preferências persistidas do dispositivo, para a tela de Configurações."""
        data = self._read_device_config()
        enabled = data.get("enabled_providers", {})
        clock = data.get("clock", "off")
        return {
            "brightness": self.get_brightness(),
            "clock": clock if clock in ("off", "24", "12") else "off",
            "enabled_providers": {
                "claude": bool(enabled.get("claude", True)),
                "codex": bool(enabled.get("codex", True)),
                "gemini": bool(enabled.get("gemini", True)),
            },
        }

    def set_clock_mode(self, mode: str) -> dict:
        """Liga/desliga o relógio no título da tela do CYD (off|24|12)."""
        mode = mode if mode in ("off", "24", "12") else "off"
        return self._write_device_config({"clock": mode})

    def set_provider_enabled(self, provider: str, enabled: bool) -> dict:
        """Liga/desliga o envio de um provedor para a bridge/CYD."""
        if provider not in ("claude", "codex", "gemini"):
            return {"ok": False, "error": "provedor inválido"}
        current = self.get_device_config()["enabled_providers"]
        current[provider] = bool(enabled)
        return self._write_device_config({"enabled_providers": current})

    def set_brightness(self, level: int) -> dict:
        """Define o brilho da tela do ESP32 CYD (10..100%)."""
        val = max(10, min(100, int(level)))
        result = self._write_device_config({"brightness": val})
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error"), "brightness": val}

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

        # A bridge USB (quando ativa) já grava o próprio histórico a cada 5 min;
        # aqui só gravamos no modo de consulta direta, pra não duplicar amostras.
        if not (cached and bridge_active):
            self._maybe_log_history(codex_data, claude_data, gemini_data)

        return {
            "port": port,
            "bridge_active": bridge_active,
            "active_provider": active_provider,
            "source_mode": source_mode,
            "brightness": brightness,
            "config": self.get_device_config(),
            "codex": codex_data,
            "claude": claude_data,
            "gemini": gemini_data,
            "markers": markers,
            "timestamp": time.time(),
        }

    def _maybe_log_history(self, codex_data: dict, claude_data: dict, gemini_data: dict) -> None:
        now = time.time()
        if now - self.last_history_write < HISTORY_LOG_INTERVAL:
            return
        self.last_history_write = now
        record = {"ts": now}
        for name, data in (("codex", codex_data), ("claude", claude_data), ("gemini", gemini_data)):
            record[name] = {"s": data.get("s"), "w": data.get("w")} if data.get("ok") else None
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with HISTORY_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            pass

    def get_history(self, days: int = 7) -> dict:
        """Resumo diário + série temporal para a tela de Histórico.

        Lê daemon/history.jsonl (gravado pela bridge USB e, no modo de
        consulta direta, por esta própria classe) e agrega por dia local.
        """
        cutoff = time.time() - days * 86400
        records: list[dict] = []
        try:
            if HISTORY_FILE.exists():
                for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("ts", 0) >= cutoff:
                        records.append(rec)
        except OSError:
            pass

        empty = {"has_data": False, "days": [], "series": {"claude": [], "codex": [], "gemini": []}, "stats": None}
        if not records:
            return empty

        by_day: dict[str, list[dict]] = defaultdict(list)
        for rec in records:
            day_key = datetime.fromtimestamp(rec["ts"]).strftime("%Y-%m-%d")
            by_day[day_key].append(rec)

        day_keys = sorted(by_day.keys())
        series: dict[str, list[float]] = {"claude": [], "codex": [], "gemini": []}
        days_out: list[dict] = []
        peak = {"pct": -1.0, "provider": None, "day": None}
        prev_s: dict[str, float | None] = {"claude": None, "codex": None, "gemini": None}
        reset_count = 0
        daily_avgs: list[float] = []

        for day_key in day_keys:
            day_records = by_day[day_key]
            day_peak = {"provider": None, "pct": -1.0}
            day_values: list[float] = []
            for provider in ("claude", "codex", "gemini"):
                vals = [r[provider]["s"] for r in day_records
                        if r.get(provider) and r[provider].get("s") is not None]
                for v in vals:
                    if prev_s[provider] is not None and prev_s[provider] - v > 40:
                        reset_count += 1
                    prev_s[provider] = v
                day_max = max(vals) if vals else 0.0
                series[provider].append(round(day_max, 1))
                day_values.extend(vals)
                if day_max > day_peak["pct"]:
                    day_peak = {"provider": provider, "pct": day_max}
                if day_max > peak["pct"]:
                    peak = {"pct": day_max, "provider": provider, "day": day_key}
            day_avg = round(sum(day_values) / len(day_values), 1) if day_values else 0.0
            daily_avgs.append(day_avg)
            days_out.append({
                "date": day_key,
                "peak_provider": day_peak["provider"],
                "peak_pct": round(day_peak["pct"], 1) if day_peak["pct"] >= 0 else 0,
                "avg_pct": day_avg,
            })

        avg_daily = round(sum(daily_avgs) / len(daily_avgs), 1) if daily_avgs else 0.0
        return {
            "has_data": True,
            "days": days_out[-days:],
            "series": {k: v[-days:] for k, v in series.items()},
            "stats": {
                "peak_pct": round(peak["pct"], 1),
                "peak_provider": peak["provider"],
                "peak_day": peak["day"],
                "avg_daily": avg_daily,
                "resets": reset_count,
                "sample_count": len(records),
            },
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
