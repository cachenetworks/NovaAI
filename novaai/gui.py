from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .audio_input import (
    describe_selected_microphone,
    describe_stt_backend,
    list_input_devices_compact,
    recalibrate_microphone,
    recognize_speech,
)
from .chat import request_reply
from .config import Config
from .models import SessionState
from .storage import (
    append_history,
    create_profile,
    delete_profile,
    ensure_runtime_dirs,
    get_active_profile_id,
    list_profiles,
    load_profile,
    load_profile_by_id,
    read_recent_history,
    reset_history,
    save_profile_by_id,
    set_active_profile,
)
from .tts import (
    describe_selected_speaker,
    describe_tts_voice,
    get_xtts_device,
    list_output_devices_compact,
    play_audio_file,
    should_play_audio_after_synthesis,
    speak_text,
)
from .web_search import (
    extract_web_query_from_request,
    fetch_web_context,
    should_auto_search,
)

PALETTE = {
    "bg": "#07131d",
    "card": "#0d1c2b",
    "card_alt": "#102338",
    "canvas": "#091522",
    "input": "#12263c",
    "border": "#1c3955",
    "border_soft": "#17324a",
    "text": "#f5fbff",
    "muted": "#9bb1c7",
    "muted_soft": "#7890a8",
    "accent": "#64d2ff",
    "accent_deep": "#183b52",
    "accent_text": "#06121b",
    "success": "#7be0b4",
    "success_deep": "#112d27",
    "warning": "#f4c574",
    "warning_deep": "#3c2b13",
    "danger": "#ff8e7a",
    "danger_deep": "#3d1d22",
    "user_bubble": "#2c2114",
    "user_border": "#8c6230",
    "assistant_bubble": "#10293b",
    "assistant_border": "#2e7aa1",
    "system_bubble": "#111f31",
    "system_border": "#29435f",
    "tile_disabled": "#0b1724",
}

TILE_TONES = {
    "accent": {
        "bg": "#0f2333",
        "border": "#275676",
        "stripe": PALETTE["accent"],
    },
    "success": {
        "bg": "#10241f",
        "border": "#2f6858",
        "stripe": PALETTE["success"],
    },
    "warning": {
        "bg": "#2a2215",
        "border": "#6e5830",
        "stripe": PALETTE["warning"],
    },
    "danger": {
        "bg": "#29171c",
        "border": "#76404b",
        "stripe": PALETTE["danger"],
    },
    "neutral": {
        "bg": PALETTE["card_alt"],
        "border": PALETTE["border_soft"],
        "stripe": "#8aa3bb",
    },
}

MESSAGE_STYLES = {
    "system": {
        "card_bg": PALETTE["system_bubble"],
        "card_border": PALETTE["system_border"],
        "title_fg": "#8fcfff",
        "body_fg": "#bfd1e3",
    },
    "user": {
        "card_bg": PALETTE["user_bubble"],
        "card_border": PALETTE["user_border"],
        "title_fg": "#f7c87d",
        "body_fg": "#fff1dd",
    },
    "assistant": {
        "card_bg": PALETTE["assistant_bubble"],
        "card_border": PALETTE["assistant_border"],
        "title_fg": "#83ddff",
        "body_fg": "#ebf8ff",
    },
}


