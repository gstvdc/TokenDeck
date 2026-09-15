"""
TokenMeter Studio - Desktop GUI
Painel visual moderno em CustomTkinter para monitorar Codex/GPT, Claude e Gemini em tempo real.
Inclui atalhos para Iniciar/Parar a Bridge USB, Gravar Firmware na CYD e Atualização manual.
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

import customtkinter as ctk

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

# Configurações visuais do CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Paleta de Cores
COLOR_BG = "#0d1117"
COLOR_HEADER = "#161b22"
COLOR_TOOLBAR = "#12151c"
COLOR_CARD = "#161b22"
COLOR_BORDER = "#30363d"
COLOR_TEXT = "#f0f6fc"
COLOR_TEXT_MUTED = "#8b949e"
COLOR_PROGRESS_TRACK = "#21262d"

# Cores de Identidade de Cada Modelo
COLOR_CODEX = "#10a37f"   # Verde OpenAI
COLOR_CLAUDE = "#f59e0b"  # Âmbar / Laranja Anthropic
COLOR_GEMINI = "#a855f7"  # Roxo Google Gemini

# Mutex do Windows usado por run-usb-bridge.ps1
MUTEX_BRIDGE_NAME = "Local\\TokenMeterUsbBridge"


def is_bridge_running() -> bool:
    """Verifica via mutex do Windows se o script run-usb-bridge.ps1 está em execução."""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenMutexW(0x00100000, False, MUTEX_BRIDGE_NAME)
        if handle:
            kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    return False


def stop_bridge_process() -> bool:
    """Finaliza o processo da bridge USB de forma limpa para liberar a COM4."""
    try:
        ps_cmd = (
            '$procs = Get-CimInstance Win32_Process | '
            'Where-Object { $_.CommandLine -like "*usage_serial_bridge_windows.py*" }; '
            'foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force }'
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            shell=True,
            timeout=8,
            capture_output=True,
        )
        return True
    except Exception:
        return False


def format_minutes_human(minutes: int | float | None) -> str:
    """Converte minutos em formato legível como '1h 50m (110 min)'."""
    if minutes is None or minutes < 0:
        return "--"
    mins = int(minutes)
    if mins == 0:
        return "Agora mesmo (0 min)"
    if mins < 60:
        return f"{mins} min"
    
    hours = mins // 60
    rem_mins = mins % 60
    if hours < 24:
        return f"{hours}h {rem_mins}m ({mins} min)"
    
    days = hours // 24
    rem_hours = hours % 24
    return f"{days}d {rem_hours}h ({mins} min)"


class ProviderCard(ctk.CTkFrame):
    """Card individual com visual moderno para cada IA."""

    def __init__(
        self,
        parent,
        title: str,
        badge_name: str,
        subtitle: str,
        accent_color: str,
    ):
        super().__init__(
            parent,
            fg_color=COLOR_CARD,
            corner_radius=14,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        self.accent_color = accent_color
        self.is_active_on_cyd = False

        # Topo do Card
        self.top_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_frame.pack(fill="x", padx=16, pady=(16, 6))

        self.title_label = ctk.CTkLabel(
            self.top_frame,
            text=title,
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLOR_TEXT,
        )
        self.title_label.pack(side="left")

        self.active_badge = ctk.CTkLabel(
            self.top_frame,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=accent_color,
            fg_color="transparent",
            corner_radius=6,
            padx=6,
            pady=2,
        )
        self.active_badge.pack(side="right")

        # Subtítulo com provedor e badge de conta
        self.sub_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.sub_frame.pack(fill="x", padx=16, pady=(0, 10))

        self.subtitle_label = ctk.CTkLabel(
            self.sub_frame,
            text=subtitle,
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        self.subtitle_label.pack(side="left")

        self.account_badge = ctk.CTkLabel(
            self.sub_frame,
            text=badge_name,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=accent_color,
            fg_color="#1f2430",
            corner_radius=6,
            padx=8,
            pady=1,
        )
        self.account_badge.pack(side="right")

        # Linha divisória sutil
        divider = ctk.CTkFrame(self, height=1, fg_color=COLOR_BORDER)
        divider.pack(fill="x", padx=16, pady=(0, 14))

        # ----------------- SEÇÃO: JANELA DE 5 HORAS -----------------
        self.lbl_5h_title = ctk.CTkLabel(
            self,
            text="Janela de 5 Horas",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#c9d1d9",
        )
        self.lbl_5h_title.pack(anchor="w", padx=16)

        self.frame_5h = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_5h.pack(fill="x", padx=16, pady=(3, 3))

        self.progress_5h = ctk.CTkProgressBar(
            self.frame_5h,
            height=12,
            corner_radius=6,
            progress_color=accent_color,
            fg_color=COLOR_PROGRESS_TRACK,
        )
        self.progress_5h.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.progress_5h.set(0.0)

        self.lbl_5h_pct = ctk.CTkLabel(
            self.frame_5h,
            text="0%",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLOR_TEXT,
            width=52,
            anchor="e",
        )
        self.lbl_5h_pct.pack(side="right")

        self.lbl_5h_reset = ctk.CTkLabel(
            self,
            text="Renova em: --",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        self.lbl_5h_reset.pack(anchor="w", padx=16, pady=(0, 16))

        # ----------------- SEÇÃO: LIMITE SEMANAL -----------------
        self.lbl_week_title = ctk.CTkLabel(
            self,
            text="Limite Semanal",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#c9d1d9",
        )
        self.lbl_week_title.pack(anchor="w", padx=16)

        self.frame_week = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_week.pack(fill="x", padx=16, pady=(3, 3))

        self.progress_week = ctk.CTkProgressBar(
            self.frame_week,
            height=12,
            corner_radius=6,
            progress_color=accent_color,
            fg_color=COLOR_PROGRESS_TRACK,
        )
        self.progress_week.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.progress_week.set(0.0)

        self.lbl_week_pct = ctk.CTkLabel(
            self.frame_week,
            text="0%",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLOR_TEXT,
            width=52,
            anchor="e",
        )
        self.lbl_week_pct.pack(side="right")

        self.lbl_week_reset = ctk.CTkLabel(
            self,
            text="Renova em: --",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        self.lbl_week_reset.pack(anchor="w", padx=16, pady=(0, 18))

        # ----------------- RODAPÉ DO CARD -----------------
        self.footer = ctk.CTkFrame(self, fg_color="#0f1319", corner_radius=10)
        self.footer.pack(fill="x", padx=14, pady=(0, 14), side="bottom")

        self.lbl_status = ctk.CTkLabel(
            self.footer,
            text="Status: OK",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED,
        )
        self.lbl_status.pack(anchor="w", padx=12, pady=(6, 1))

        self.lbl_activity = ctk.CTkLabel(
            self.footer,
            text="Último prompt: --:--:--",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED,
        )
        self.lbl_activity.pack(anchor="w", padx=12, pady=(1, 6))

    def update_card(
        self,
        pct_5h: float,
        reset_5h_min: int | float | None,
        pct_week: float,
        reset_week_min: int | float | None,
        status_text: str,
        activity_str: str,
        account_name: str | None = None,
        is_active_cyd: bool = False,
    ):
        val_5h = min(max(pct_5h / 100.0, 0.0), 1.0)
        self.progress_5h.set(val_5h)
        self.lbl_5h_pct.configure(text=f"{pct_5h:.1f}%" if pct_5h % 1 != 0 else f"{int(pct_5h)}%")
        self.lbl_5h_reset.configure(text=f"Renova em: {format_minutes_human(reset_5h_min)}")

        val_week = min(max(pct_week / 100.0, 0.0), 1.0)
        self.progress_week.set(val_week)
        self.lbl_week_pct.configure(text=f"{pct_week:.1f}%" if pct_week % 1 != 0 else f"{int(pct_week)}%")
        self.lbl_week_reset.configure(text=f"Renova em: {format_minutes_human(reset_week_min)}")

        self.lbl_status.configure(text=f"Status: {status_text}")
        self.lbl_activity.configure(text=f"Último prompt: {activity_str}")

        if account_name:
            self.account_badge.configure(text=account_name)

        if is_active_cyd:
            self.configure(border_color=self.accent_color, border_width=2)
            self.active_badge.configure(
                text="● NA TELA CYD",
                fg_color="#211d33",
            )
        else:
            self.configure(border_color=COLOR_BORDER, border_width=1)
            self.active_badge.configure(text="", fg_color="transparent")


class TokenMeterApp(ctk.CTk):
    """Janela principal do TokenDeck com botões de controle."""

    def __init__(self):
        super().__init__()

        self.title("TokenDeck — Multi-Model AI Usage Monitor")
        self.geometry("1100x670")
        self.minsize(1020, 620)
        self.configure(fg_color=COLOR_BG)

        # ----------------- 1. HEADER BAR -----------------
        self.header = ctk.CTkFrame(self, fg_color=COLOR_HEADER, corner_radius=0, height=64)
        self.header.pack(fill="x", side="top")

        self.title_box = ctk.CTkFrame(self.header, fg_color="transparent")
        self.title_box.pack(side="left", padx=20, pady=12)

        self.title_label = ctk.CTkLabel(
            self.title_box,
            text="⚡ TOKENDECK",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#ffffff",
        )
        self.title_label.pack(side="left")

        self.badge_version = ctk.CTkLabel(
            self.title_box,
            text="CYD 2.8\" USB",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#58a6ff",
            fg_color="#1f2d47",
            corner_radius=6,
            padx=8,
            pady=2,
        )
        self.badge_version.pack(side="left", padx=(10, 0))

        # Indicadores de status no cabeçalho
        self.header_status_box = ctk.CTkFrame(self.header, fg_color="transparent")
        self.header_status_box.pack(side="right", padx=20)

        self.bridge_pill = ctk.CTkLabel(
            self.header_status_box,
            text="● Bridge Ativa",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#3fb950",
            fg_color="#182c20",
            corner_radius=8,
            padx=12,
            pady=4,
        )
        self.bridge_pill.pack(side="left", padx=(0, 10))

        self.cyd_screen_pill = ctk.CTkLabel(
            self.header_status_box,
            text="Tela CYD: Gemini",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLOR_GEMINI,
            fg_color="#271c3b",
            corner_radius=8,
            padx=12,
            pady=4,
        )
        self.cyd_screen_pill.pack(side="left", padx=(0, 10))

        self.serial_pill = ctk.CTkLabel(
            self.header_status_box,
            text="● COM4 Conectada",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#3fb950",
            fg_color="#182c20",
            corner_radius=8,
            padx=12,
            pady=4,
        )
        self.serial_pill.pack(side="left")

        # ----------------- 2. ACTION TOOLBAR (ATALHOS) -----------------
        self.toolbar = ctk.CTkFrame(self, fg_color=COLOR_TOOLBAR, corner_radius=0, height=56)
        self.toolbar.pack(fill="x", side="top", pady=(1, 0))

        self.tb_left = ctk.CTkFrame(self.toolbar, fg_color="transparent")
        self.tb_left.pack(side="left", padx=20, pady=10)

        # Botão 1: Iniciar / Parar Bridge USB
        self.btn_toggle_bridge = ctk.CTkButton(
            self.tb_left,
            text="⏹️ Parar Bridge USB",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.toggle_bridge,
            width=165,
            height=34,
            corner_radius=8,
            fg_color="#da3633",
            hover_color="#f85149",
        )
        self.btn_toggle_bridge.pack(side="left", padx=(0, 10))

        # Botão 2: Gravar Firmware na CYD (tokenmeter-record)
        self.btn_flash = ctk.CTkButton(
            self.tb_left,
            text="⚡ Gravar Firmware (CYD)",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.flash_cyd_firmware,
            width=190,
            height=34,
            corner_radius=8,
            fg_color="#8957e5",
            hover_color="#a371f7",
        )
        self.btn_flash.pack(side="left", padx=(0, 10))

        # Botão 3: Atualizar Agora
        self.btn_refresh = ctk.CTkButton(
            self.tb_left,
            text="🔄 Atualizar Agora",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.manual_refresh,
            width=150,
            height=34,
            corner_radius=8,
            fg_color="#238636",
            hover_color="#2ea043",
        )
        self.btn_refresh.pack(side="left")

        # Mensagem de status dinâmico da Toolbar
        self.lbl_toolbar_msg = ctk.CTkLabel(
            self.toolbar,
            text="Sincronizado a cada 5s com a CYD.",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        self.lbl_toolbar_msg.pack(side="right", padx=20)

        # ----------------- 3. CONTAINER DOS CARDS -----------------
        self.cards_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.cards_frame.pack(fill="both", expand=True, padx=20, pady=16)
        self.cards_frame.columnconfigure((0, 1, 2), weight=1, uniform="equal_cards")
        self.cards_frame.rowconfigure(0, weight=1)

        # Card 1: Codex / GPT
        self.card_codex = ProviderCard(
            self.cards_frame,
            title="Codex / GPT",
            badge_name="Plus / Local",
            subtitle="OpenAI Session Logs",
            accent_color=COLOR_CODEX,
        )
        self.card_codex.grid(row=0, column=0, padx=8, pady=4, sticky="nsew")

        # Card 2: Claude
        self.card_claude = ProviderCard(
            self.cards_frame,
            title="Claude",
            badge_name="Anthropic",
            subtitle="Claude Code API",
            accent_color=COLOR_CLAUDE,
        )
        self.card_claude.grid(row=0, column=1, padx=8, pady=4, sticky="nsew")

        # Card 3: Gemini
        self.card_gemini = ProviderCard(
            self.cards_frame,
            title="Gemini",
            badge_name="Antigravity",
            subtitle="Gemini Flash & Pro",
            accent_color=COLOR_GEMINI,
        )
        self.card_gemini.grid(row=0, column=2, padx=8, pady=4, sticky="nsew")

        # ----------------- 4. FOOTER BAR -----------------
        self.footer_bar = ctk.CTkFrame(self, fg_color="transparent", height=38)
        self.footer_bar.pack(fill="x", side="bottom", padx=24, pady=(0, 10))

        self.lbl_footer_info = ctk.CTkLabel(
            self.footer_bar,
            text="Carregando leituras dos provedores...",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_MUTED,
        )
        self.lbl_footer_info.pack(side="left")

        self.lbl_shortcuts_help = ctk.CTkLabel(
            self.footer_bar,
            text="Atalhos: [tokendeck-gui] | [tokendeck-server] | [tokendeck-record]",
            font=ctk.CTkFont(size=11),
            text_color="#6e7681",
        )
        self.lbl_shortcuts_help.pack(side="right")

        # Estado interno
        self.running = True
        self.cached_claude: dict | None = None
        self.next_claude_poll = 0.0
        self.active_cyd_provider = "gemini"

        # Thread de sincronização contínua (5s)
        self.sync_thread = threading.Thread(target=self.background_loop, daemon=True)
        self.sync_thread.start()

    # ----------------- AÇÕES DOS BOTÕES -----------------

    def toggle_bridge(self):
        """Alterna entre Iniciar ou Parar a bridge USB."""
        if is_bridge_running():
            self.lbl_toolbar_msg.configure(text="Parando bridge USB para liberar a porta COM4...")
            self.update_idletasks()
            stop_bridge_process()
            time.sleep(0.8)
            self.update_bridge_button_state(running=False)
            self.lbl_toolbar_msg.configure(text="Bridge USB parada. Porta COM4 liberada.")
        else:
            self.lbl_toolbar_msg.configure(text="Iniciando Bridge USB...")
            self.update_idletasks()
            server_cmd = _REPO_ROOT / "tokenmeter-server.cmd"
            if server_cmd.exists():
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "TokenMeter USB Bridge", str(server_cmd)],
                    shell=True,
                    cwd=str(_REPO_ROOT),
                )
            time.sleep(1.0)
            self.update_bridge_button_state(running=is_bridge_running())
            self.lbl_toolbar_msg.configure(text="Bridge USB iniciada e enviando dados à CYD.")

    def flash_cyd_firmware(self):
        """Para a bridge se estiver rodando e grava o firmware na tela CYD."""
        record_cmd = _REPO_ROOT / "tokenmeter-record.cmd"
        if not record_cmd.exists():
            self.lbl_toolbar_msg.configure(text="Erro: tokenmeter-record.cmd não encontrado.")
            return

        # Se a bridge estiver rodando na COM4, para antes para não causar conflito de porta
        if is_bridge_running():
            self.lbl_toolbar_msg.configure(text="Liberando COM4 (parando bridge) antes de gravar...")
            self.update_idletasks()
            stop_bridge_process()
            time.sleep(1.0)
            self.update_bridge_button_state(running=False)

        self.lbl_toolbar_msg.configure(text="Gravando firmware na CYD (veja a janela do PlatformIO)...")
        # Abre o processo de gravação em janela separada para o usuário acompanhar o progresso
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "Gravar Firmware CYD", str(record_cmd)],
            shell=True,
            cwd=str(_REPO_ROOT),
        )

    def manual_refresh(self):
        """Dispara atualização manual imediata."""
        self.btn_refresh.configure(state="disabled", text="Atualizando...")
        self.lbl_toolbar_msg.configure(text="Atualizando métricas agora...")

        def run_update():
            self.fetch_all_data()
            time.sleep(0.4)
            self.after(0, lambda: self.btn_refresh.configure(state="normal", text="🔄 Atualizar Agora"))
            self.after(0, lambda: self.lbl_toolbar_msg.configure(text="Métricas atualizadas com sucesso!"))

        threading.Thread(target=run_update, daemon=True).start()

    def update_bridge_button_state(self, running: bool):
        """Atualiza a aparência do botão da bridge de acordo com seu estado real."""
        if running:
            self.btn_toggle_bridge.configure(
                text="⏹️ Parar Bridge USB",
                fg_color="#da3633",
                hover_color="#f85149",
            )
            self.bridge_pill.configure(
                text="● Bridge Ativa",
                text_color="#3fb950",
                fg_color="#182c20",
            )
        else:
            self.btn_toggle_bridge.configure(
                text="▶️ Iniciar Bridge USB",
                fg_color="#1f6feb",
                hover_color="#388bfd",
            )
            self.bridge_pill.configure(
                text="○ Bridge Parada",
                text_color=COLOR_TEXT_MUTED,
                fg_color="#21262d",
            )

    # ----------------- COLETA E ATUALIZAÇÃO DE DADOS -----------------

    def format_timestamp(self, ts: float) -> str:
        if ts <= 0:
            return "Nenhum registro"
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")

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

    def fetch_all_data(self):
        port = find_port()
        bridge_active = is_bridge_running()
        markers = activity_markers()
        last_active = max(markers, key=markers.get, default="") if markers else ""
        if last_active:
            self.active_cyd_provider = last_active

        cached = self.read_cached_status()
        if cached and bridge_active:
            payloads = cached.get("payloads", {})
            codex_data = payloads.get("codex", {})
            claude_data = payloads.get("claude", {})
            gemini_data = payloads.get("gemini", {})
            active_provider = cached.get("active_provider") or self.active_cyd_provider
            source_mode = "Sincronizado via Bridge USB (COM4)"
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

        self.after(
            0,
            lambda: self.update_ui(
                codex_data=codex_data,
                claude_data=claude_data,
                gemini_data=gemini_data,
                active_provider=active_provider,
                port=port,
                markers=markers,
                source_mode=source_mode,
                bridge_active=bridge_active,
            ),
        )

    def update_ui(
        self,
        codex_data: dict,
        claude_data: dict,
        gemini_data: dict,
        active_provider: str,
        port: str | None,
        markers: dict[str, float],
        source_mode: str,
        bridge_active: bool,
    ):
        now_str = datetime.now().strftime("%H:%M:%S")

        # Atualiza estado do botão e do pill da bridge
        self.update_bridge_button_state(bridge_active)

        # Status Serial
        if port:
            self.serial_pill.configure(
                text=f"● USB {port} Conectada",
                text_color="#3fb950",
                fg_color="#182c20",
            )
        else:
            self.serial_pill.configure(
                text="○ USB Desconectado",
                text_color=COLOR_TEXT_MUTED,
                fg_color="#21262d",
            )

        # Tela Ativa na CYD
        active_names = {"codex": "Codex / GPT", "claude": "Claude", "gemini": "Gemini"}
        active_colors = {
            "codex": COLOR_CODEX,
            "claude": COLOR_CLAUDE,
            "gemini": COLOR_GEMINI,
        }
        current_active_name = active_names.get(active_provider, active_provider.title() or "Gemini")
        current_active_color = active_colors.get(active_provider, COLOR_GEMINI)

        self.cyd_screen_pill.configure(
            text=f"Tela CYD: {current_active_name}",
            text_color=current_active_color,
        )

        # Card 1: Codex
        codex_ok = codex_data.get("ok", False)
        self.card_codex.update_card(
            pct_5h=codex_data.get("s", 0.0),
            reset_5h_min=codex_data.get("sr"),
            pct_week=codex_data.get("w", 0.0),
            reset_week_min=codex_data.get("wr"),
            status_text="Ativo" if codex_ok else "Sem dados de sessão",
            activity_str=self.format_timestamp(markers.get("codex", 0)),
            account_name=codex_data.get("acct", "plus").upper(),
            is_active_cyd=(active_provider == "codex"),
        )

        # Card 2: Claude
        claude_ok = claude_data.get("ok", False)
        self.card_claude.update_card(
            pct_5h=claude_data.get("s", 0.0),
            reset_5h_min=claude_data.get("sr"),
            pct_week=claude_data.get("w", 0.0),
            reset_week_min=claude_data.get("wr"),
            status_text="Conectado" if claude_ok else "Sem credenciais locais",
            activity_str=self.format_timestamp(markers.get("claude", 0)),
            account_name="PRO / OAUTH" if claude_ok else "OFFLINE",
            is_active_cyd=(active_provider == "claude"),
        )

        # Card 3: Gemini
        gemini_ok = gemini_data.get("ok", False)
        self.card_gemini.update_card(
            pct_5h=gemini_data.get("s", 0.0),
            reset_5h_min=gemini_data.get("sr"),
            pct_week=gemini_data.get("w", 0.0),
            reset_week_min=gemini_data.get("wr"),
            status_text="Liberado" if gemini_ok else "Aguardando CLI",
            activity_str=self.format_timestamp(markers.get("gemini", 0)),
            account_name="AGY MODELS",
            is_active_cyd=(active_provider == "gemini"),
        )

        self.lbl_footer_info.configure(
            text=f"{source_mode} | Última leitura: {now_str} (atualiza a cada 5s)"
        )

    def background_loop(self):
        while self.running:
            self.fetch_all_data()
            for _ in range(50):
                if not self.running:
                    break
                time.sleep(0.1)

    def destroy(self):
        self.running = False
        super().destroy()


def main():
    app = TokenMeterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