class NovaAIGui:
    def __init__(self, auto_listen_on_launch: bool = True):
        ensure_runtime_dirs()
        self.config = Config.from_env()
        self.active_profile_id = get_active_profile_id()
        self.profile = load_profile()
        self.state = SessionState(
            voice_enabled=self.config.voice_enabled,
            input_mode=self.config.input_mode,
        )
        # GUI starts with voice replies off by default for safer first launches.
        self.state.voice_enabled = False
        self.config.voice_enabled = False

        self.root = tk.Tk()
        self.root.title(f"{self.profile['companion_name']} Studio")
        self.root.configure(bg=PALETTE["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._configure_window_bounds()

        self.hands_free_enabled = self.config.input_mode == "voice"
        self.mic_muted = False
        self.busy = False
        self.busy_reason = ""
        self.closing = False
        self.auto_listen_on_launch = auto_listen_on_launch
        self.session_started = False

        self.control_tiles: dict[str, dict[str, object]] = {}
        self.message_body_labels: list[tuple[tk.Label, str]] = []
        self.mic_choice_map: dict[str, int | None] = {}
        self.speaker_choice_map: dict[str, int | None] = {}
        self.tab_buttons: dict[str, tk.Button] = {}
        self.tab_frames: dict[str, tk.Frame] = {}
        self.current_tab = "main"
        self.profile_choice_map: dict[str, str] = {}
        self.profile_list_ids: list[str] = []
        self.profile_editor_loaded_id: str | None = None

        self.status_text = tk.StringVar(value="Press Start Session to begin.")
        self.status_badge_text = tk.StringVar(value="Standby")
        self.hero_subtitle_text = tk.StringVar()
        self.mic_select_text = tk.StringVar(value="System default microphone")
        self.speaker_select_text = tk.StringVar(value="System default speaker")
        self.profile_choice_text = tk.StringVar(value="")
        self.profile_name_text = tk.StringVar(value="")
        self.profile_description_text = tk.StringVar(value="")
        self.profile_companion_name_text = tk.StringVar(value="")
        self.profile_user_name_text = tk.StringVar(value="")
        self.profile_tags_text = tk.StringVar(value="")
        self.model_badge_text = tk.StringVar()
        self.mode_badge_text = tk.StringVar()
        self.voice_badge_text = tk.StringVar()
        self.mic_badge_text = tk.StringVar()

        self._build_ui()
        self.root.bind("<F8>", self._on_voice_hotkey)
        self._refresh_profiles_panel(select_profile_id=self.active_profile_id)
        self._refresh_audio_device_choices(silent=True)
        self._load_recent_history()
        self._refresh_summary_labels()
        self._refresh_controls()
        self._append_system_message(
            "NovaAI is online in standby. Press Start Session to begin."
        )
        self._append_system_message(
            "Voice replies start off by default. Turn Voice Replies on whenever you want spoken output."
        )
        self._append_system_message(
            "Mic mute is app-level. It blocks new captures here without touching the Windows microphone state."
        )
        self._append_system_message(
            "Use Voice Ask on the Chat tab (or press F8) to speak a question."
        )
        self._print_console_diagnostics()

        if (
            self.auto_listen_on_launch
            and self.session_started
            and self.hands_free_enabled
            and not self.mic_muted
        ):
            self.root.after(900, lambda: self.start_listen(auto=True))

    def _configure_window_bounds(self) -> None:
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        max_width = max(720, screen_width - 40)
        max_height = max(560, screen_height - 80)
        width = min(1360, max_width)
        height = min(860, max_height)
        x_pos = max(0, (screen_width - width) // 2)
        y_pos = max(0, (screen_height - height) // 2)

        self.root.geometry(f"{width}x{height}+{x_pos}+{y_pos}")
        self.root.minsize(min(width, 920), min(height, 620))

    def _print_console_diagnostics(self) -> None:
        companion_name = self.profile.get("companion_name", "NovaAI")
        user_name = self.profile.get("user_name", "You")
        print()
        print(f"[NovaAI GUI] Companion: {companion_name} | User: {user_name}")
        print(f"[NovaAI GUI] Active profile id: {self.active_profile_id}")
        print(
            f"[NovaAI GUI] Provider: {self.config.llm_provider} | Model: {self.config.model} | "
            f"Profile: {self.config.performance_profile} | "
            f"Hardware: {self.config.system_summary}"
        )
        print(
            f"[NovaAI GUI] STT: {describe_stt_backend(self.config)} | "
            f"TTS provider: {self.config.tts_provider} | "
            f"Voice: {describe_tts_voice(self.config)}"
        )
        if self.config.tts_provider == "xtts":
            print(f"[NovaAI GUI] XTTS device: {get_xtts_device(self.config)}")
        print(
            f"[NovaAI GUI] Mic: {describe_selected_microphone(self.config)} | "
            f"Speaker: {describe_selected_speaker(self.config)}"
        )
        print(
            f"[NovaAI GUI] Web: {'on' if self.config.web_browsing_enabled else 'off'} | "
            f"Auto: {'on' if self.config.web_auto_search else 'off'} | "
            f"Provider: {self.config.web_search_provider} | "
            f"Max results: {self.config.web_max_results}"
        )
        print()

    def _build_ui_legacy(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        shell = tk.Frame(self.root, bg=PALETTE["bg"], padx=24, pady=24)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.grid_columnconfigure(0, weight=5)
        shell.grid_columnconfigure(1, weight=2, minsize=340)
        shell.grid_rowconfigure(1, weight=1)

        hero_card = self._make_shell_card(shell, bg=PALETTE["card"])
        hero_card.grid(row=0, column=0, sticky="nsew", padx=(0, 18), pady=(0, 18))
        hero_card.grid_columnconfigure(0, weight=1)

        tk.Frame(hero_card, bg=PALETTE["accent"], height=3).grid(
            row=0, column=0, sticky="ew", pady=(0, 18)
        )

        tk.Label(
            hero_card,
            text="LOCAL VOICE CONTROL",
            bg=PALETTE["card"],
            fg=PALETTE["muted_soft"],
            font=("Bahnschrift SemiBold", 10),
        ).grid(row=1, column=0, sticky="w")

        tk.Label(
            hero_card,
            text=f"{self.profile['companion_name']} Studio",
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 28),
        ).grid(row=2, column=0, sticky="w", pady=(8, 6))

        tk.Label(
            hero_card,
            textvariable=self.hero_subtitle_text,
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 10),
            justify="left",
            anchor="w",
            wraplength=760,
        ).grid(row=3, column=0, sticky="w")

        badge_row = tk.Frame(hero_card, bg=PALETTE["card"])
        badge_row.grid(row=4, column=0, sticky="w", pady=(18, 4))

        self.model_badge_label = self._make_badge(
            badge_row,
            textvariable=self.model_badge_text,
        )
        self.model_badge_label.pack(side="left", padx=(0, 10))

        self.mode_badge_label = self._make_badge(
            badge_row,
            textvariable=self.mode_badge_text,
        )
        self.mode_badge_label.pack(side="left", padx=(0, 10))

        self.voice_badge_label = self._make_badge(
            badge_row,
            textvariable=self.voice_badge_text,
        )
        self.voice_badge_label.pack(side="left", padx=(0, 10))

        self.mic_badge_label = self._make_badge(
            badge_row,
            textvariable=self.mic_badge_text,
        )
        self.mic_badge_label.pack(side="left")

        pulse_card = self._make_shell_card(shell, bg=PALETTE["card_alt"])
        pulse_card.grid(row=0, column=1, sticky="nsew", pady=(0, 18))

        tk.Frame(pulse_card, bg=PALETTE["success"], height=3).pack(fill="x", pady=(0, 18))

        tk.Label(
            pulse_card,
            text="SESSION PULSE",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted_soft"],
            font=("Bahnschrift SemiBold", 10),
        ).pack(anchor="w")

        self.status_badge_label = self._make_badge(
            pulse_card,
            textvariable=self.status_badge_text,
        )
        self.status_badge_label.pack(anchor="w", pady=(12, 12))

        tk.Label(
            pulse_card,
            textvariable=self.status_text,
            bg=PALETTE["card_alt"],
            fg=PALETTE["text"],
            font=("Segoe UI Semibold", 11),
            justify="left",
            anchor="w",
            wraplength=280,
        ).pack(anchor="w", fill="x")

        conversation_card = self._make_shell_card(shell, bg=PALETTE["card"])
        conversation_card.grid(row=1, column=0, sticky="nsew", padx=(0, 18))
        conversation_card.grid_columnconfigure(0, weight=1)
        conversation_card.grid_rowconfigure(1, weight=1)

        transcript_header = tk.Frame(conversation_card, bg=PALETTE["card"])
        transcript_header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        transcript_header.grid_columnconfigure(0, weight=1)

        tk.Label(
            transcript_header,
            text="Conversation",
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 18),
        ).grid(row=0, column=0, sticky="w")

        tk.Label(
            transcript_header,
            text="A cleaner live transcript with room for voice turns, short banter, and longer replies when needed.",
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 10),
            justify="left",
            anchor="w",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        transcript_shell = tk.Frame(
            conversation_card,
            bg=PALETTE["canvas"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["border"],
        )
        transcript_shell.grid(row=1, column=0, sticky="nsew")
        transcript_shell.grid_columnconfigure(0, weight=1)
        transcript_shell.grid_rowconfigure(0, weight=1)

        self.transcript_canvas = tk.Canvas(
            transcript_shell,
            bg=PALETTE["canvas"],
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.transcript_canvas.grid(row=0, column=0, sticky="nsew")

        transcript_scroll = tk.Scrollbar(
            transcript_shell,
            orient="vertical",
            command=self.transcript_canvas.yview,
        )
        transcript_scroll.grid(row=0, column=1, sticky="ns")
        self.transcript_canvas.configure(yscrollcommand=transcript_scroll.set)

        self.message_column = tk.Frame(
            self.transcript_canvas,
            bg=PALETTE["canvas"],
            padx=18,
            pady=18,
        )
        self.message_window = self.transcript_canvas.create_window(
            (0, 0),
            window=self.message_column,
            anchor="nw",
        )

        self.message_column.bind(
            "<Configure>",
            lambda _event: self._update_transcript_scrollregion(),
        )
        self.transcript_canvas.bind("<Configure>", self._on_transcript_resize)
        self.transcript_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.message_column.bind("<MouseWheel>", self._on_mousewheel)

        composer = tk.Frame(
            conversation_card,
            bg=PALETTE["card_alt"],
            padx=18,
            pady=16,
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["border_soft"],
        )
        composer.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        composer.grid_columnconfigure(0, weight=1)

        tk.Label(
            composer,
            text="Send a message or drop in a slash command when you want quick control.",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.message_entry = tk.Entry(
            composer,
            bg=PALETTE["input"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["accent"],
            font=("Segoe UI", 12),
        )
        self.message_entry.grid(row=1, column=0, sticky="ew", ipady=12)
        self.message_entry.bind("<Return>", self._on_send_pressed)

        self.send_button = tk.Button(
            composer,
            text="Transmit",
            command=self.send_text_message,
            bg=PALETTE["accent"],
            fg=PALETTE["accent_text"],
            activebackground="#8be0ff",
            activeforeground=PALETTE["accent_text"],
            relief="flat",
            bd=0,
            padx=18,
            pady=12,
            font=("Bahnschrift SemiBold", 11),
            cursor="hand2",
        )
        self.send_button.grid(row=1, column=1, padx=(12, 0))

        side_shell = tk.Frame(
            shell,
            bg=PALETTE["bg"],
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["border_soft"],
        )
        side_shell.grid(row=1, column=1, sticky="nsew")
        side_shell.grid_columnconfigure(0, weight=1)
        side_shell.grid_rowconfigure(0, weight=1)

        self.sidebar_canvas = tk.Canvas(
            side_shell,
            bg=PALETTE["bg"],
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.sidebar_canvas.grid(row=0, column=0, sticky="nsew")

        sidebar_scroll = tk.Scrollbar(
            side_shell,
            orient="vertical",
            command=self.sidebar_canvas.yview,
        )
        sidebar_scroll.grid(row=0, column=1, sticky="ns")
        self.sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)

        self.sidebar_content = tk.Frame(
            self.sidebar_canvas,
            bg=PALETTE["bg"],
            padx=0,
            pady=0,
        )
        self.sidebar_content.grid_columnconfigure(0, weight=1)
        self.sidebar_window = self.sidebar_canvas.create_window(
            (0, 0),
            window=self.sidebar_content,
            anchor="nw",
        )
        self.sidebar_content.bind(
            "<Configure>",
            lambda _event: self._update_sidebar_scrollregion(),
        )
        self.sidebar_canvas.bind("<Configure>", self._on_sidebar_resize)
        self.sidebar_canvas.bind("<MouseWheel>", self._on_sidebar_mousewheel)
        self.sidebar_content.bind("<MouseWheel>", self._on_sidebar_mousewheel)

        controls_card = self._make_shell_card(self.sidebar_content, bg=PALETTE["card"])
        controls_card.grid(row=0, column=0, sticky="ew")

        tk.Label(
            controls_card,
            text="Quick Actions",
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 16),
        ).pack(anchor="w")

        tk.Label(
            controls_card,
            text="Only the core controls are shown here. Runtime diagnostics stay in the console.",
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 10),
            wraplength=280,
            justify="left",
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(6, 14))

        selector_style = ttk.Style(self.root)
        try:
            selector_style.theme_use("clam")
        except tk.TclError:
            pass
        selector_style.configure(
            "NovaAI.TCombobox",
            fieldbackground=PALETTE["input"],
            background=PALETTE["input"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border_soft"],
            lightcolor=PALETTE["border_soft"],
            darkcolor=PALETTE["border_soft"],
            arrowcolor=PALETTE["accent"],
            insertcolor=PALETTE["text"],
        )

        device_card = tk.Frame(
            controls_card,
            bg=PALETTE["card_alt"],
            padx=12,
            pady=12,
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["border_soft"],
        )
        device_card.pack(fill="x", pady=(0, 12))
        device_card.grid_columnconfigure(0, weight=1)

        tk.Label(
            device_card,
            text="Audio Devices",
            bg=PALETTE["card_alt"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 11),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.refresh_devices_button = tk.Button(
            device_card,
            text="Refresh",
            command=self.refresh_audio_devices,
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            activebackground=PALETTE["input"],
            activeforeground=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )
        self.refresh_devices_button.grid(row=0, column=1, sticky="e")

        tk.Label(
            device_card,
            text="Microphone",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 4))

        self.mic_selector = ttk.Combobox(
            device_card,
            textvariable=self.mic_select_text,
            state="readonly",
            style="NovaAI.TCombobox",
            font=("Segoe UI", 10),
        )
        self.mic_selector.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.mic_selector.bind("<<ComboboxSelected>>", self._on_mic_selected)

        tk.Label(
            device_card,
            text="Speaker",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 4))

        self.speaker_selector = ttk.Combobox(
            device_card,
            textvariable=self.speaker_select_text,
            state="readonly",
            style="NovaAI.TCombobox",
            font=("Segoe UI", 10),
        )
        self.speaker_selector.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.speaker_selector.bind("<<ComboboxSelected>>", self._on_speaker_selected)

        action_grid = tk.Frame(controls_card, bg=PALETTE["card"])
        action_grid.pack(fill="x")
        action_grid.grid_columnconfigure(0, weight=1)
        action_grid.grid_columnconfigure(1, weight=1)

        self._make_control_tile(
            action_grid,
            key="start",
            title="Start Session",
            subtitle="Enable chat and live controls.",
            command=self.start_session,
            tone="accent",
            row=0,
            column=0,
            columnspan=2,
        )
        self._make_control_tile(
            action_grid,
            key="listen",
            title="Listen Now",
            subtitle="Capture one spoken turn right away.",
            command=self.start_listen_once,
            tone="accent",
            row=1,
            column=0,
        )
        self._make_control_tile(
            action_grid,
            key="hands_free",
            title="Hands-free Off",
            subtitle="Manual listens only.",
            command=self.toggle_hands_free,
            tone="neutral",
            row=1,
            column=1,
        )
        self._make_control_tile(
            action_grid,
            key="mic",
            title="Mic Live",
            subtitle="NovaAI can start new captures.",
            command=self.toggle_mic_muted,
            tone="success",
            row=2,
            column=0,
        )
        self._make_control_tile(
            action_grid,
            key="voice",
            title="Voice Replies On",
            subtitle="Spoken output is active.",
            command=self.toggle_voice_output,
            tone="accent",
            row=2,
            column=1,
        )
        self._make_control_tile(
            action_grid,
            key="recalibrate",
            title="Recalibrate",
            subtitle="Relearn room noise.",
            command=self.start_recalibration,
            tone="warning",
            row=3,
            column=0,
        )
        self._make_control_tile(
            action_grid,
            key="clear_history",
            title="Clear History",
            subtitle="Wipe the saved transcript.",
            command=self.clear_history,
            tone="danger",
            row=3,
            column=1,
        )
        self._make_control_tile(
            action_grid,
            key="performance",
            title="Diagnostics",
            subtitle="Print runtime details to console.",
            command=self.show_performance,
            tone="neutral",
            row=4,
            column=0,
            columnspan=2,
        )

    def _build_chat_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        conversation_card = self._make_shell_card(parent, bg=PALETTE["card"])
        conversation_card.grid(row=0, column=0, sticky="nsew")
        conversation_card.grid_columnconfigure(0, weight=1)
        conversation_card.grid_rowconfigure(1, weight=1)

        transcript_header = tk.Frame(conversation_card, bg=PALETTE["card"])
        transcript_header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        transcript_header.grid_columnconfigure(0, weight=1)

        tk.Label(
            transcript_header,
            text="Conversation",
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 18),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            transcript_header,
            text="Live transcript for voice turns, quick banter, and longer explanations when needed.",
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 10),
            justify="left",
            anchor="w",
            wraplength=940,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        transcript_shell = tk.Frame(
            conversation_card,
            bg=PALETTE["canvas"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["border"],
        )
        transcript_shell.grid(row=1, column=0, sticky="nsew")
        transcript_shell.grid_columnconfigure(0, weight=1)
        transcript_shell.grid_rowconfigure(0, weight=1)

        self.transcript_canvas = tk.Canvas(
            transcript_shell,
            bg=PALETTE["canvas"],
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        self.transcript_canvas.grid(row=0, column=0, sticky="nsew")

        transcript_scroll = tk.Scrollbar(
            transcript_shell,
            orient="vertical",
            command=self.transcript_canvas.yview,
        )
        transcript_scroll.grid(row=0, column=1, sticky="ns")
        self.transcript_canvas.configure(yscrollcommand=transcript_scroll.set)

        self.message_column = tk.Frame(
            self.transcript_canvas,
            bg=PALETTE["canvas"],
            padx=18,
            pady=18,
        )
        self.message_window = self.transcript_canvas.create_window(
            (0, 0),
            window=self.message_column,
            anchor="nw",
        )

        self.message_column.bind(
            "<Configure>",
            lambda _event: self._update_transcript_scrollregion(),
        )
        self.transcript_canvas.bind("<Configure>", self._on_transcript_resize)
        self.transcript_canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.message_column.bind("<MouseWheel>", self._on_mousewheel)

        composer = tk.Frame(
            conversation_card,
            bg=PALETTE["card_alt"],
            padx=18,
            pady=16,
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["border_soft"],
        )
        composer.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        composer.grid_columnconfigure(0, weight=1)
        composer.grid_columnconfigure(1, weight=0)
        composer.grid_columnconfigure(2, weight=0)

        tk.Label(
            composer,
            text="Send text, use a slash command, or ask by voice.",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 10),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        self.message_entry = tk.Entry(
            composer,
            bg=PALETTE["input"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["accent"],
            font=("Segoe UI", 12),
        )
        self.message_entry.grid(row=1, column=0, sticky="ew", ipady=12)
        self.message_entry.bind("<Return>", self._on_send_pressed)

        self.voice_input_button = tk.Button(
            composer,
            text="Voice Ask",
            command=self.start_listen_once,
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            activebackground=PALETTE["input"],
            activeforeground=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=14,
            pady=12,
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        )
        self.voice_input_button.grid(row=1, column=1, padx=(12, 0))

        self.send_button = tk.Button(
            composer,
            text="Transmit",
            command=self.send_text_message,
            bg=PALETTE["accent"],
            fg=PALETTE["accent_text"],
            activebackground="#8be0ff",
            activeforeground=PALETTE["accent_text"],
            relief="flat",
            bd=0,
            padx=18,
            pady=12,
            font=("Bahnschrift SemiBold", 11),
            cursor="hand2",
        )
        self.send_button.grid(row=1, column=2, padx=(10, 0))

    def _build_profile_field(
        self,
        parent: tk.Widget,
        label: str,
        variable: tk.StringVar,
        row: int,
    ) -> None:
        tk.Label(
            parent,
            text=label,
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
        ).grid(row=row, column=0, sticky="w", pady=(0 if row == 0 else 8, 4), padx=(0, 10))
        entry = tk.Entry(
            parent,
            textvariable=variable,
            bg=PALETTE["input"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["accent"],
            font=("Segoe UI", 10),
        )
        entry.grid(row=row, column=1, sticky="ew", pady=(0 if row == 0 else 8, 4))

    def _build_profiles_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=3)
        parent.grid_rowconfigure(0, weight=1)

        list_card = self._make_shell_card(parent, bg=PALETTE["card"])
        list_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        list_card.grid_columnconfigure(0, weight=1)
        list_card.grid_rowconfigure(1, weight=1)

        tk.Label(
            list_card,
            text="Profiles",
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 16),
        ).grid(row=0, column=0, sticky="w")

        self.profiles_listbox = tk.Listbox(
            list_card,
            bg=PALETTE["canvas"],
            fg=PALETTE["text"],
            selectbackground=PALETTE["accent_deep"],
            selectforeground=PALETTE["accent"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["accent"],
            activestyle="none",
            font=("Segoe UI", 10),
        )
        self.profiles_listbox.grid(row=1, column=0, sticky="nsew", pady=(10, 8))
        self.profiles_listbox.bind("<<ListboxSelect>>", self._on_profile_selected)

        list_actions = tk.Frame(list_card, bg=PALETTE["card"])
        list_actions.grid(row=2, column=0, sticky="ew")
        list_actions.grid_columnconfigure(0, weight=1)
        list_actions.grid_columnconfigure(1, weight=1)

        tk.Button(
            list_actions,
            text="Create",
            command=self.create_profile_from_gui,
            bg=PALETTE["accent_deep"],
            fg=PALETTE["accent"],
            relief="flat",
            bd=0,
            padx=8,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        tk.Button(
            list_actions,
            text="Clone",
            command=self.clone_profile_from_gui,
            bg=PALETTE["card_alt"],
            fg=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=8,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        tk.Button(
            list_actions,
            text="Use Profile",
            command=self.activate_selected_profile,
            bg=PALETTE["success_deep"],
            fg=PALETTE["success"],
            relief="flat",
            bd=0,
            padx=8,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        ).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(8, 0))
        tk.Button(
            list_actions,
            text="Delete",
            command=self.delete_selected_profile,
            bg=PALETTE["danger_deep"],
            fg=PALETTE["danger"],
            relief="flat",
            bd=0,
            padx=8,
            pady=8,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        ).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(8, 0))

        editor_card = self._make_shell_card(parent, bg=PALETTE["card"])
        editor_card.grid(row=0, column=1, sticky="nsew")
        editor_card.grid_columnconfigure(0, weight=1)
        editor_card.grid_rowconfigure(6, weight=1)
        editor_card.grid_rowconfigure(8, weight=2)

        tk.Label(
            editor_card,
            text="Profile Editor",
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 16),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            editor_card,
            text="Edit basics quickly or use the advanced JSON editor for full customization.",
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
            justify="left",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        basic_form = tk.Frame(editor_card, bg=PALETTE["card"])
        basic_form.grid(row=2, column=0, sticky="ew")
        basic_form.grid_columnconfigure(1, weight=1)

        self._build_profile_field(basic_form, "Profile Name", self.profile_name_text, row=0)
        self._build_profile_field(
            basic_form,
            "Description",
            self.profile_description_text,
            row=1,
        )
        self._build_profile_field(
            basic_form,
            "Companion Name",
            self.profile_companion_name_text,
            row=2,
        )
        self._build_profile_field(
            basic_form,
            "User Name",
            self.profile_user_name_text,
            row=3,
        )
        self._build_profile_field(
            basic_form,
            "Tags (comma separated)",
            self.profile_tags_text,
            row=4,
        )

        tk.Label(
            editor_card,
            text="Companion Style",
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
        ).grid(row=3, column=0, sticky="w", pady=(12, 4))
        self.profile_style_textbox = tk.Text(
            editor_card,
            height=4,
            bg=PALETTE["input"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["accent"],
            font=("Segoe UI", 10),
            wrap="word",
        )
        self.profile_style_textbox.grid(row=4, column=0, sticky="ew")

        goals_memory_frame = tk.Frame(editor_card, bg=PALETTE["card"])
        goals_memory_frame.grid(row=5, column=0, sticky="nsew", pady=(12, 0))
        goals_memory_frame.grid_columnconfigure(0, weight=1)
        goals_memory_frame.grid_columnconfigure(1, weight=1)

        goals_card = tk.Frame(goals_memory_frame, bg=PALETTE["card_alt"], padx=10, pady=10)
        goals_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        goals_card.grid_columnconfigure(0, weight=1)
        tk.Label(
            goals_card,
            text="Shared Goals (one per line)",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="w")
        self.profile_goals_textbox = tk.Text(
            goals_card,
            height=7,
            bg=PALETTE["input"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["accent"],
            font=("Segoe UI", 10),
            wrap="word",
        )
        self.profile_goals_textbox.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

        memory_card = tk.Frame(goals_memory_frame, bg=PALETTE["card_alt"], padx=10, pady=10)
        memory_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        memory_card.grid_columnconfigure(0, weight=1)
        tk.Label(
            memory_card,
            text="Memory Notes (one per line)",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="w")
        self.profile_memory_textbox = tk.Text(
            memory_card,
            height=7,
            bg=PALETTE["input"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["accent"],
            font=("Segoe UI", 10),
            wrap="word",
        )
        self.profile_memory_textbox.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

        action_row = tk.Frame(editor_card, bg=PALETTE["card"])
        action_row.grid(row=7, column=0, sticky="ew", pady=(12, 8))
        action_row.grid_columnconfigure(0, weight=1)
        action_row.grid_columnconfigure(1, weight=1)
        action_row.grid_columnconfigure(2, weight=1)

        tk.Button(
            action_row,
            text="Save Basic Fields",
            command=self.save_profile_basic_from_gui,
            bg=PALETTE["accent_deep"],
            fg=PALETTE["accent"],
            relief="flat",
            bd=0,
            padx=8,
            pady=10,
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        tk.Button(
            action_row,
            text="Reload Selected",
            command=self.reload_selected_profile_editor,
            bg=PALETTE["card_alt"],
            fg=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=8,
            pady=10,
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        ).grid(row=0, column=1, sticky="ew", padx=4)
        tk.Button(
            action_row,
            text="Apply Advanced JSON",
            command=self.apply_profile_json_from_gui,
            bg=PALETTE["warning_deep"],
            fg=PALETTE["warning"],
            relief="flat",
            bd=0,
            padx=8,
            pady=10,
            font=("Segoe UI Semibold", 10),
            cursor="hand2",
        ).grid(row=0, column=2, sticky="ew", padx=(4, 0))

        tk.Label(
            editor_card,
            text="Advanced JSON (full profile object)",
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
        ).grid(row=8, column=0, sticky="w", pady=(2, 4))
        self.profile_json_textbox = tk.Text(
            editor_card,
            bg=PALETTE["input"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["accent"],
            font=("Consolas", 10),
            wrap="none",
        )
        self.profile_json_textbox.grid(row=9, column=0, sticky="nsew")

    def _build_settings_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        selector_style = ttk.Style(self.root)
        try:
            selector_style.theme_use("clam")
        except tk.TclError:
            pass
        selector_style.configure(
            "NovaAI.TCombobox",
            fieldbackground=PALETTE["input"],
            background=PALETTE["input"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border_soft"],
            lightcolor=PALETTE["border_soft"],
            darkcolor=PALETTE["border_soft"],
            arrowcolor=PALETTE["accent"],
            insertcolor=PALETTE["text"],
        )

        settings_card = self._make_shell_card(parent, bg=PALETTE["card"])
        settings_card.grid(row=0, column=0, sticky="nsew")
        settings_card.grid_columnconfigure(0, weight=1)

        tk.Label(
            settings_card,
            text="Settings",
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 18),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            settings_card,
            text="Audio routing, device selection, and runtime preferences.",
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 10),
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))

        device_card = tk.Frame(
            settings_card,
            bg=PALETTE["card_alt"],
            padx=14,
            pady=14,
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["border_soft"],
        )
        device_card.grid(row=2, column=0, sticky="ew")
        device_card.grid_columnconfigure(0, weight=1)

        tk.Label(
            device_card,
            text="Audio Devices",
            bg=PALETTE["card_alt"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 12),
        ).grid(row=0, column=0, sticky="w")
        self.refresh_devices_button = tk.Button(
            device_card,
            text="Refresh",
            command=self.refresh_audio_devices,
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            activebackground=PALETTE["input"],
            activeforeground=PALETTE["text"],
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            font=("Segoe UI Semibold", 9),
            cursor="hand2",
        )
        self.refresh_devices_button.grid(row=0, column=1, sticky="e")

        tk.Label(
            device_card,
            text="Microphone",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 4))
        self.mic_selector = ttk.Combobox(
            device_card,
            textvariable=self.mic_select_text,
            state="readonly",
            style="NovaAI.TCombobox",
            font=("Segoe UI", 10),
        )
        self.mic_selector.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.mic_selector.bind("<<ComboboxSelected>>", self._on_mic_selected)

        tk.Label(
            device_card,
            text="Speaker",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 4))
        self.speaker_selector = ttk.Combobox(
            device_card,
            textvariable=self.speaker_select_text,
            state="readonly",
            style="NovaAI.TCombobox",
            font=("Segoe UI", 10),
        )
        self.speaker_selector.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.speaker_selector.bind("<<ComboboxSelected>>", self._on_speaker_selected)

        notes_card = tk.Frame(
            settings_card,
            bg=PALETTE["card_alt"],
            padx=14,
            pady=14,
            highlightthickness=1,
            highlightbackground=PALETTE["border_soft"],
            highlightcolor=PALETTE["border_soft"],
        )
        notes_card.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        tk.Label(
            notes_card,
            text="Notes",
            bg=PALETTE["card_alt"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 11),
        ).pack(anchor="w")
        tk.Label(
            notes_card,
            text="Use Main tab for live control actions. Use Profiles tab for personality and deep JSON customization.",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
            justify="left",
            anchor="w",
            wraplength=860,
        ).pack(anchor="w", pady=(6, 0))

    def _make_shell_card(self, parent: tk.Widget, bg: str) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=bg,
            padx=20,
            pady=20,
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["border"],
        )

    def _make_badge(
        self,
        parent: tk.Widget,
        textvariable: tk.StringVar,
    ) -> tk.Label:
        return tk.Label(
            parent,
            textvariable=textvariable,
            bg=PALETTE["accent_deep"],
            fg=PALETTE["accent"],
            padx=12,
            pady=6,
            font=("Bahnschrift SemiBold", 10),
        )

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        shell = tk.Frame(self.root, bg=PALETTE["bg"], padx=18, pady=18)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        nav = tk.Frame(
            shell,
            bg=PALETTE["card"],
            padx=12,
            pady=12,
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["border"],
        )
        nav.grid(row=0, column=0, sticky="ns", padx=(0, 14))
        nav.grid_columnconfigure(0, weight=1)

        tk.Label(
            nav,
            text="NovaAI",
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 18),
        ).grid(row=0, column=0, sticky="w", pady=(4, 0))
        tk.Label(
            nav,
            text="Workspace",
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky="w", pady=(0, 14))

        self._create_tab_button(nav, "main", "Main", row=2)
        self._create_tab_button(nav, "chat", "Chat", row=3)
        self._create_tab_button(nav, "profiles", "Profiles", row=4)
        self._create_tab_button(nav, "settings", "Settings", row=5)

        content = tk.Frame(shell, bg=PALETTE["bg"])
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        for tab_key in ("main", "chat", "profiles", "settings"):
            frame = tk.Frame(content, bg=PALETTE["bg"])
            frame.grid(row=0, column=0, sticky="nsew")
            self.tab_frames[tab_key] = frame

        self._build_main_tab(self.tab_frames["main"])
        self._build_chat_tab(self.tab_frames["chat"])
        self._build_profiles_tab(self.tab_frames["profiles"])
        self._build_settings_tab(self.tab_frames["settings"])
        self._switch_tab("main")

    def _create_tab_button(self, parent: tk.Widget, key: str, label: str, row: int) -> None:
        button = tk.Button(
            parent,
            text=label,
            command=lambda: self._switch_tab(key),
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted"],
            activebackground=PALETTE["accent_deep"],
            activeforeground=PALETTE["accent"],
            relief="flat",
            bd=0,
            anchor="w",
            padx=12,
            pady=10,
            font=("Bahnschrift SemiBold", 11),
            cursor="hand2",
        )
        button.grid(row=row, column=0, sticky="ew", pady=3)
        self.tab_buttons[key] = button

    def _switch_tab(self, tab_key: str) -> None:
        if tab_key not in self.tab_frames:
            return

        self.current_tab = tab_key
        for key, frame in self.tab_frames.items():
            if key == tab_key:
                frame.tkraise()
            else:
                frame.lower()

        for key, button in self.tab_buttons.items():
            selected = key == tab_key
            button.configure(
                bg=PALETTE["accent_deep"] if selected else PALETTE["card_alt"],
                fg=PALETTE["accent"] if selected else PALETTE["muted"],
            )

    def _build_main_tab(self, parent: tk.Widget) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        hero_card = self._make_shell_card(parent, bg=PALETTE["card"])
        hero_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 12))
        hero_card.grid_columnconfigure(0, weight=1)

        tk.Frame(hero_card, bg=PALETTE["accent"], height=3).grid(
            row=0,
            column=0,
            sticky="ew",
            pady=(0, 14),
        )
        tk.Label(
            hero_card,
            text="MAIN CONTROL",
            bg=PALETTE["card"],
            fg=PALETTE["muted_soft"],
            font=("Bahnschrift SemiBold", 10),
        ).grid(row=1, column=0, sticky="w")
        tk.Label(
            hero_card,
            text=f"{self.profile['companion_name']} Studio",
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 27),
        ).grid(row=2, column=0, sticky="w", pady=(8, 5))
        tk.Label(
            hero_card,
            textvariable=self.hero_subtitle_text,
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 10),
            justify="left",
            anchor="w",
            wraplength=620,
        ).grid(row=3, column=0, sticky="w")

        badge_row = tk.Frame(hero_card, bg=PALETTE["card"])
        badge_row.grid(row=4, column=0, sticky="w", pady=(14, 2))
        self.model_badge_label = self._make_badge(badge_row, textvariable=self.model_badge_text)
        self.model_badge_label.pack(side="left", padx=(0, 8))
        self.mode_badge_label = self._make_badge(badge_row, textvariable=self.mode_badge_text)
        self.mode_badge_label.pack(side="left", padx=(0, 8))
        self.voice_badge_label = self._make_badge(badge_row, textvariable=self.voice_badge_text)
        self.voice_badge_label.pack(side="left", padx=(0, 8))
        self.mic_badge_label = self._make_badge(badge_row, textvariable=self.mic_badge_text)
        self.mic_badge_label.pack(side="left")

        pulse_card = self._make_shell_card(parent, bg=PALETTE["card_alt"])
        pulse_card.grid(row=0, column=1, sticky="nsew", pady=(0, 12))
        tk.Frame(pulse_card, bg=PALETTE["success"], height=3).pack(fill="x", pady=(0, 14))
        tk.Label(
            pulse_card,
            text="SESSION PULSE",
            bg=PALETTE["card_alt"],
            fg=PALETTE["muted_soft"],
            font=("Bahnschrift SemiBold", 10),
        ).pack(anchor="w")
        self.status_badge_label = self._make_badge(pulse_card, textvariable=self.status_badge_text)
        self.status_badge_label.pack(anchor="w", pady=(10, 10))
        tk.Label(
            pulse_card,
            textvariable=self.status_text,
            bg=PALETTE["card_alt"],
            fg=PALETTE["text"],
            font=("Segoe UI Semibold", 11),
            justify="left",
            anchor="w",
            wraplength=260,
        ).pack(anchor="w", fill="x")

        controls_card = self._make_shell_card(parent, bg=PALETTE["card"])
        controls_card.grid(row=1, column=0, columnspan=2, sticky="nsew")
        controls_card.grid_columnconfigure(0, weight=1)

        tk.Label(
            controls_card,
            text="Quick Actions",
            bg=PALETTE["card"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 16),
        ).pack(anchor="w")
        tk.Label(
            controls_card,
            text="Start the session, control voice behavior, and keep the flow moving.",
            bg=PALETTE["card"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 10),
            wraplength=840,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        action_grid = tk.Frame(controls_card, bg=PALETTE["card"])
        action_grid.pack(fill="x")
        action_grid.grid_columnconfigure(0, weight=1)
        action_grid.grid_columnconfigure(1, weight=1)

        self._make_control_tile(
            action_grid,
            key="start",
            title="Start Session",
            subtitle="Enable chat and live controls.",
            command=self.start_session,
            tone="accent",
            row=0,
            column=0,
            columnspan=2,
        )
        self._make_control_tile(
            action_grid,
            key="listen",
            title="Listen Now",
            subtitle="Capture one spoken turn right away.",
            command=self.start_listen_once,
            tone="accent",
            row=1,
            column=0,
        )
        self._make_control_tile(
            action_grid,
            key="hands_free",
            title="Hands-free Off",
            subtitle="Manual listens only.",
            command=self.toggle_hands_free,
            tone="neutral",
            row=1,
            column=1,
        )
        self._make_control_tile(
            action_grid,
            key="mic",
            title="Mic Live",
            subtitle="NovaAI can start new captures.",
            command=self.toggle_mic_muted,
            tone="success",
            row=2,
            column=0,
        )
        self._make_control_tile(
            action_grid,
            key="voice",
            title="Voice Replies On",
            subtitle="Spoken output is active.",
            command=self.toggle_voice_output,
            tone="accent",
            row=2,
            column=1,
        )
        self._make_control_tile(
            action_grid,
            key="recalibrate",
            title="Recalibrate",
            subtitle="Relearn room noise.",
            command=self.start_recalibration,
            tone="warning",
            row=3,
            column=0,
        )
        self._make_control_tile(
            action_grid,
            key="clear_history",
            title="Clear History",
            subtitle="Wipe the saved transcript.",
            command=self.clear_history,
            tone="danger",
            row=3,
            column=1,
        )
        self._make_control_tile(
            action_grid,
            key="performance",
            title="Diagnostics",
            subtitle="Print runtime details to console.",
            command=self.show_performance,
            tone="neutral",
            row=4,
            column=0,
            columnspan=2,
        )

    def _selected_profile_id(self) -> str | None:
        selected_indices = self.profiles_listbox.curselection()
        if not selected_indices:
            return None
        index = selected_indices[0]
        if index < 0 or index >= len(self.profile_list_ids):
            return None
        return self.profile_list_ids[index]

    def _set_textbox_value(self, textbox: tk.Text, value: str) -> None:
        textbox.delete("1.0", "end")
        textbox.insert("1.0", value)

    def _textbox_lines(self, textbox: tk.Text) -> list[str]:
        raw = textbox.get("1.0", "end").strip()
        if not raw:
            return []
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _on_profile_selected(self, _event: object) -> None:
        selected_profile_id = self._selected_profile_id()
        if not selected_profile_id:
            return
        try:
            selected_profile = load_profile_by_id(selected_profile_id)
        except RuntimeError as exc:
            self._set_status_text(str(exc))
            return
        self._load_profile_into_editor(selected_profile_id, selected_profile)

    def _refresh_profiles_panel(self, select_profile_id: str | None = None) -> None:
        profile_summaries = list_profiles()
        self.profile_list_ids = [summary["profile_id"] for summary in profile_summaries]
        self.profiles_listbox.delete(0, "end")

        for summary in profile_summaries:
            active_tag = " (active)" if summary["is_active"] else ""
            label = f"{summary['profile_name']} [{summary['companion_name']}]{active_tag}"
            self.profiles_listbox.insert("end", label)

        target_id = select_profile_id or self.active_profile_id
        if target_id in self.profile_list_ids:
            target_index = self.profile_list_ids.index(target_id)
            self.profiles_listbox.selection_clear(0, "end")
            self.profiles_listbox.selection_set(target_index)
            self.profiles_listbox.activate(target_index)
            self.profiles_listbox.see(target_index)
            selected_profile = load_profile_by_id(target_id)
            self._load_profile_into_editor(target_id, selected_profile)
        elif self.profile_list_ids:
            self.profiles_listbox.selection_clear(0, "end")
            self.profiles_listbox.selection_set(0)
            selected_profile_id = self.profile_list_ids[0]
            selected_profile = load_profile_by_id(selected_profile_id)
            self._load_profile_into_editor(selected_profile_id, selected_profile)

    def _load_profile_into_editor(
        self,
        profile_id: str,
        profile: dict[str, object],
    ) -> None:
        self.profile_editor_loaded_id = profile_id
        self.profile_name_text.set(str(profile.get("profile_name", "")))
        self.profile_description_text.set(str(profile.get("description", "")))
        self.profile_companion_name_text.set(str(profile.get("companion_name", "")))
        self.profile_user_name_text.set(str(profile.get("user_name", "")))
        tags = profile.get("tags")
        tag_text = ", ".join(str(tag).strip() for tag in (tags or []) if str(tag).strip())
        self.profile_tags_text.set(tag_text)
        self._set_textbox_value(
            self.profile_style_textbox,
            str(profile.get("companion_style", "")).strip(),
        )
        shared_goals = profile.get("shared_goals") if isinstance(profile.get("shared_goals"), list) else []
        self._set_textbox_value(
            self.profile_goals_textbox,
            "\n".join(str(goal).strip() for goal in shared_goals if str(goal).strip()),
        )
        memory_notes = profile.get("memory_notes") if isinstance(profile.get("memory_notes"), list) else []
        self._set_textbox_value(
            self.profile_memory_textbox,
            "\n".join(str(note).strip() for note in memory_notes if str(note).strip()),
        )
        self._set_textbox_value(
            self.profile_json_textbox,
            json.dumps(profile, indent=2, ensure_ascii=False),
        )

    def _build_basic_profile_update(self, base_profile: dict[str, object]) -> dict[str, object]:
        updated_profile = dict(base_profile)
        updated_profile["profile_name"] = self.profile_name_text.get().strip() or str(
            base_profile.get("profile_name", "Untitled Profile")
        )
        updated_profile["description"] = self.profile_description_text.get().strip()
        updated_profile["companion_name"] = self.profile_companion_name_text.get().strip() or str(
            base_profile.get("companion_name", "NovaAI")
        )
        updated_profile["user_name"] = self.profile_user_name_text.get().strip() or str(
            base_profile.get("user_name", "Friend")
        )
        updated_profile["companion_style"] = self.profile_style_textbox.get("1.0", "end").strip()
        updated_profile["shared_goals"] = self._textbox_lines(self.profile_goals_textbox)
        updated_profile["memory_notes"] = self._textbox_lines(self.profile_memory_textbox)
        updated_profile["tags"] = [
            piece.strip()
            for piece in self.profile_tags_text.get().split(",")
            if piece.strip()
        ]
        return updated_profile

    def _sync_active_profile_from_storage(self) -> None:
        self.active_profile_id = get_active_profile_id()
        self.profile = load_profile()
        self._refresh_summary_labels()
        self._refresh_controls()

    def create_profile_from_gui(self) -> None:
        entered_name = simpledialog.askstring(
            "Create profile",
            "Profile name:",
            parent=self.root,
        )
        if entered_name is None:
            return
        profile_name = entered_name.strip()
        if not profile_name:
            self._set_status_text("Profile creation cancelled: name is required.")
            return
        new_profile = create_profile(profile_name)
        new_profile_id = str(new_profile.get("profile_id", ""))
        self._refresh_profiles_panel(select_profile_id=new_profile_id)
        self._set_status_text(f"Created profile '{profile_name}'.")

    def clone_profile_from_gui(self) -> None:
        source_profile_id = self._selected_profile_id()
        if not source_profile_id:
            self._set_status_text("Select a profile to clone first.")
            return

        clone_name = simpledialog.askstring(
            "Clone profile",
            "Name for the cloned profile:",
            parent=self.root,
        )
        if clone_name is None:
            return
        clone_name = clone_name.strip()
        if not clone_name:
            self._set_status_text("Clone cancelled: name is required.")
            return

        source_profile = load_profile_by_id(source_profile_id)
        cloned_profile = create_profile(clone_name, base_profile=source_profile)
        cloned_profile_id = str(cloned_profile.get("profile_id", ""))
        self._refresh_profiles_panel(select_profile_id=cloned_profile_id)
        self._set_status_text(f"Cloned profile as '{clone_name}'.")

    def activate_selected_profile(self) -> None:
        selected_profile_id = self._selected_profile_id()
        if not selected_profile_id:
            self._set_status_text("Select a profile to activate.")
            return

        active_profile = set_active_profile(selected_profile_id)
        self.active_profile_id = selected_profile_id
        self.profile = active_profile
        self._refresh_profiles_panel(select_profile_id=selected_profile_id)
        self._refresh_summary_labels()
        self._refresh_controls()
        self._append_system_message(
            f"Active profile switched to {self.profile.get('profile_name', 'profile')}."
        )
        self._set_status_text("Profile activated.")

    def delete_selected_profile(self) -> None:
        selected_profile_id = self._selected_profile_id()
        if not selected_profile_id:
            self._set_status_text("Select a profile to delete.")
            return

        confirm_text = (
            "Delete this profile? If it is active, NovaAI will switch to another profile."
        )
        confirmed = messagebox.askyesno(
            "Delete profile",
            confirm_text,
            parent=self.root,
        )
        if not confirmed:
            return

        new_active_id = delete_profile(selected_profile_id)
        self._sync_active_profile_from_storage()
        self._refresh_profiles_panel(select_profile_id=new_active_id)
        self._set_status_text("Profile deleted.")

    def save_profile_basic_from_gui(self) -> None:
        selected_profile_id = self._selected_profile_id()
        if not selected_profile_id:
            self._set_status_text("Select a profile to save first.")
            return

        existing_profile = load_profile_by_id(selected_profile_id)
        updated_profile = self._build_basic_profile_update(existing_profile)
        saved_profile = save_profile_by_id(selected_profile_id, updated_profile)

        if selected_profile_id == self.active_profile_id:
            self.profile = saved_profile
            self._refresh_summary_labels()
            self._refresh_controls()

        self._refresh_profiles_panel(select_profile_id=selected_profile_id)
        self._set_status_text("Basic profile fields saved.")

    def reload_selected_profile_editor(self) -> None:
        selected_profile_id = self._selected_profile_id()
        if not selected_profile_id:
            self._set_status_text("Select a profile to reload.")
            return
        selected_profile = load_profile_by_id(selected_profile_id)
        self._load_profile_into_editor(selected_profile_id, selected_profile)
        self._set_status_text("Profile editor reloaded.")

    def apply_profile_json_from_gui(self) -> None:
        selected_profile_id = self._selected_profile_id()
        if not selected_profile_id:
            self._set_status_text("Select a profile before applying JSON.")
            return

        raw_json = self.profile_json_textbox.get("1.0", "end").strip()
        if not raw_json:
            self._set_status_text("Advanced JSON cannot be empty.")
            return

        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            self._set_status_text(f"Invalid JSON: {exc}")
            return

        if not isinstance(parsed, dict):
            self._set_status_text("Profile JSON must be an object.")
            return

        parsed["profile_id"] = selected_profile_id
        saved_profile = save_profile_by_id(selected_profile_id, parsed)
        if selected_profile_id == self.active_profile_id:
            self.profile = saved_profile
            self._refresh_summary_labels()
            self._refresh_controls()
        self._refresh_profiles_panel(select_profile_id=selected_profile_id)
        self._set_status_text("Advanced JSON applied.")

    def refresh_audio_devices(self) -> None:
        self._refresh_audio_device_choices(silent=False)

    def _refresh_audio_device_choices(self, silent: bool) -> None:
        max_choices = 18

        previous_mic_index = self.config.mic_device_index
        previous_speaker_index = self.config.speaker_device_index

        try:
            microphones = list_input_devices_compact(max_devices=max_choices)
            speakers = list_output_devices_compact(max_devices=max_choices)
        except RuntimeError as exc:
            if not silent:
                self._set_status_text(f"Could not refresh devices: {exc}")
            return

        mic_map: dict[str, int | None] = {"System default microphone": None}
        for device in microphones:
            label = device["name"]
            hostapi = str(device.get("hostapi", "")).strip()
            if hostapi:
                label = f"{label} [{hostapi}]"
            if device["is_default"]:
                label += " (default)"
            if label in mic_map:
                label = f"{label}  #{device['index']}"
            mic_map[label] = device["index"]

        speaker_map: dict[str, int | None] = {"System default speaker": None}
        for device in speakers:
            label = device["name"]
            hostapi = str(device.get("hostapi", "")).strip()
            if hostapi:
                label = f"{label} [{hostapi}]"
            if device["is_default"]:
                label += " (default)"
            if label in speaker_map:
                label = f"{label}  #{device['index']}"
            speaker_map[label] = device["index"]

        self.mic_choice_map = mic_map
        self.speaker_choice_map = speaker_map
        self.mic_selector.configure(values=list(mic_map.keys()))
        self.speaker_selector.configure(values=list(speaker_map.keys()))

        mic_label = next(
            (label for label, index in mic_map.items() if index == previous_mic_index),
            None,
        )
        if mic_label is None:
            if previous_mic_index is None:
                mic_label = "System default microphone"
            else:
                mic_label = f"Custom microphone #{previous_mic_index}"
                self.mic_choice_map[mic_label] = previous_mic_index
                self.mic_selector.configure(values=list(self.mic_choice_map.keys()))
        self.mic_select_text.set(mic_label)

        speaker_label = next(
            (
                label
                for label, index in speaker_map.items()
                if index == previous_speaker_index
            ),
            None,
        )
        if speaker_label is None:
            if previous_speaker_index is None:
                speaker_label = "System default speaker"
            else:
                speaker_label = f"Custom speaker #{previous_speaker_index}"
                self.speaker_choice_map[speaker_label] = previous_speaker_index
                self.speaker_selector.configure(
                    values=list(self.speaker_choice_map.keys())
                )
        self.speaker_select_text.set(speaker_label)

        if not silent:
            self._set_status_text(
                f"Audio devices refreshed ({len(microphones)} mics, {len(speakers)} speakers)."
            )

    def _on_mic_selected(self, _event: object) -> None:
        selected = self.mic_select_text.get()
        if selected not in self.mic_choice_map:
            return

        new_index = self.mic_choice_map[selected]
        if self.config.mic_device_index == new_index:
            return

        self.config.mic_device_index = new_index
        self.state.speech_recognizer = None
        self.state.speech_recognizer_signature = None
        self.state.mic_calibrated = False
        self._set_status_text(f"Microphone set to {selected}.")

    def _on_speaker_selected(self, _event: object) -> None:
        selected = self.speaker_select_text.get()
        if selected not in self.speaker_choice_map:
            return

        new_index = self.speaker_choice_map[selected]
        if self.config.speaker_device_index == new_index:
            return

        self.config.speaker_device_index = new_index
        self._set_status_text(f"Speaker set to {selected}.")

    def _make_control_tile(
        self,
        parent: tk.Widget,
        key: str,
        title: str,
        subtitle: str,
        command: object,
        tone: str,
        row: int,
        column: int,
        columnspan: int = 1,
    ) -> None:
        tone_colors = TILE_TONES[tone]
        tile = tk.Frame(
            parent,
            bg=tone_colors["bg"],
            padx=14,
            pady=14,
            highlightthickness=1,
            highlightbackground=tone_colors["border"],
            highlightcolor=tone_colors["border"],
            cursor="hand2",
        )
        tile.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="nsew",
            padx=4,
            pady=4,
        )

        stripe = tk.Frame(tile, bg=tone_colors["stripe"], height=3)
        stripe.pack(fill="x", pady=(0, 12))

        title_var = tk.StringVar(value=title)
        subtitle_var = tk.StringVar(value=subtitle)

        title_label = tk.Label(
            tile,
            textvariable=title_var,
            bg=tone_colors["bg"],
            fg=PALETTE["text"],
            font=("Bahnschrift SemiBold", 11),
            anchor="w",
            justify="left",
        )
        title_label.pack(anchor="w", fill="x")

        subtitle_label = tk.Label(
            tile,
            textvariable=subtitle_var,
            bg=tone_colors["bg"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=220,
        )
        subtitle_label.pack(anchor="w", fill="x", pady=(6, 0))

        widgets = (tile, stripe, title_label, subtitle_label)
        for widget in widgets:
            widget.bind(
                "<Button-1>",
                lambda _event, current=key: self._handle_tile_click(current),
            )
            widget.bind("<MouseWheel>", self._on_mousewheel)

        self.control_tiles[key] = {
            "frame": tile,
            "stripe": stripe,
            "title_label": title_label,
            "subtitle_label": subtitle_label,
            "title_var": title_var,
            "subtitle_var": subtitle_var,
            "command": command,
            "tone": tone,
            "enabled": True,
        }

    def _handle_tile_click(self, key: str) -> None:
        tile = self.control_tiles.get(key)
        if tile is None or not tile.get("enabled", False):
            return
        command = tile["command"]
        if callable(command):
            command()

    def _configure_tile(
        self,
        key: str,
        *,
        title: str | None = None,
        subtitle: str | None = None,
        tone: str | None = None,
        enabled: bool = True,
    ) -> None:
        tile = self.control_tiles[key]
        tile_tone = tone or str(tile["tone"])
        tile["tone"] = tile_tone
        colors = TILE_TONES[tile_tone]

        frame_bg = colors["bg"] if enabled else PALETTE["tile_disabled"]
        border_color = colors["border"] if enabled else PALETTE["border_soft"]
        stripe_color = colors["stripe"] if enabled else PALETTE["border_soft"]
        title_fg = PALETTE["text"] if enabled else PALETTE["muted_soft"]
        subtitle_fg = PALETTE["muted"] if enabled else PALETTE["muted_soft"]
        cursor = "hand2" if enabled else "arrow"

        if title is not None:
            tile["title_var"].set(title)
        if subtitle is not None:
            tile["subtitle_var"].set(subtitle)

        tile["enabled"] = enabled
        tile["frame"].configure(
            bg=frame_bg,
            highlightbackground=border_color,
            highlightcolor=border_color,
            cursor=cursor,
        )
        tile["stripe"].configure(bg=stripe_color, cursor=cursor)
        tile["title_label"].configure(bg=frame_bg, fg=title_fg, cursor=cursor)
        tile["subtitle_label"].configure(bg=frame_bg, fg=subtitle_fg, cursor=cursor)

    def _load_recent_history(self) -> None:
        for message in read_recent_history(self.config.history_turns):
            role = message.get("role")
            content = message.get("content", "")
            if role == "user":
                self._append_message(self.profile["user_name"], content, "user")
            elif role == "assistant":
                self._append_message(self.profile["companion_name"], content, "assistant")

    def _append_message(self, author: str, text: str, role: str) -> None:
        style = MESSAGE_STYLES[role]
        row = tk.Frame(self.message_column, bg=PALETTE["canvas"])
        row.pack(fill="x", pady=8)
        row.bind("<MouseWheel>", self._on_mousewheel)

        card = tk.Frame(
            row,
            bg=style["card_bg"],
            padx=18,
            pady=16,
            highlightthickness=1,
            highlightbackground=style["card_border"],
            highlightcolor=style["card_border"],
        )

        if role == "assistant":
            card.pack(anchor="w", padx=(0, 132))
        elif role == "user":
            card.pack(anchor="e", padx=(132, 0))
        else:
            card.pack(fill="x", padx=52)

        author_label = tk.Label(
            card,
            text=author.upper(),
            bg=style["card_bg"],
            fg=style["title_fg"],
            font=("Bahnschrift SemiBold", 9),
            anchor="w",
            justify="left",
        )
        author_label.pack(anchor="w")

        body_label = tk.Label(
            card,
            text=text,
            bg=style["card_bg"],
            fg=style["body_fg"],
            font=("Segoe UI", 11 if role != "system" else 10),
            justify="left",
            anchor="w",
            wraplength=560,
        )
        body_label.pack(anchor="w", fill="x", pady=(10, 0))
        self.message_body_labels.append((body_label, role))

        for widget in (card, author_label, body_label):
            widget.bind("<MouseWheel>", self._on_mousewheel)

        self._sync_message_wraplength()
        self._scroll_transcript_to_end()

    def _append_system_message(self, text: str) -> None:
        self._append_message("System", text, "system")

    def _refresh_summary_labels(self) -> None:
        companion_name = self.profile.get("companion_name", "NovaAI")
        profile_name = self.profile.get("profile_name", "Active Profile")
        self.hero_subtitle_text.set(
            f"Active profile: {profile_name}. Provider: {self.config.llm_provider}. Use the Profiles tab for deep JSON customization."
        )

        self.model_badge_text.set(
            f"{self.config.llm_provider.title()} | {self.config.model}"
        )
        self.mode_badge_text.set(
            (
                "Hands-free active"
                if self.session_started and self.hands_free_enabled
                else "Waiting to start"
                if not self.session_started
                else "Manual mode"
            )
        )
        self.voice_badge_text.set(
            "Voice replies on" if self.state.voice_enabled else "Voice replies off"
        )
        self.mic_badge_text.set("Mic muted" if self.mic_muted else "Mic live")

        self._apply_badge_style(self.model_badge_label, "accent")
        self._apply_badge_style(
            self.mode_badge_label,
            "warning"
            if not self.session_started
            else "success"
            if self.hands_free_enabled
            else "neutral",
        )
        self._apply_badge_style(
            self.voice_badge_label,
            "accent" if self.state.voice_enabled else "neutral",
        )
        self._apply_badge_style(
            self.mic_badge_label,
            "danger" if self.mic_muted else "success",
        )
        self._update_status_badge()
        self.root.title(f"{companion_name} Studio")

    def _apply_badge_style(self, label: tk.Label, tone: str) -> None:
        tone_colors = {
            "accent": (PALETTE["accent_deep"], PALETTE["accent"]),
            "success": (PALETTE["success_deep"], PALETTE["success"]),
            "warning": (PALETTE["warning_deep"], PALETTE["warning"]),
            "danger": (PALETTE["danger_deep"], PALETTE["danger"]),
            "neutral": (PALETTE["card_alt"], "#c0d1e0"),
        }[tone]
        label.configure(bg=tone_colors[0], fg=tone_colors[1])

    def _update_status_badge(self) -> None:
        status_copy = self.status_text.get().lower()
        if self.busy and "speak" in status_copy:
            text = "Speaking"
            tone = "accent"
        elif self.busy_reason == "listening":
            text = "Listening"
            tone = "accent"
        elif self.busy_reason == "replying":
            text = "Thinking"
            tone = "warning"
        elif self.busy_reason == "recalibrating":
            text = "Calibrating"
            tone = "warning"
        elif not self.session_started:
            text = "Standby"
            tone = "warning"
        elif self.mic_muted:
            text = "Mic muted"
            tone = "danger"
        elif self.hands_free_enabled:
            text = "Hands-free"
            tone = "success"
        else:
            text = "Ready"
            tone = "neutral"

        self.status_badge_text.set(text)
        self._apply_badge_style(self.status_badge_label, tone)

    def _refresh_controls(self) -> None:
        busy = self.busy
        session_active = self.session_started
        interaction_enabled = session_active and not busy
        send_state = "normal" if interaction_enabled else "disabled"
        voice_input_enabled = session_active and not (busy or self.mic_muted)
        selector_state = "disabled" if busy else "readonly"

        self.send_button.configure(
            state=send_state,
            bg=PALETTE["accent"] if interaction_enabled else PALETTE["card_alt"],
            fg=PALETTE["accent_text"] if interaction_enabled else PALETTE["muted_soft"],
            activebackground="#8be0ff" if interaction_enabled else PALETTE["card_alt"],
            cursor="hand2" if interaction_enabled else "arrow",
        )
        self.voice_input_button.configure(
            state="normal" if voice_input_enabled else "disabled",
            bg=PALETTE["accent_deep"] if voice_input_enabled else PALETTE["card_alt"],
            fg=PALETTE["accent"] if voice_input_enabled else PALETTE["muted_soft"],
            activebackground=PALETTE["accent_deep"]
            if voice_input_enabled
            else PALETTE["card_alt"],
            activeforeground=PALETTE["accent"] if voice_input_enabled else PALETTE["muted_soft"],
            cursor="hand2" if voice_input_enabled else "arrow",
        )
        self.message_entry.configure(
            state="normal" if interaction_enabled else "disabled",
            bg=PALETTE["input"] if interaction_enabled else PALETTE["card_alt"],
            disabledbackground=PALETTE["card_alt"],
            disabledforeground=PALETTE["muted_soft"],
        )
        self.mic_selector.configure(state=selector_state)
        self.speaker_selector.configure(state=selector_state)
        self.refresh_devices_button.configure(
            state="disabled" if busy else "normal",
            cursor="arrow" if busy else "hand2",
        )

        self._configure_tile(
            "start",
            title="Start Session" if not self.session_started else "Session Running",
            subtitle=(
                "Enable chat and live controls."
                if not self.session_started
                else "Chat and voice controls are now active."
            ),
            tone="accent" if not self.session_started else "success",
            enabled=(not busy and not self.session_started),
        )
        self._configure_tile(
            "listen",
            title="Listen Now",
            subtitle=(
                "Capture one spoken turn right away."
                if self.session_started and not self.mic_muted
                else "Unavailable while the app mic is muted."
                if self.session_started
                else "Start the session first."
            ),
            tone="accent",
            enabled=self.session_started and not (busy or self.mic_muted),
        )
        self._configure_tile(
            "hands_free",
            title=f"Hands-free {'On' if self.hands_free_enabled else 'Off'}",
            subtitle=(
                "Auto-listen after each reply."
                if self.hands_free_enabled
                else "Manual listens only."
            ),
            tone="success" if self.hands_free_enabled else "neutral",
            enabled=session_active,
        )
        self._configure_tile(
            "mic",
            title="Mic Muted" if self.mic_muted else "Mic Live",
            subtitle=(
                "New captures are blocked."
                if self.mic_muted
                else "NovaAI can start new captures."
            ),
            tone="danger" if self.mic_muted else "success",
            enabled=session_active,
        )
        self._configure_tile(
            "voice",
            title=f"Voice Replies {'On' if self.state.voice_enabled else 'Off'}",
            subtitle=(
                "Replies will be spoken aloud."
                if self.state.voice_enabled
                else "Replies stay text-only."
            ),
            tone="accent" if self.state.voice_enabled else "neutral",
            enabled=session_active,
        )
        self._configure_tile(
            "recalibrate",
            title="Recalibrate",
            subtitle="Relearn room noise.",
            tone="warning",
            enabled=self.session_started and not busy,
        )
        self._configure_tile(
            "performance",
            title="Performance",
            subtitle="Post the live tuning profile.",
            tone="neutral",
            enabled=session_active,
        )
        self._configure_tile(
            "clear_history",
            title="Clear History",
            subtitle="Wipe the saved transcript.",
            tone="danger",
            enabled=self.session_started and not busy,
        )

        self._refresh_summary_labels()

    def _set_status_text(self, message: str) -> None:
        self.status_text.set(message)
        self._update_status_badge()

    def _safe_ui(self, callback: object) -> None:
        if self.closing:
            return
        try:
            self.root.after(0, callback)
        except tk.TclError:
            pass

    def _set_busy(self, busy: bool, reason: str = "") -> None:
        self.busy = busy
        self.busy_reason = reason
        self._refresh_controls()

    def _begin_task(self, reason: str) -> bool:
        if self.busy:
            self._set_status_text(
                f"NovaAI is busy {self.busy_reason or 'right now'}."
            )
            return False
        self._set_busy(True, reason)
        return True

    def _finish_task(self, next_status: str = "System idle. Ready when you are.") -> None:
        self._set_busy(False)
        self._set_status_text(next_status)

    def _schedule_auto_listen(self) -> None:
        if (
            self.closing
            or not self.session_started
            or self.busy
            or not self.hands_free_enabled
            or self.mic_muted
        ):
            return
        self.root.after(350, lambda: self.start_listen(auto=True))

    def _on_send_pressed(self, _event: object) -> None:
        self.send_text_message()

    def _on_voice_hotkey(self, _event: object) -> str:
        self.start_listen_once()
        return "break"

    def _on_mousewheel(self, event: tk.Event[tk.Misc]) -> str:
        self.transcript_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _update_transcript_scrollregion(self) -> None:
        self.transcript_canvas.configure(scrollregion=self.transcript_canvas.bbox("all"))

    def _update_sidebar_scrollregion(self) -> None:
        self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all"))

    def _on_transcript_resize(self, event: tk.Event[tk.Misc]) -> None:
        self.transcript_canvas.itemconfigure(self.message_window, width=event.width)
        self._sync_message_wraplength(event.width)

    def _on_sidebar_resize(self, event: tk.Event[tk.Misc]) -> None:
        self.sidebar_canvas.itemconfigure(self.sidebar_window, width=event.width)

    def _on_sidebar_mousewheel(self, event: tk.Event[tk.Misc]) -> str:
        self.sidebar_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _sync_message_wraplength(self, width: int | None = None) -> None:
        usable_width = width or self.transcript_canvas.winfo_width()
        if usable_width <= 1:
            return
        dialogue_wrap = max(360, min(860, int(usable_width * 0.66)))
        system_wrap = max(420, min(980, int(usable_width * 0.84)))
        for body_label, role in self.message_body_labels:
            body_label.configure(
                wraplength=system_wrap if role == "system" else dialogue_wrap
            )

    def _scroll_transcript_to_end(self) -> None:
        self.root.update_idletasks()
        self.transcript_canvas.yview_moveto(1.0)

    def send_text_message(self) -> None:
        if not self.session_started:
            self._set_status_text("Press Start Session first.")
            return

        raw_text = self.message_entry.get().strip()
        if not raw_text:
            return
        self.message_entry.delete(0, "end")

        if raw_text.startswith("/"):
            self._handle_gui_command(raw_text)
            return

        if not self._begin_task("replying"):
            return

        self._set_status_text("Thinking through your message...")
        worker = threading.Thread(
            target=self._reply_worker,
            args=(raw_text, False),
            daemon=True,
        )
        worker.start()

    def start_session(self) -> None:
        if self.session_started:
            self._set_status_text("Session is already running.")
            return

        self.session_started = True
        self._refresh_summary_labels()
        self._refresh_controls()
        self._append_system_message(
            "Session started. Voice replies are off by default. Toggle Voice Replies when you want spoken output."
        )
        self._set_status_text("Session started.")

        if self.hands_free_enabled and not self.mic_muted and not self.busy:
            self.root.after(250, lambda: self.start_listen(auto=True))

    def _handle_gui_command(self, command: str) -> None:
        lowered = command.strip().lower()

        if lowered in {"/listen", "/ask", "/voiceask"}:
            self.start_listen_once()
            return

        if lowered == "/performance":
            self.show_performance()
            return

        if lowered == "/reset":
            self.clear_history()
            return

        if lowered == "/voice":
            self.toggle_voice_output()
            return

        if lowered == "/tts":
            self._append_system_message(
                f"TTS provider is currently {self.config.tts_provider}."
            )
            return

        if lowered.startswith("/tts "):
            choice = lowered[5:].strip()
            if choice in {"xtts", "gtts"}:
                self.config.tts_provider = choice
                self._append_system_message(
                    f"TTS provider switched to {self.config.tts_provider}."
                )
            else:
                self._append_system_message("Use /tts xtts or /tts gtts.")
            return

        if lowered == "/mode voice":
            if not self.hands_free_enabled:
                self.toggle_hands_free()
            return

        if lowered == "/mode text":
            if self.hands_free_enabled:
                self.toggle_hands_free()
            return

        if lowered == "/recalibrate":
            self.start_recalibration()
            return

        if lowered == "/web" or lowered.startswith("/web "):
            self._handle_web_command(command)
            return

        if lowered == "/profile":
            self._append_system_message(
                json.dumps(self.profile, indent=2, ensure_ascii=False)
            )
            return

        if lowered == "/profiles":
            summaries = list_profiles()
            lines = ["Profiles:"]
            for summary in summaries:
                active_tag = " (active)" if summary["is_active"] else ""
                lines.append(
                    f"- {summary['profile_id']}: {summary['profile_name']}{active_tag}"
                )
            self._append_system_message("\n".join(lines))
            return

        if lowered.startswith("/profile use "):
            target_profile_id = command.strip()[13:].strip()
            if not target_profile_id:
                self._append_system_message("Use /profile use <profile_id>.")
                return
            try:
                active_profile = set_active_profile(target_profile_id)
            except RuntimeError as exc:
                self._append_system_message(str(exc))
                return
            self.active_profile_id = target_profile_id
            self.profile = active_profile
            self._refresh_profiles_panel(select_profile_id=target_profile_id)
            self._refresh_summary_labels()
            self._refresh_controls()
            self._append_system_message(
                f"Active profile switched to {self.profile.get('profile_name', target_profile_id)}."
            )
            return

        if lowered == "/help":
            self._append_system_message(
                "GUI commands: /listen, /ask, /performance, /reset, /voice, /tts, /tts xtts, /tts gtts, /mode voice, "
                "/mode text, /recalibrate, /web, /web on, /web off, /web auto on, "
                "/web auto off, /web clear, /web <query>, /profile, /profiles, "
                "/profile use <id>. Hotkey: F8 triggers Voice Ask."
            )
            return

        self._append_system_message(
            "That slash command is not wired into the GUI yet. The full command set still lives in the CLI."
        )

    def _web_status_text(self) -> str:
        queued_query = self.state.pending_web_query or "none"
        queued_context = "ready" if self.state.pending_web_context else "none"
        return (
            "Web browsing: "
            f"{'on' if self.config.web_browsing_enabled else 'off'} | "
            f"Auto-search: {'on' if self.config.web_auto_search else 'off'} | "
            f"Provider: {self.config.web_search_provider} | "
            f"Max results: {self.config.web_max_results} | "
            f"Timeout: {self.config.web_timeout_seconds}s | "
            f"Region: {self.config.web_region} | "
            f"SafeSearch: {self.config.web_safesearch} | "
            f"Queued query: {queued_query} | "
            f"Queued context: {queued_context}"
        )

    def _handle_web_command(self, command: str) -> None:
        lowered = command.strip().lower()
        if lowered == "/web":
            self._append_system_message(self._web_status_text())
            return

        argument = command.strip()[4:].strip()
        if not argument:
            self._append_system_message(self._web_status_text())
            return

        lowered_argument = argument.lower()

        if lowered_argument in {"on", "off"}:
            self.config.web_browsing_enabled = lowered_argument == "on"
            if not self.config.web_browsing_enabled:
                self.state.pending_web_query = None
                self.state.pending_web_context = None
            self._append_system_message(
                f"Web browsing is now {'on' if self.config.web_browsing_enabled else 'off'}."
            )
            return

        if lowered_argument in {"clear", "reset"}:
            self.state.pending_web_query = None
            self.state.pending_web_context = None
            self._append_system_message("Cleared queued web context.")
            return

        if lowered_argument == "auto":
            self._append_system_message(
                f"Web auto-search is {'on' if self.config.web_auto_search else 'off'}."
            )
            return

        if lowered_argument.startswith("auto "):
            toggle = lowered_argument[5:].strip()
            if toggle in {"on", "true", "1", "yes"}:
                self.config.web_auto_search = True
            elif toggle in {"off", "false", "0", "no"}:
                self.config.web_auto_search = False
            else:
                self._append_system_message("Use /web auto on or /web auto off.")
                return
            self._append_system_message(
                f"Web auto-search is now {'on' if self.config.web_auto_search else 'off'}."
            )
            return

        if not self.config.web_browsing_enabled:
            self._append_system_message("Web browsing is off. Run /web on first.")
            return

        self.state.pending_web_query = argument
        self.state.pending_web_context = None
        self._append_system_message(
            f"Queued web search for the next reply: {argument}"
        )

    def start_listen_once(self) -> None:
        self.start_listen(auto=False)

    def start_listen(self, auto: bool) -> None:
        if not self.session_started:
            self._set_status_text("Press Start Session first.")
            return

        if self.mic_muted:
            self._set_status_text("Mic is muted. Unmute it before listening.")
            return

        if not self._begin_task("listening"):
            return

        self._set_status_text("Listening for your voice...")
        worker = threading.Thread(
            target=self._voice_turn_worker,
            args=(auto,),
            daemon=True,
        )
        worker.start()

    def _voice_turn_worker(self, auto: bool) -> None:
        next_status = "System idle. Ready when you are."
        try:
            result = recognize_speech(self.config, self.state, announce=False)

            if result.status == "timeout":
                next_status = "No speech detected."
                return

            if result.status == "unknown":
                next_status = "I heard something, but it did not transcribe cleanly."
                return

            if result.status != "ok":
                raise RuntimeError(
                    result.error or "Speech recognition did not return a usable result."
                )

            user_text = result.text.strip()
            if not user_text:
                next_status = "No speech detected."
                return

            next_status = self._perform_reply_pipeline(user_text, from_voice=True)
        except Exception as exc:
            next_status = f"Audio error: {exc}"
            self._safe_ui(lambda: self._append_system_message(next_status))
        finally:
            self._safe_ui(lambda: self._finish_task(next_status))
            if self.hands_free_enabled and not self.mic_muted and not self.closing:
                self._safe_ui(self._schedule_auto_listen)

    def _reply_worker(self, user_text: str, from_voice: bool) -> None:
        next_status = "System idle. Ready when you are."
        try:
            next_status = self._perform_reply_pipeline(user_text, from_voice=from_voice)
        except Exception as exc:
            next_status = f"Companion error: {exc}"
            self._safe_ui(lambda: self._append_system_message(next_status))
        finally:
            self._safe_ui(lambda: self._finish_task(next_status))
            if self.hands_free_enabled and not self.mic_muted and not self.closing:
                self._safe_ui(self._schedule_auto_listen)

    def _perform_reply_pipeline(self, user_text: str, from_voice: bool) -> str:
        self._safe_ui(
            lambda: self._append_message(self.profile["user_name"], user_text, "user")
        )
        self._safe_ui(lambda: self._set_status_text("Thinking through your message..."))

        web_context: str | None = None
        web_note: str | None = None
        if self.config.web_browsing_enabled:
            web_query = self.state.pending_web_query
            if self.state.pending_web_context:
                web_context = self.state.pending_web_context
                self.state.pending_web_context = None
                self.state.pending_web_query = None
                if web_query:
                    web_note = f"Using queued web results for: {web_query}"
            else:
                if not web_query:
                    inferred_query = extract_web_query_from_request(user_text)
                    if inferred_query:
                        web_query = inferred_query
                        web_note = f"Interpreted your request as lookup: {web_query}"
                if not web_query and self.config.web_auto_search and should_auto_search(user_text):
                    web_query = user_text
                if web_query:
                    try:
                        bundle = fetch_web_context(web_query, self.config)
                    except RuntimeError as exc:
                        web_note = f"Web search skipped: {exc}"
                    else:
                        web_context = bundle.context
                        web_note = (
                            f"Web search found {bundle.result_count} results for: "
                            f"{bundle.query}"
                        )
                    finally:
                        self.state.pending_web_query = None

        if web_note:
            self._safe_ui(lambda message=web_note: self._append_system_message(message))

        reply = request_reply(
            user_text,
            self.profile,
            self.config,
            web_context=web_context,
        )
        append_history("user", user_text)
        append_history("assistant", reply)

        self._safe_ui(
            lambda: self._append_message(
                self.profile["companion_name"],
                reply,
                "assistant",
            )
        )

        if self.state.voice_enabled:
            self._safe_ui(lambda: self._set_status_text("Speaking the reply..."))
            audio_path = speak_text(reply, self.config, self.state)
            if should_play_audio_after_synthesis(self.config):
                play_audio_file(audio_path, self.config.speaker_device_index)

        if from_voice and self.hands_free_enabled and not self.mic_muted:
            return "Reply finished. Hands-free will listen again."
        return "System idle. Ready when you are."

    def toggle_hands_free(self) -> None:
        self.hands_free_enabled = not self.hands_free_enabled
        self.config.input_mode = "voice" if self.hands_free_enabled else "text"
        self._refresh_summary_labels()
        self._refresh_controls()

        if self.hands_free_enabled:
            self._set_status_text("Hands-free mode is on.")
            if not self.busy and not self.mic_muted:
                self.root.after(300, lambda: self.start_listen(auto=True))
            return

        self._set_status_text("Hands-free mode is off.")

    def toggle_mic_muted(self) -> None:
        self.mic_muted = not self.mic_muted
        self._refresh_summary_labels()
        self._refresh_controls()

        if self.mic_muted:
            if self.busy and self.busy_reason == "listening":
                self._set_status_text(
                    "Mic muted. The current listen will finish, then NovaAI will stop listening."
                )
            else:
                self._set_status_text("Mic muted.")
            return

        self._set_status_text("Mic live.")
        if self.hands_free_enabled and not self.busy:
            self.root.after(250, lambda: self.start_listen(auto=True))

    def toggle_voice_output(self) -> None:
        self.state.voice_enabled = not self.state.voice_enabled
        self._refresh_summary_labels()
        self._refresh_controls()
        self._set_status_text(
            f"Voice replies {'enabled' if self.state.voice_enabled else 'disabled'}."
        )

    def start_recalibration(self) -> None:
        if not self._begin_task("recalibrating"):
            return

        self._set_status_text("Calibrating the microphone...")
        worker = threading.Thread(target=self._recalibration_worker, daemon=True)
        worker.start()

    def _recalibration_worker(self) -> None:
        next_status = "Microphone calibration complete."
        try:
            self.state.speech_recognizer = None
            self.state.speech_recognizer_signature = None
            self.state.mic_calibrated = False
            recalibrate_microphone(self.config, self.state, announce=False)
        except Exception as exc:
            next_status = f"Microphone calibration failed: {exc}"
            self._safe_ui(lambda: self._append_system_message(next_status))
        finally:
            self._safe_ui(lambda: self._finish_task(next_status))
            if self.hands_free_enabled and not self.mic_muted and not self.closing:
                self._safe_ui(self._schedule_auto_listen)

    def show_performance(self) -> None:
        lines = [
            f"Active profile: {self.profile.get('profile_name', self.active_profile_id)} ({self.active_profile_id})",
            f"Performance profile: {self.config.performance_profile}",
            f"Auto-tune: {'on' if self.config.auto_tune_performance else 'off'} ({self.config.auto_tune_goal})",
            f"Hardware: {self.config.system_summary}",
            f"Provider: {self.config.llm_provider}",
            f"Endpoint: {self.config.llm_api_url}",
            f"Reply limit: {self.config.llm_num_predict}",
            f"STT: {describe_stt_backend(self.config)}",
            f"TTS provider: {self.config.tts_provider}",
            (
                f"XTTS: {get_xtts_device(self.config)} at speed {self.config.xtts_speed:.2f}"
                if self.config.tts_provider == "xtts"
                else f"gTTS language: {self.config.tts_language}"
            ),
            f"Mic: {describe_selected_microphone(self.config)}",
            f"Speaker: {describe_selected_speaker(self.config)}",
        ]
        lines.extend(self.config.performance_notes)
        print()
        print("[NovaAI GUI] Runtime diagnostics")
        for line in lines:
            print(f"[NovaAI GUI] {line}")
        print()
        self._set_status_text("Diagnostics printed to console.")

    def clear_history(self) -> None:
        if self.busy:
            self._set_status_text(
                "Wait for the current task to finish before clearing history."
            )
            return

        confirmed = messagebox.askyesno(
            "Clear history",
            "Delete the saved conversation history for NovaAI?",
            parent=self.root,
        )
        if not confirmed:
            return

        reset_history()
        for child in self.message_column.winfo_children():
            child.destroy()
        self.message_body_labels.clear()
        self._append_system_message("Conversation history cleared.")
        self._set_status_text("Conversation history cleared.")

    def close(self) -> None:
        self.closing = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = NovaAIGui(auto_listen_on_launch=False)
    app.run()
