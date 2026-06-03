"""NovaAI - pywebview desktop GUI with Tailwind CSS frontend."""
from __future__ import annotations

import base64
import collections
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# pywebview is the OPTIONAL native-desktop-GUI backend. The headless web server
# (novaai/webserver.py) reuses the Api class from this module without needing it,
# so guard the import: it's only actually used inside main() for `--gui`.
try:
    import webview
except ImportError:  # pragma: no cover - desktop GUI extra not installed
    webview = None  # type: ignore[assignment]

from .audio_input import (
    describe_selected_microphone,
    describe_stt_backend,
    list_input_devices_compact,
    recalibrate_microphone,
    recognize_speech,
)
from .avatar import AvatarBridge
from .config import Config
from .engine import GenerationRequest, generate_reply
from .memory import MemoryStore
from .twitch import TwitchClient
from . import stream_events
from .features import (
    handle_feature_request,
    check_due_reminders,
    check_due_alarms,
    add_reminder,
    list_reminders,
    delete_reminder_by_id,
    add_alarm,
    list_alarms,
    cancel_alarm_by_id,
    cancel_all_alarms,
    add_todo,
    list_todos,
    toggle_todo,
    delete_todo,
    add_shopping_item,
    list_shopping,
    toggle_shopping_item,
    clear_shopping_done,
    clear_shopping_all,
    add_calendar_event,
    list_calendar_events,
    delete_calendar_event,
    _parse_any_datetime,
    _extract_time_str,
)
from .media import handle_media_request
from .media_player import stop_media_playback
from .models import SessionState
from .paths import MMD_DIR
from .storage import (
    _safe_profile_id,
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

STATIC_DIR = Path(__file__).resolve().parent / "static"
ICON_PATH = Path(__file__).resolve().parent.parent / "data" / "logo.ico"
WINDOW_TITLE = "NovaAI Studio"
WINDOWS_APP_ID = "NekoSuneProjects.NovaAI.Studio"
_window: "webview.Window | None" = None
# Pluggable JS sink for headless web mode. When set (by novaai/webserver.py),
# Api._js() relays code here instead of to a pywebview window. See _js().
_emit_js: "Callable[[str], None] | None" = None

# Per-driver game settings shown in the Game panel (instead of editing .env).
# Each field maps to a Config attribute; values are persisted to app_state.
GAME_SETTINGS_SCHEMA: dict[str, dict[str, Any]] = {
    "minecraft": {
        "label": "Minecraft (Mineflayer + Node)",
        "preview": True,
        "fields": [
            {"key": "mc_host", "label": "Server host", "type": "text"},
            {"key": "mc_port", "label": "Server port", "type": "int"},
            {"key": "mc_username", "label": "Bot username / MS email", "type": "text"},
            {"key": "mc_auth", "label": "Auth mode", "type": "select", "options": ["offline", "microsoft"]},
            {"key": "mc_owner_username", "label": "Owner username", "type": "text"},
            {"key": "mc_help_whitelist", "label": "Help whitelist (comma-separated)", "type": "list"},
            {"key": "mc_version", "label": "MC version (blank = auto)", "type": "text"},
            {"key": "mc_home", "label": "Home x,y,z (optional)", "type": "text"},
            {"key": "mc_bridge_port", "label": "Bridge port", "type": "int"},
            {"key": "mc_viewer_port", "label": "Live-view port", "type": "int"},
            {"key": "mc_viewer_first_person", "label": "First-person view", "type": "bool"},
            {"key": "game_tick_seconds", "label": "Think interval (sec)", "type": "float"},
        ],
    },
    "universal": {
        "label": "Universal (vision + keyboard)",
        "preview": False,
        "fields": [
            {"key": "game_universal_name", "label": "Game name (e.g. Unturned, Terraria)", "type": "text"},
            {"key": "vision_model", "label": "Vision model (Ollama, e.g. moondream)", "type": "text"},
            {"key": "game_tick_seconds", "label": "Think interval (sec)", "type": "float"},
        ],
    },
    "vrchat": {
        "label": "VRChat (OSC)",
        "preview": False,
        "fields": [
            {"key": "vrchat_osc_host", "label": "OSC host", "type": "text"},
            {"key": "vrchat_osc_port", "label": "OSC port", "type": "int"},
            {"key": "vision_model", "label": "Vision model (optional)", "type": "text"},
            {"key": "game_tick_seconds", "label": "Think interval (sec)", "type": "float"},
        ],
    },
    "factorio": {
        "label": "Factorio (RCON)",
        "preview": False,
        "fields": [
            {"key": "factorio_rcon_host", "label": "RCON host", "type": "text"},
            {"key": "factorio_rcon_port", "label": "RCON port", "type": "int"},
            {"key": "factorio_rcon_password", "label": "RCON password", "type": "password"},
            {"key": "game_tick_seconds", "label": "Think interval (sec)", "type": "float"},
        ],
    },
    "osu": {
        "label": "osu! (offline / solo only)",
        "preview": False,
        "fields": [
            {"key": "osu_allow_online", "label": "Allow online (BANNABLE — at your own risk)", "type": "bool"},
            {"key": "vision_model", "label": "Vision model (Ollama)", "type": "text"},
            {"key": "game_tick_seconds", "label": "Think interval (sec)", "type": "float"},
        ],
    },
}
_GAME_FIELD_TYPES: dict[str, str] = {
    f["key"]: f["type"] for meta in GAME_SETTINGS_SCHEMA.values() for f in meta["fields"]
}


# General app settings shown in the Settings panel (override .env, persisted).
# "model" fields render with an auto-detected dropdown for their category.
APP_SETTINGS_SCHEMA: dict[str, dict[str, Any]] = {
    "llm": {
        "label": "AI Provider & Models",
        "fields": [
            {"key": "llm_provider", "label": "Provider", "type": "select",
             "options": ["ollama", "openai", "claude-code", "codex", "cli"]},
            {"key": "model", "label": "Chat model", "type": "model", "category": "chat"},
            {"key": "vision_model", "label": "Vision model", "type": "model", "category": "vision"},
            {"key": "rag_embedding_provider", "label": "Embedding provider", "type": "select",
             "options": ["local", "ollama", "openai"]},
            {"key": "rag_embedding_model", "label": "Embedding model", "type": "model", "category": "embedding"},
            {"key": "llm_api_url", "label": "API URL (openai/LiteLLM)", "type": "text"},
            {"key": "llm_api_key", "label": "API key", "type": "password"},
            {"key": "temperature", "label": "Temperature", "type": "float"},
        ],
    },
    "twitch": {
        "label": "Twitch",
        "fields": [
            {"key": "twitch_channel", "label": "Channel (no #)", "type": "text"},
            {"key": "twitch_bot_username", "label": "Bot username (blank = anonymous read-only)", "type": "text"},
            {"key": "twitch_oauth_token", "label": "OAuth token (blank = anonymous)", "type": "password"},
            {"key": "twitch_reply_mode", "label": "Reply mode", "type": "select",
             "options": ["mention", "all", "command"]},
            {"key": "twitch_allowed_roles", "label": "Who can talk to NovaAI", "type": "select",
             "options": ["everyone", "subscribers", "moderators"]},
            {"key": "twitch_reply_cooldown_seconds", "label": "Reply cooldown (sec)", "type": "float"},
        ],
    },
    "alerts": {
        "label": "Stream Alerts (donations / subs / raids)",
        "fields": [
            {"key": "streamlabs_socket_token", "label": "Streamlabs socket token (blank = off)", "type": "password"},
            {"key": "streamelements_jwt_token", "label": "StreamElements JWT token (blank = off)", "type": "password"},
            {"key": "streamlabs_platforms", "label": "Streamlabs platforms (blank = all; e.g. twitch,kick)", "type": "str"},
        ],
    },
    "voice": {
        "label": "Voice (TTS)",
        "fields": [
            {"key": "tts_provider", "label": "TTS engine", "type": "select", "options": ["xtts", "gtts"]},
            {"key": "audio_output", "label": "Audio output (voice/singing/music)", "type": "select", "options": ["speaker", "browser", "both"]},
            {"key": "xtts_speaker", "label": "XTTS speaker", "type": "text"},
            {"key": "xtts_speaker_wav", "label": "Voice clone .wav (optional)", "type": "text"},
            {"key": "xtts_speed", "label": "Speed", "type": "float"},
            {"key": "tts_language", "label": "Language", "type": "text"},
        ],
    },
    "stt": {
        "label": "Speech-to-Text",
        "fields": [
            {"key": "stt_provider", "label": "STT engine", "type": "select",
             "options": ["faster-whisper", "google"]},
            {"key": "stt_model", "label": "Whisper model", "type": "text"},
            {"key": "stt_language", "label": "Language", "type": "text"},
        ],
    },
    "media": {
        "label": "Media",
        "fields": [
            {"key": "media_region", "label": "Region", "type": "text"},
            {"key": "music_provider_default", "label": "Music provider", "type": "select",
             "options": ["soundcloud", "radio", "deezer", "spotify"]},
            {"key": "soundcloud_stream_endpoint", "label": "Stream endpoint", "type": "text"},
        ],
    },
    "singing": {
        "label": "Singing",
        "fields": [
            {"key": "singing_enabled", "label": "Enable singing", "type": "bool"},
            {"key": "singing_backend", "label": "Backend", "type": "select",
             "options": ["local", "rvc", "cloud"]},
            {"key": "rvc_model_path", "label": "RVC model .pth (rvc)", "type": "text"},
            {"key": "singing_api_url", "label": "Singing API URL (cloud)", "type": "text"},
            {"key": "singing_api_key", "label": "Singing API key (cloud)", "type": "password"},
        ],
    },
}
_APP_FIELD_TYPES: dict[str, str] = {
    f["key"]: f["type"] for meta in APP_SETTINGS_SCHEMA.values() for f in meta["fields"]
}


def _coerce_game_setting(value: Any, ftype: str) -> Any:
    if ftype == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if ftype == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 1.0
    if ftype == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if ftype == "list":
        items = value if isinstance(value, (list, tuple)) else str(value).split(",")
        return tuple(str(s).strip() for s in items if str(s).strip())
    return str(value).strip()


class Api:
    """Python backend exposed to JavaScript via pywebview.api."""

    def __init__(self) -> None:
        # Bare minimum so the window can open instantly with the loading screen.
        # Heavy work (config, DB, profiles) is deferred to initialize().
        self.config: Config | None = None
        self.active_profile_id: str = ""
        self.profile: dict = {}
        self.state = SessionState(voice_enabled=False, input_mode="text")
        self.session_started = False
        self.hands_free_enabled = False
        self.mic_muted = False
        self.media_enabled = True   # music/radio playback feature toggle
        self.busy = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._initialized = False
        # Streaming (Twitch) + memory
        self.memory: MemoryStore | None = None
        self.twitch: TwitchClient | None = None
        self.stream_started = False
        self._stream_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._stream_responder_thread: threading.Thread | None = None
        self._last_stream_reply = 0.0
        self.alert_sources: list = []          # Streamlabs / StreamElements clients
        self._seen_event_ids: collections.deque[str] = collections.deque(maxlen=512)
        self._session_earnings = 0.0
        # Avatar
        self.avatar: AvatarBridge | None = None
        self._last_amplitude_emit = 0.0
        # Game agent
        self.game_agent: Any = None
        self.game_driver_key: str | None = None  # the actually-running driver

    def initialize(self) -> dict[str, Any]:
        """Heavy init — called from JS once the loading screen is visible."""
        ensure_runtime_dirs()
        self.config = Config.from_env()
        self._apply_saved_app_settings()
        self._apply_saved_game_settings()
        self.memory = MemoryStore(self.config)
        self.active_profile_id = get_active_profile_id()
        self.profile = load_profile() or {}
        self.state = SessionState(
            voice_enabled=False,
            input_mode=self.config.input_mode,
        )
        self.config.voice_enabled = False
        self.hands_free_enabled = self.config.input_mode == "voice"
        # Restore the Voice & Input + Media toggles saved last session.
        self._apply_saved_ui_prefs()
        self._initialized = True
        self._start_avatar_if_enabled()
        # Update window title with the loaded companion name
        global _window
        if _window:
            name = self.profile.get("companion_name", "NovaAI")
            try:
                _window.set_title(f"{name} Studio")
            except Exception:
                pass
        return self.get_state()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _not_ready(self) -> dict[str, Any] | None:
        """Return an error dict if initialize() hasn't run yet, else None."""
        if not self._initialized:
            return {"ok": False, "msg": "Still loading, please wait..."}
        return None

    def _js(self, code: str) -> None:
        """Push JavaScript to the frontend.

        In the native desktop GUI this runs in the pywebview window. In headless
        web mode (novaai/webserver.py) there is no window, so the code is handed
        to a pluggable sink (`_emit_js`) that relays it to connected browsers.
        """
        global _window, _emit_js
        if _window:
            try:
                _window.evaluate_js(code)
            except Exception:
                pass
        elif _emit_js is not None:
            try:
                _emit_js(code)
            except Exception:
                pass

    def _push_state(self) -> None:
        self._js(f"window.__onStateUpdate({json.dumps(self.get_state())})")

    def _push_chat(self, author: str, text: str, role: str) -> None:
        payload = json.dumps({"author": author, "text": text, "role": role})
        self._js(f"window.__onChatMessage({payload})")

    def _push_status(self, msg: str) -> None:
        safe = json.dumps(msg)
        self._js(f"window.__onStatusUpdate({safe})")

    def _push_notification(self, msg: str) -> None:
        safe = json.dumps(msg)
        self._js(f"window.__onNotification({safe})")

    # ── state ─────────────────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        cfg = self.config
        return {
            "session_started": self.session_started,
            "voice_enabled": self.state.voice_enabled,
            "hands_free": self.hands_free_enabled,
            "mic_muted": self.mic_muted,
            "web_search": cfg.web_browsing_enabled if cfg else False,
            "web_auto_search": cfg.web_auto_search if cfg else False,
            "media_enabled": self.media_enabled,
            "busy": self.busy,
            "model": cfg.model if cfg else "--",
            "llm_provider": cfg.llm_provider if cfg else "--",
            "performance_profile": cfg.performance_profile if cfg else "--",
            "system_summary": cfg.system_summary if cfg else "--",
            "tts_provider": cfg.tts_provider if cfg else "--",
            "stt_provider": cfg.stt_provider if cfg else "--",
            "stt_model": cfg.stt_model if cfg else "--",
            "web_search_provider": cfg.web_search_provider if cfg else "--",
            "web_search_url": cfg.web_search_url if cfg else "--",
            "companion_name": self.profile.get("companion_name", "NovaAI"),
            "user_name": self.profile.get("user_name", "Friend"),
            "description": self.profile.get("description", ""),
            "input_mode": "voice" if self.hands_free_enabled else "text",
            "active_profile_id": self.active_profile_id,
            "initialized": self._initialized,
        }

    # ── session controls ──────────────────────────────────────────────────────

    def start_session(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        if self.session_started:
            return {"ok": False, "msg": "Session is already running."}
        self.session_started = True
        self._push_state()
        self._push_chat("System", "Session started. You can now chat and use voice controls.", "system")
        if self.hands_free_enabled and not self.mic_muted:
            threading.Thread(target=self._auto_listen, daemon=True).start()
        return {"ok": True, "msg": "Session started."}

    def toggle_voice(self) -> dict[str, Any]:
        self.state.voice_enabled = not self.state.voice_enabled
        self._save_ui_pref("voice_enabled", self.state.voice_enabled)
        self._push_state()
        return {"voice_enabled": self.state.voice_enabled}

    def toggle_handsfree(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.hands_free_enabled = not self.hands_free_enabled
        self.config.input_mode = "voice" if self.hands_free_enabled else "text"
        self._save_ui_pref("hands_free", self.hands_free_enabled)
        self._push_state()
        if self.hands_free_enabled and not self.busy and not self.mic_muted and self.session_started:
            threading.Thread(target=self._auto_listen, daemon=True).start()
        return {"hands_free": self.hands_free_enabled}

    def toggle_mic(self) -> dict[str, Any]:
        self.mic_muted = not self.mic_muted
        self._save_ui_pref("mic_muted", self.mic_muted)
        self._push_state()
        if not self.mic_muted and self.hands_free_enabled and not self.busy and self.session_started:
            threading.Thread(target=self._auto_listen, daemon=True).start()
        return {"mic_muted": self.mic_muted}

    def toggle_web_search(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.config.web_browsing_enabled = not self.config.web_browsing_enabled
        self._save_ui_pref("web_search", self.config.web_browsing_enabled)
        self._push_state()
        return {"web_search": self.config.web_browsing_enabled}

    def toggle_media(self) -> dict[str, Any]:
        self.media_enabled = not self.media_enabled
        self._save_ui_pref("media_enabled", self.media_enabled)
        self._push_state()
        return {"media_enabled": self.media_enabled}

    def toggle_auto_search(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.config.web_auto_search = not self.config.web_auto_search
        self._save_ui_pref("web_auto_search", self.config.web_auto_search)
        self._push_state()
        return {"web_auto_search": self.config.web_auto_search}

    # ── chat ──────────────────────────────────────────────────────────────────

    def send_message(self, text: str) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        if not text or not text.strip():
            return {"ok": False, "msg": "Empty message."}
        if not self.session_started:
            return {"ok": False, "msg": "Start a session first."}
        text = text.strip()
        if text.startswith("/"):
            return self._handle_command(text)
        if not self._acquire():
            return {"ok": False, "msg": "System is busy."}
        try:
            result = self._pipeline(text, from_voice=False)
            return {"ok": True, "msg": result}
        finally:
            self._release()

    def stop_generation(self) -> dict[str, Any]:
        """Interrupt the current pipeline (LLM / TTS / playback)."""
        if not self.busy:
            return {"ok": False, "msg": "Nothing to stop."}
        self._stop_event.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        return {"ok": True}

    def start_listen(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        if not self.session_started:
            return {"ok": False, "msg": "Start a session first."}
        if self.mic_muted:
            return {"ok": False, "msg": "Microphone is muted."}
        if not self._acquire():
            return {"ok": False, "msg": "System is busy."}
        try:
            self._push_status("Listening...")
            self._push_state()
            result = recognize_speech(self.config, self.state, announce=False)
            if result.status == "timeout":
                self._push_status("No speech detected.")
                return {"ok": False, "msg": "No speech detected."}
            if result.status == "unknown":
                self._push_status("Could not transcribe clearly.")
                return {"ok": False, "msg": "Could not transcribe clearly."}
            if result.status != "ok":
                msg = result.error or "Speech recognition failed."
                self._push_status(msg)
                return {"ok": False, "msg": msg}
            text = result.text.strip()
            if not text:
                self._push_status("No speech detected.")
                return {"ok": False, "msg": "No speech detected."}
            status = self._pipeline(text, from_voice=True)
            return {"ok": True, "msg": status, "text": text}
        except Exception as exc:
            msg = f"Audio error: {exc}"
            self._push_status(msg)
            return {"ok": False, "msg": msg}
        finally:
            self._release()
            # Re-arm hands-free listening no matter how the turn ended — normal
            # reply, early-handled request, timeout, or a backend error. Without
            # this, any failure mid-turn silently ends the conversation and Nova
            # stops responding to speech after the first prompt.
            if (
                self.hands_free_enabled
                and not self.mic_muted
                and self.session_started
                and not self._stopped()
            ):
                threading.Thread(target=self._auto_listen, daemon=True).start()

    def _auto_listen(self) -> None:
        time.sleep(0.3)
        if self.busy or self.mic_muted or not self.session_started or not self.hands_free_enabled:
            return
        self.start_listen()

    def _handle_command(self, cmd: str) -> dict[str, Any]:
        lower = cmd.strip().lower()
        if lower in {"/listen", "/ask", "/voiceask"}:
            return self.start_listen()
        if lower == "/reset":
            return self.clear_history()
        if lower == "/voice":
            return self.toggle_voice()
        self._push_chat("System", f"Unknown command: {cmd}", "system")
        return {"ok": False, "msg": f"Unknown command: {cmd}"}

    # ── pipeline (runs in api thread) ─────────────────────────────────────────

    def _stopped(self) -> bool:
        return self._stop_event.is_set()

    def _pipeline(self, user_text: str, from_voice: bool) -> str:
        self._stop_event.clear()
        user_name = self.profile.get("user_name", "You")
        companion = self.profile.get("companion_name", "NovaAI")

        self._push_chat(user_name, user_text, "user")
        self._push_status("Thinking...")

        # Media (music/radio) — only when the feature is enabled.
        media_action = handle_media_request(user_text, self.profile, self.config) if self.media_enabled else None
        if media_action and media_action.handled:
            self.profile = save_profile_by_id(self.active_profile_id, self.profile)
            append_history("user", user_text)
            append_history("assistant", media_action.response)
            self._push_chat(companion, media_action.response, "assistant")
            # Dance to the music (or stop when playback stops).
            low = user_text.lower()
            if any(w in low for w in ("stop", "pause", "silence", "quiet", "turn off")):
                self._avatar_dance(False)
            elif any(w in low for w in ("play", "radio", "music", "song", "listen")):
                self._avatar_dance(True)
            self._push_status("Media request handled.")
            return "Media request handled."

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        # Features
        feature_result = handle_feature_request(user_text, self.profile)
        if feature_result.handled:
            if feature_result.save_needed:
                self.profile = save_profile_by_id(self.active_profile_id, self.profile)
            append_history("user", user_text)
            append_history("assistant", feature_result.response)
            self._push_chat(companion, feature_result.response, "assistant")
            self._js("window.__onFeaturesChanged()")
            if self.state.voice_enabled and not self._stopped():
                self._speak(feature_result.response, "neutral")
            self._push_status("Ready.")
            return "Feature request handled."

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        # Game command — if a game agent is running, route in-game orders to it
        # (combat, build, mine, follow, etc.) instead of just chatting about them.
        game_reply = self._maybe_handle_game_command(user_text)
        if game_reply is not None:
            append_history("user", user_text)
            append_history("assistant", game_reply)
            self._push_chat(companion, game_reply, "assistant")
            if self.state.voice_enabled and not self._stopped():
                self._speak(game_reply, "neutral")
            self._push_status("Ready.")
            return "Game command handled."

        # Web context
        web_context: str | None = None
        if self.config.web_browsing_enabled:
            web_query = self.state.pending_web_query
            if self.state.pending_web_context:
                web_context = self.state.pending_web_context
                self.state.pending_web_context = None
                self.state.pending_web_query = None
            else:
                if not web_query:
                    inferred = extract_web_query_from_request(user_text)
                    if inferred:
                        web_query = inferred
                        self._push_chat("System", f"Searching: {web_query}", "system")
                if not web_query and self.config.web_auto_search and should_auto_search(user_text):
                    web_query = user_text
                if web_query and not self._stopped():
                    try:
                        bundle = fetch_web_context(web_query, self.config)
                        web_context = bundle.context
                        self._push_chat("System", f"Web: {bundle.result_count} results for: {bundle.query}", "system")
                    except RuntimeError as exc:
                        self._push_chat("System", f"Web search skipped: {exc}", "system")
                    finally:
                        self.state.pending_web_query = None

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        self._push_status("Generating reply...")
        result = generate_reply(
            GenerationRequest(
                user_text=user_text,
                profile=self.profile,
                config=self.config,
                source="chat",
                web_context=web_context,
                extra_system=self._game_awareness() + self._recall(user_text),
            )
        )
        reply = result.reply

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        append_history("user", user_text)
        append_history("assistant", reply)
        self._push_chat(companion, reply, "assistant")
        self._remember_exchange(user_name, user_text, reply, source="chat")

        if self.state.voice_enabled and not self._stopped():
            self._push_status("Speaking...")
            self._speak(reply, result.emotion)

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        # Hands-free re-listen is re-armed by start_listen()'s finally block so
        # it fires on every exit path (including errors), not just here.
        if from_voice and self.hands_free_enabled and not self.mic_muted:
            self._push_status("Listening...")
            return "Hands-free listening."

        self._push_status("Ready.")
        return "Ready."

    # ── busy guard ────────────────────────────────────────────────────────────

    def _acquire(self) -> bool:
        with self._lock:
            if self.busy:
                return False
            self.busy = True
        self._push_state()
        return True

    def _release(self) -> None:
        with self._lock:
            self.busy = False
        self._push_state()

    # ── memory (RAG) ────────────────────────────────────────────────────────────

    def _recall(self, query: str) -> list[str]:
        if not self.memory or not self.config or not self.config.rag_enabled:
            return []
        try:
            memories = self.memory.recall(query, self.active_profile_id)
        except Exception:
            return []
        if not memories:
            return []
        joined = "; ".join(memories)
        return [f"Relevant things you remember: {joined}"]

    def _remember_exchange(
        self, speaker: str, user_text: str, reply: str, source: str
    ) -> None:
        if not self.memory or not self.config or not self.config.rag_enabled:
            return
        try:
            self.memory.remember(
                self.active_profile_id,
                content=user_text,
                source=source,
                speaker=speaker,
            )
        except Exception:
            pass

    def get_memories(self) -> list[dict[str, Any]]:
        if not self.memory:
            return []
        try:
            return self.memory.list_recent(self.active_profile_id)
        except Exception:
            return []

    def reinforce_memory(self, memory_id: int, delta: float) -> dict[str, Any]:
        if not self.memory:
            return {"ok": False, "msg": "Memory not ready."}
        try:
            self.memory.reinforce(int(memory_id), float(delta))
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def forget_memory(self, memory_id: int) -> dict[str, Any]:
        if not self.memory:
            return {"ok": False, "msg": "Memory not ready."}
        try:
            self.memory.forget(int(memory_id))
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ── streaming (Twitch) ──────────────────────────────────────────────────────

    def get_stream_status(self) -> dict[str, Any]:
        connected = bool(self.twitch and self.twitch.is_connected())
        return {
            "stream_started": self.stream_started,
            "connected": connected,
            "channel": self.config.twitch_channel if self.config else "",
            "reply_mode": self.config.twitch_reply_mode if self.config else "mention",
            "authenticated": bool(self.twitch and self.twitch.authenticated),
        }

    def start_stream(self) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        if self.stream_started:
            return {"ok": False, "msg": "Stream is already connected."}
        if not self.config.twitch_channel:
            return {"ok": False, "msg": "Set TWITCH_CHANNEL in your .env first."}
        try:
            self.twitch = TwitchClient(
                channel=self.config.twitch_channel,
                on_message=self._on_twitch_message,
                bot_username=self.config.twitch_bot_username,
                oauth_token=self.config.twitch_oauth_token,
                on_status=lambda msg: self._push_chat("Twitch", msg, "system"),
            )
            self.twitch.start()
            self.stream_started = True
            if (
                self._stream_responder_thread is None
                or not self._stream_responder_thread.is_alive()
            ):
                self._stream_responder_thread = threading.Thread(
                    target=self._stream_responder, daemon=True, name="NovaAIStreamResponder"
                )
                self._stream_responder_thread.start()
            self._start_alert_sources()
            self._push_state()
            return {"ok": True, "msg": f"Connecting to #{self.config.twitch_channel}..."}
        except Exception as exc:
            self.stream_started = False
            return {"ok": False, "msg": str(exc)}

    def _start_alert_sources(self) -> None:
        """Connect Streamlabs / StreamElements if tokens are configured."""
        from . import stream_sources

        self._stop_alert_sources()
        cfg = self.config
        on_status = lambda msg: self._push_chat("Alerts", msg, "system")
        specs = [
            (stream_sources.StreamlabsSource, getattr(cfg, "streamlabs_socket_token", None)),
            (stream_sources.StreamElementsSource, getattr(cfg, "streamelements_jwt_token", None)),
        ]
        for cls, token in specs:
            if not token:
                continue
            try:
                src = cls(token, self.handle_stream_event, on_status)
                if src.start():
                    self.alert_sources.append(src)
            except Exception as exc:
                on_status(f"{cls.name}: failed to start ({exc}).")

    def _stop_alert_sources(self) -> None:
        for src in self.alert_sources:
            try:
                src.stop()
            except Exception:
                pass
        self.alert_sources = []

    def stop_stream(self) -> dict[str, Any]:
        self.stream_started = False
        if self.twitch:
            try:
                self.twitch.stop()
            except Exception:
                pass
        self.twitch = None
        self._stop_alert_sources()
        self._push_state()
        return {"ok": True, "msg": "Stream disconnected."}

    def _on_twitch_message(self, username: str, text: str, roles: set[str] | None = None) -> None:
        roles = roles or set()
        # Show the raw chat line in the Stream feed (the streamer sees all chat).
        payload = json.dumps({"username": username, "text": text})
        self._js(f"window.__onStreamMessage({payload})")
        # Only reply when the chatter's role is allowed AND the reply-mode matches.
        if self._role_allowed(roles) and self._should_reply_to(text):
            try:
                self._stream_queue.put_nowait((username, text))
            except queue.Full:
                pass

    def _role_allowed(self, roles: set[str]) -> bool:
        """Gate replies by chatter role per twitch_allowed_roles."""
        mode = getattr(self.config, "twitch_allowed_roles", "everyone") if self.config else "everyone"
        if mode == "everyone":
            return True
        if mode == "moderators":
            return bool(roles & {"moderator", "broadcaster"})
        if mode == "subscribers":
            return bool(roles & {"subscriber", "vip", "moderator", "broadcaster"})
        return True

    def _should_reply_to(self, text: str) -> bool:
        cfg = self.config
        if not cfg:
            return False
        mode = cfg.twitch_reply_mode
        lowered = text.lower()
        if mode == "all":
            return True
        if mode == "command":
            return lowered.startswith("!ask")
        # default: mention
        names = [cfg.twitch_bot_username]
        if self.profile:
            names.append(str(self.profile.get("companion_name", "")).lower())
        return any(name and name in lowered for name in names)

    def _stream_responder(self) -> None:
        while self.stream_started:
            try:
                username, text = self._stream_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            now = time.time()
            if now - self._last_stream_reply < self.config.twitch_reply_cooldown_seconds:
                continue
            if self.busy:
                continue
            self._last_stream_reply = now
            if not self._acquire():
                continue
            try:
                self._stream_pipeline(username, text)
            except Exception:
                pass
            finally:
                self._release()

    def _stream_pipeline(self, username: str, text: str) -> None:
        companion = self.profile.get("companion_name", "NovaAI")
        # Strip a leading !ask command if present.
        clean = text[4:].strip() if text.lower().startswith("!ask") else text
        framing = (
            "You are live on Twitch responding to chat. Keep replies short, punchy, and "
            "in-character. Address the chatter by name when natural. Do not read out URLs."
        )
        extra = [framing] + self._recall(clean)
        result = generate_reply(
            GenerationRequest(
                user_text=clean,
                profile=self.profile,
                config=self.config,
                source="twitch",
                speaker_label=f"<twitch:{username}>",
                extra_system=extra,
                use_shared_history=True,
            )
        )
        reply = result.reply
        append_history("user", f"[twitch:{username}] {clean}")
        append_history("assistant", reply)
        self._push_chat(companion, reply, "assistant")
        self._remember_exchange(f"twitch:{username}", clean, reply, source="twitch")
        # Optionally echo the reply back into Twitch chat if authenticated.
        if self.twitch and self.twitch.authenticated:
            self.twitch.send_message(reply)
        if self.state.voice_enabled and not self._stopped():
            self._speak(reply, result.emotion)

    # ── avatar ──────────────────────────────────────────────────────────────────

    def _avatar_profile_block(self) -> dict[str, Any]:
        details = self.profile.get("profile_details")
        if isinstance(details, dict) and isinstance(details.get("avatar"), dict):
            return details["avatar"]
        return {}

    def _start_avatar_if_enabled(self) -> None:
        if self.avatar is not None:
            return
        if not self._avatar_profile_block().get("enabled"):
            return
        try:
            self.avatar = AvatarBridge(on_vrm_loaded=self._on_vrm_uploaded)
            self.avatar.start()
            last = self._avatar_profile_block().get("last_loaded_vrm_path") or ""
            if last:
                self.avatar.publish_avatar(last)
        except Exception as exc:
            self.avatar = None
            self._push_chat("System", f"Avatar bridge failed to start: {exc}", "system")

    def _on_vrm_uploaded(self, path: Path) -> None:
        url = f"/uploads/{path.name}"
        block = self._avatar_profile_block()
        if block:
            block["last_loaded_vrm_path"] = url
            block["vrm_path"] = str(path)
            try:
                self.profile = save_profile_by_id(self.active_profile_id, self.profile)
            except Exception:
                pass
        if self.avatar:
            self.avatar.publish_avatar(url)

    def _amplitude_cb(self):
        def cb(level: float) -> None:
            if self.avatar is None:
                return
            now = time.time()
            if level > 0 and now - self._last_amplitude_emit < 0.04:
                return
            self._last_amplitude_emit = now
            try:
                self.avatar.publish_viseme(level)
            except Exception:
                pass
        return cb

    def _speak(self, text: str, emotion: str = "neutral") -> None:
        """Speak text via TTS, driving avatar emotion + lip-sync if present."""
        # Where the spoken reply plays: server "speaker", the "browser" (avatar
        # overlay does its own playback + lip-sync), or "both".
        out = getattr(self.config, "audio_output", "speaker")
        to_browser = out in ("browser", "both") and self.avatar is not None
        # Speaker plays when selected, OR as a fallback when "browser" is chosen
        # but no avatar overlay is running (so a reply is never silently dropped).
        to_speaker = out in ("speaker", "both") or (out == "browser" and self.avatar is None)
        # In speaker mode the server playback blocks, so it owns the speaking
        # window (start now / stop in finally). In browser-only mode the overlay
        # plays the audio itself and manages speaking + lip-sync from the 'tts'
        # message, so we don't open/close the window here.
        if self.avatar is not None and to_speaker:
            try:
                self.avatar.publish_speaking(True, emotion)
            except Exception:
                pass
        cb = self._amplitude_cb() if (self.avatar is not None and to_speaker) else None
        try:
            audio_path = speak_text(text, self.config, self.state, on_amplitude=cb)
            if to_browser and not self._stopped():
                # Cache-bust so the browser fetches this reply, not the previous one.
                self.avatar.publish_tts(f"/tts-audio?t={int(time.time() * 1000)}", emotion)
            if to_speaker and should_play_audio_after_synthesis(self.config) and not self._stopped():
                play_audio_file(audio_path, self.config.speaker_device_index, on_amplitude=cb)
        except Exception:
            pass
        finally:
            if self.avatar is not None and to_speaker:
                try:
                    self.avatar.publish_viseme(0.0)
                    self.avatar.publish_speaking(False, emotion)
                except Exception:
                    pass

    def get_avatar_status(self) -> dict[str, Any]:
        block = self._avatar_profile_block()
        return {
            "enabled": bool(block.get("enabled")),
            "running": self.avatar is not None,
            "url": self.avatar.get_frontend_url() if self.avatar else "",
            "last_vrm": block.get("last_loaded_vrm_path", ""),
            "lip_sync": bool(block.get("lip_sync", True)),
            "idle_motion": bool(block.get("idle_motion", True)),
            "transparent_bg": bool(block.get("transparent_bg", False)),
        }

    def start_avatar(self) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        block = self._avatar_profile_block()
        if not block:
            return {"ok": False, "msg": "Active profile has no avatar settings."}
        block["enabled"] = True
        try:
            self.profile = save_profile_by_id(self.active_profile_id, self.profile)
        except Exception:
            pass
        self._start_avatar_if_enabled()
        return {"ok": self.avatar is not None, "url": self.avatar.get_frontend_url() if self.avatar else ""}

    def stop_avatar(self) -> dict[str, Any]:
        block = self._avatar_profile_block()
        if block:
            block["enabled"] = False
            try:
                self.profile = save_profile_by_id(self.active_profile_id, self.profile)
            except Exception:
                pass
        # The bridge has no clean shutdown; leave the daemon threads but stop publishing.
        self.avatar = None
        return {"ok": True}

    def open_avatar_window(self) -> dict[str, Any]:
        if self.avatar is None:
            self._start_avatar_if_enabled()
        if self.avatar is None:
            return {"ok": False, "msg": "Enable the avatar first."}
        url = self.avatar.get_frontend_url()
        block = self._avatar_profile_block()
        path = "/?transparent=1" if block.get("transparent_bg") else "/"
        if block.get("transparent_bg"):
            url = url + "?transparent=1"
        # In headless web mode the browser opens the URL itself (built from its
        # own location, so it matches the LAN IP / Tailscale / tunnel host). Only
        # open server-side for the local desktop GUI.
        if _emit_js is None:
            try:
                import webbrowser

                webbrowser.open(url)
            except Exception:
                pass
        return {"ok": True, "url": url, "port": self.avatar.http_port, "path": path}

    def set_avatar_option(self, key: str, value: Any) -> dict[str, Any]:
        block = self._avatar_profile_block()
        if not block or key not in {"lip_sync", "idle_motion", "transparent_bg"}:
            return {"ok": False, "msg": "Unknown avatar option."}
        block[key] = bool(value)
        try:
            self.profile = save_profile_by_id(self.active_profile_id, self.profile)
        except Exception:
            pass
        return {"ok": True}

    def _avatar_dance(self, on: bool) -> None:
        if self.avatar is not None:
            try:
                self.avatar.publish_dance(on)
            except Exception:
                pass

    def set_dancing(self, on: bool) -> dict[str, Any]:
        self._avatar_dance(bool(on))
        return {"ok": True, "dancing": bool(on)}

    def test_avatar_emotion(self, emotion: str) -> dict[str, Any]:
        if self.avatar is None:
            return {"ok": False, "msg": "Avatar not running."}
        try:
            self.avatar.publish_state({"emotion": emotion, "danger": False})
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ── stream alerts (donations / follows / subs / raids …) ──────────────────────

    def _alerts_block(self) -> dict[str, Any]:
        details = self.profile.get("profile_details") if self.profile else None
        if isinstance(details, dict) and isinstance(details.get("alerts"), dict):
            return details["alerts"]
        return {}

    # Streaming platforms that the allow-list filters. Donations/tips (tagged
    # "streamlabs" or a payment provider like "paypal") are never filtered out.
    _FILTERABLE_PLATFORMS = {"twitch", "youtube", "facebook", "kick", "trovo"}

    def _platform_allowed(self, event: "stream_events.StreamEvent") -> bool:
        """Filter alerts by the configured streaming-platform allow-list.

        ``streamlabs_platforms`` is a comma-separated list (e.g. "twitch,kick").
        Blank = accept all platforms. Only platform-specific events (Twitch/
        YouTube/Facebook/Kick/Trovo) are filtered; donations and tips always
        pass so money is never silently dropped.
        """
        allow = getattr(self.config, "streamlabs_platforms", "") if self.config else ""
        plat = (event.platform or "").lower()
        if not allow or plat not in self._FILTERABLE_PLATFORMS:
            return True
        wanted = {p.strip() for p in allow.split(",") if p.strip()}
        return plat in wanted

    def handle_stream_event(self, event: "stream_events.StreamEvent") -> None:
        """React to one normalized stream event: expression + cute message + tally.

        Called from the webhook/socket source threads, so it never raises.
        """
        try:
            # Drop duplicate emissions (Streamlabs occasionally fires the same
            # event twice, and per-platform forwarding can echo it).
            if event.event_id:
                if event.event_id in self._seen_event_ids:
                    return
                self._seen_event_ids.append(event.event_id)

            # Platform filter: Streamlabs forwards events for EVERY linked
            # platform (Twitch/YouTube/Facebook/Kick/...). Honor the allow-list.
            if not self._platform_allowed(event):
                return

            block = self._alerts_block()
            if block and not block.get("enabled", True):
                return
            expr = event.expression(block.get("expressions") if block else None)
            message = stream_events.build_message(event, block.get("messages") if block else None)

            # Earnings ("stockings") tally for money events. Cheer amounts are
            # bits, and Twitch pays ~$1 per 100 bits, so convert to dollars.
            if event.type in stream_events.EARNING_EVENTS and event.amount > 0:
                money = event.amount / 100.0 if event.type == "cheer" else event.amount
                self._add_earnings(round(money, 2), event.currency, event.user, event.type)

            # Show it in the chat + stream feeds (tag the platform when known).
            label = event.type.capitalize()
            tag = f"{label} · {event.platform}" if event.platform else label
            self._push_chat("Alert", f"[{tag}] {event.user}", "system")
            companion = self.profile.get("companion_name", "NovaAI") if self.profile else "NovaAI"
            self._push_chat(companion, message, "assistant")

            # Drive the avatar expression even when speech is off.
            if self.avatar is not None:
                try:
                    self.avatar.publish_state({"emotion": expr, "danger": False})
                except Exception:
                    pass

            if (not block or block.get("speak", True)) and getattr(self.state, "voice_enabled", True):
                self._speak(message, expr)
        except Exception:
            pass

    def ingest_stream_event(self, payload: dict[str, Any], source: str = "webhook") -> dict[str, Any]:
        """Entry point for the /webhook/stream endpoint and external sources."""
        src = (source or "webhook").lower()
        events: list = []
        try:
            if src == "streamlabs":
                events = stream_events.from_streamlabs(payload)
            elif src in {"streamelements", "se"}:
                ev = stream_events.from_streamelements(payload)
                events = [ev] if ev else []
            elif src in {"twitch", "eventsub"}:
                ev = stream_events.from_twitch_eventsub(payload)
                events = [ev] if ev else []
            else:
                ev = stream_events.from_generic(payload)
                events = [ev] if ev else []
        except Exception:
            events = []
        if not events:
            return {"ok": False, "msg": "No recognizable event in payload."}
        for ev in events:
            self.handle_stream_event(ev)
        return {"ok": True, "count": len(events)}

    def simulate_stream_event(
        self, etype: str, user: str = "TestUser", amount: float = 0.0, months: int = 0
    ) -> dict[str, Any]:
        """Fire a fake event from the dashboard so reactions can be tested."""
        ev = stream_events.from_generic(
            {"type": etype, "user": user, "amount": amount, "months": months, "source": "manual"}
        )
        if not ev:
            return {"ok": False, "msg": f"Unknown event type: {etype}"}
        self.handle_stream_event(ev)
        return {"ok": True}

    # ── earnings ("stockings") tracker ────────────────────────────────────────────

    def _earnings_store(self) -> dict[str, Any]:
        from . import database
        try:
            return json.loads(database.get_state("earnings", "{}") or "{}")
        except Exception:
            return {}

    def _save_earnings_store(self, data: dict[str, Any]) -> None:
        from . import database
        try:
            database.set_state("earnings", json.dumps(data))
        except Exception:
            pass

    def _add_earnings(self, amount: float, currency: str, user: str, etype: str) -> None:
        from datetime import datetime
        data = self._earnings_store()
        today = datetime.now().strftime("%Y-%m-%d")
        if data.get("today_date") != today:
            data["today_date"] = today
            data["today"] = 0.0
        data["all_time"] = round(float(data.get("all_time", 0.0)) + amount, 2)
        data["today"] = round(float(data.get("today", 0.0)) + amount, 2)
        data["count"] = int(data.get("count", 0)) + 1
        data["currency"] = currency or data.get("currency", "USD")
        data["last"] = {"user": user, "amount": amount, "type": etype}
        # In-memory session total (resets when the app restarts).
        self._session_earnings = round(getattr(self, "_session_earnings", 0.0) + amount, 2)
        self._save_earnings_store(data)
        # Nudge any open overlay to refresh promptly.
        try:
            self._js("window.__onEarnings && window.__onEarnings()")
        except Exception:
            pass

    def get_earnings(self) -> dict[str, Any]:
        data = self._earnings_store()
        return {
            "all_time": round(float(data.get("all_time", 0.0)), 2),
            "today": round(float(data.get("today", 0.0)), 2),
            "session": round(getattr(self, "_session_earnings", 0.0), 2),
            "count": int(data.get("count", 0)),
            "currency": data.get("currency", "USD"),
            "last": data.get("last", {}),
        }

    def reset_earnings(self, scope: str = "all") -> dict[str, Any]:
        data = self._earnings_store()
        if scope == "today":
            data["today"] = 0.0
        elif scope == "session":
            self._session_earnings = 0.0
        else:
            data = {}
            self._session_earnings = 0.0
        self._save_earnings_store(data)
        return {"ok": True, **self.get_earnings()}

    # ── MMD dances ────────────────────────────────────────────────────────────────
    # Each dance is ONE bundle (a "set"): a .vmd motion + optional song + optional
    # .vmd camera, stored together under data/mmd/sets/<id>/ and listed as one row.

    _MMD_SETS_DIR = MMD_DIR / "sets"
    _MMD_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a"}

    @staticmethod
    def _mmd_safe_id(value: str) -> str:
        import re
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", str(value or "")).strip("._")
        return safe or "dance"

    def _mmd_dedupe_id(self, base: str) -> str:
        sid = base
        n = 2
        while (self._MMD_SETS_DIR / sid).exists():
            sid = f"{base}-{n}"
            n += 1
        return sid

    def _mmd_set_files(self, set_dir: Path) -> dict[str, str]:
        """Return {motion, song, camera} filenames present in a set folder."""
        files = {"motion": "", "song": "", "camera": ""}
        if (set_dir / "motion.vmd").is_file():
            files["motion"] = "motion.vmd"
        if (set_dir / "camera.vmd").is_file():
            files["camera"] = "camera.vmd"
        for p in set_dir.glob("song.*"):
            if p.suffix.lower() in self._MMD_AUDIO_EXTS:
                files["song"] = p.name
                break
        return files

    def create_mmd_set(self, name: str) -> dict[str, Any]:
        """Create an empty dance set; files are uploaded into it next."""
        display = str(name or "").strip() or "Dance"
        sid = self._mmd_dedupe_id(self._mmd_safe_id(display))
        set_dir = self._MMD_SETS_DIR / sid
        set_dir.mkdir(parents=True, exist_ok=True)
        (set_dir / "meta.json").write_text(json.dumps({"name": display}), encoding="utf-8")
        return {"ok": True, "id": sid}

    def upload_mmd_file(self, set_id: str, kind: str, filename: str, data_b64: str) -> dict[str, Any]:
        """Add a motion/song/camera file to an existing dance set."""
        kind = str(kind).lower()
        if kind not in {"motion", "song", "camera"}:
            return {"ok": False, "msg": f"Unknown kind: {kind}"}
        set_dir = self._MMD_SETS_DIR / self._mmd_safe_id(set_id)
        if not set_dir.is_dir():
            return {"ok": False, "msg": "Dance set not found."}
        ext = Path(str(filename)).suffix.lower()
        if kind in {"motion", "camera"} and ext != ".vmd":
            return {"ok": False, "msg": f"{kind} must be a .vmd file."}
        if kind == "song" and ext not in self._MMD_AUDIO_EXTS:
            return {"ok": False, "msg": "song must be .mp3/.wav/.ogg/.m4a."}
        try:
            raw = base64.b64decode((data_b64 or "").split(",")[-1])
        except Exception:
            return {"ok": False, "msg": "Invalid file data."}
        if not raw:
            return {"ok": False, "msg": "Empty file."}
        target = set_dir / ("motion.vmd" if kind == "motion"
                            else "camera.vmd" if kind == "camera"
                            else f"song{ext}")
        target.write_bytes(raw)
        return {"ok": True}

    def list_mmd_sets(self) -> list[dict[str, Any]]:
        sets: list[dict[str, Any]] = []
        if self._MMD_SETS_DIR.is_dir():
            for set_dir in sorted(self._MMD_SETS_DIR.iterdir()):
                if not set_dir.is_dir():
                    continue
                name = set_dir.name
                try:
                    meta = json.loads((set_dir / "meta.json").read_text(encoding="utf-8"))
                    name = str(meta.get("name", name))
                except Exception:
                    pass
                files = self._mmd_set_files(set_dir)
                sets.append({
                    "id": set_dir.name,
                    "name": name,
                    "has_motion": bool(files["motion"]),
                    "has_song": bool(files["song"]),
                    "has_camera": bool(files["camera"]),
                })
        return sets

    def delete_mmd_set(self, set_id: str) -> dict[str, Any]:
        import shutil
        set_dir = self._MMD_SETS_DIR / self._mmd_safe_id(set_id)
        try:
            if set_dir.is_dir():
                shutil.rmtree(set_dir)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def play_mmd_set(self, set_id: str, loop: bool = False) -> dict[str, Any]:
        """Play a whole dance set (motion + its song + its camera) on the avatar."""
        if self.avatar is None:
            return {"ok": False, "msg": "Start the avatar first."}
        sid = self._mmd_safe_id(set_id)
        set_dir = self._MMD_SETS_DIR / sid
        files = self._mmd_set_files(set_dir)
        if not files["motion"]:
            return {"ok": False, "msg": "This dance has no motion (.vmd)."}
        def _url(fname: str) -> str:
            return f"/mmd/sets/{sid}/{fname}" if fname else ""
        try:
            self.avatar.publish_mmd(
                _url(files["motion"]), _url(files["song"]), _url(files["camera"]), bool(loop)
            )
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def stop_mmd(self) -> dict[str, Any]:
        if self.avatar is None:
            return {"ok": False, "msg": "Avatar not running."}
        try:
            self.avatar.publish_mmd_stop()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ── game agent ────────────────────────────────────────────────────────────

    def _game_narrate(self, text: str, emotion: str = "neutral") -> None:
        companion = self.profile.get("companion_name", "NovaAI")
        self._push_chat(companion, text, "assistant")
        # Mirror the thought to the game bridge's Live View dashboard.
        drv = getattr(self.game_agent, "driver", None) if self.game_agent else None
        if drv is not None and hasattr(drv, "push_thought"):
            try:
                drv.push_thought(text)
            except Exception:
                pass
        # Echo to Twitch chat if connected + authenticated.
        if self.twitch and self.twitch.authenticated:
            try:
                self.twitch.send_message(text)
            except Exception:
                pass
        # Speak only when not busy with a chat/stream turn (don't block them).
        if self.state.voice_enabled:
            if self._acquire():
                try:
                    self._speak(text, emotion)
                finally:
                    self._release()

    def _game_update(self, raw: dict[str, Any]) -> None:
        try:
            self._js(f"window.__onGameUpdate({json.dumps(raw)})")
        except Exception:
            pass

    def _game_remember(self, content: str) -> None:
        if self.memory and self.config and self.config.rag_enabled:
            try:
                self.memory.remember(self.active_profile_id, content, source="game", speaker="game")
            except Exception:
                pass

    def _game_running(self) -> bool:
        return bool(self.game_agent and self.game_agent.is_running())

    def _game_awareness(self) -> list[str]:
        """Tell the chat persona it currently controls an in-game body."""
        if not self._game_running():
            return []
        driver = getattr(self.game_agent, "driver", None)
        game = getattr(driver, "name", "a game")
        return [
            f"You are RIGHT NOW controlling a character in {game} — you CAN move, "
            "fight, mine, build, eat, and act in the world through your game body. "
            "Never say you have no controls or can't fight/move. If the user tells you "
            "to do something in-game (fight back, defend, build, mine, follow, come, "
            "etc.), confirm you're doing it; the action is carried out by your game agent."
        ]

    # Phrases that mean "do this with your in-game body".
    _COMBAT_TRIGGERS = (
        "under attack", "being attacked", "attacked by", "attacking you", "attacking us",
        "fight back", "hit them", "hit him", "hit her", "hit back", "smack",
        "defend", "protect me", "protect us", "kill them", "kill him", "kill her",
        "punch", "they're hitting", "stop them", "fend them", "fight them",
    )
    _COMMAND_TRIGGERS = (
        "build", "mine", "dig", "chop", "gather", "farm", "plant", "harvest",
        "follow me", "come here", "come to me", "bring me", "find", "explore",
        "craft", "smelt", "cook", "fish", "hunt", "breed", "store", "go to",
        "make a", "make me", "place", "trade", "sleep", "equip", "collect", "kill",
        "attack",
    )

    def _maybe_handle_game_command(self, user_text: str) -> str | None:
        if not self._game_running():
            return None
        lower = f" {user_text.lower().strip()} "
        # Punish a named player -> punch them (pass the literal order so the agent
        # punches the right target).
        if "smack" in lower or "punch" in lower:
            self.game_agent.set_goal(user_text.strip())
            return f"On it — {user_text.strip()} 😤"
        if any(k in lower for k in self._COMBAT_TRIGGERS):
            self.game_agent.set_goal(
                "You are under attack by a player or mob. FIGHT BACK now: equip your "
                "best weapon and armor, then use the 'retaliate' verb to hit the "
                "attacker (nearest non-owner player, else hostiles) repeatedly until "
                "they stop. Eat to heal if low, and stay alive. Keep retaliating."
            )
            return "On it — fighting back! Equipping a weapon and hitting them until they stop."
        if any(k in lower for k in self._COMMAND_TRIGGERS):
            self.game_agent.set_goal(user_text.strip())
            return f"Got it — doing that in-game now: {user_text.strip()}"
        return None

    # ── general settings (Settings panel) ───────────────────────────────────────

    def _ollama_base(self) -> str:
        url = (self.config.llm_api_url if self.config else "") or ""
        # OLLAMA_API_URL env wins for the local daemon base.
        env_url = os.environ.get("OLLAMA_API_URL", "")
        for candidate in (env_url, url, "http://127.0.0.1:11434/api/chat"):
            if candidate and "/api/" in candidate:
                return candidate.split("/api/")[0].rstrip("/")
        return "http://127.0.0.1:11434"

    def _reresolve_llm_url(self) -> None:
        """Recompute llm_api_url after a provider/url change."""
        from .config import resolve_llm_api_url

        provider = self.config.llm_provider
        if provider == "ollama":
            raw = os.environ.get("OLLAMA_API_URL") or "http://127.0.0.1:11434/api/chat"
        elif provider == "openai":
            raw = self.config.llm_api_url or os.environ.get("OPENAI_API_URL")
        else:
            raw = None
        self.config.llm_api_url = resolve_llm_api_url(provider, raw)

    # ── persisted UI prefs (voice/input toggles + media) ──────────────────────────

    def _ui_prefs(self) -> dict[str, Any]:
        from . import database
        try:
            return json.loads(database.get_state("ui_prefs", "{}") or "{}")
        except Exception:
            return {}

    def _save_ui_pref(self, key: str, value: Any) -> None:
        from . import database
        try:
            prefs = self._ui_prefs()
            prefs[key] = value
            database.set_state("ui_prefs", json.dumps(prefs))
        except Exception:
            pass

    def _apply_saved_ui_prefs(self) -> None:
        """Restore the Voice & Input toggles + Media toggle from last session."""
        prefs = self._ui_prefs()
        if "voice_enabled" in prefs:
            self.state.voice_enabled = bool(prefs["voice_enabled"])
            if self.config:
                self.config.voice_enabled = self.state.voice_enabled
        if "hands_free" in prefs:
            self.hands_free_enabled = bool(prefs["hands_free"])
            if self.config:
                self.config.input_mode = "voice" if self.hands_free_enabled else "text"
        if "mic_muted" in prefs:
            self.mic_muted = bool(prefs["mic_muted"])
        if self.config and "web_search" in prefs:
            self.config.web_browsing_enabled = bool(prefs["web_search"])
        if self.config and "web_auto_search" in prefs:
            self.config.web_auto_search = bool(prefs["web_auto_search"])
        if "media_enabled" in prefs:
            self.media_enabled = bool(prefs["media_enabled"])

    def _apply_saved_app_settings(self) -> None:
        if not self.config:
            return
        try:
            from . import database

            store = json.loads(database.get_state("app_settings", "{}") or "{}")
        except Exception:
            return
        for key, val in store.items():
            ftype = _APP_FIELD_TYPES.get(key)
            if ftype is not None:
                try:
                    setattr(self.config, key, _coerce_game_setting(val, ftype))
                except Exception:
                    pass
        self._reresolve_llm_url()

    def restart_app(self) -> dict[str, Any]:
        """Relaunch NovaAI (applies any settings/code changes cleanly)."""
        def _do_restart() -> None:
            time.sleep(0.4)
            # Stop game/stream/avatar cleanly so ports free up before relaunch.
            try:
                if self.game_agent:
                    self.game_agent.stop()
            except Exception:
                pass
            try:
                if self.twitch:
                    self.twitch.stop()
            except Exception:
                pass
            try:
                cwd = str(Path(__file__).resolve().parent.parent)
                subprocess.Popen([sys.executable] + sys.argv, cwd=cwd)
            except Exception:
                pass
            os._exit(0)

        threading.Thread(target=_do_restart, daemon=True).start()
        return {"ok": True, "msg": "Restarting NovaAI..."}

    def get_app_settings(self) -> dict[str, Any]:
        sections: dict[str, Any] = {}
        for name, meta in APP_SETTINGS_SCHEMA.items():
            fields = []
            for f in meta["fields"]:
                val = getattr(self.config, f["key"], "") if self.config else ""
                if val is None:
                    val = ""
                fields.append({**f, "value": val})
            sections[name] = {"label": meta["label"], "fields": fields}
        return {"sections": sections}

    def save_app_settings(self, section: str, values: dict[str, Any]) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        meta = APP_SETTINGS_SCHEMA.get(section)
        if not meta:
            return {"ok": False, "msg": f"Unknown section: {section}"}
        applied: dict[str, Any] = {}
        for f in meta["fields"]:
            if f["key"] in (values or {}):
                coerced = _coerce_game_setting(values[f["key"]], f["type"])
                if f["key"] == "streamlabs_platforms":
                    from .config import normalize_streamlabs_platforms
                    coerced = normalize_streamlabs_platforms(coerced)
                setattr(self.config, f["key"], coerced)
                applied[f["key"]] = list(coerced) if isinstance(coerced, tuple) else coerced
        if section == "llm":
            self._reresolve_llm_url()
            if self.memory:
                self.memory.config = self.config  # pick up new embedding settings
        if section == "alerts":
            # (Re)connect Streamlabs/StreamElements with the new tokens right
            # away — alerts are independent of the Twitch chat connection.
            self._start_alert_sources()
        try:
            from . import database

            store = json.loads(database.get_state("app_settings", "{}") or "{}")
            store.update(applied)
            database.set_state("app_settings", json.dumps(store))
        except Exception:
            pass
        self._push_state()
        msg = "Settings saved."
        if section == "alerts":
            from . import stream_sources
            has_token = bool(
                getattr(self.config, "streamlabs_socket_token", None)
                or getattr(self.config, "streamelements_jwt_token", None)
            )
            if has_token and not stream_sources.available():
                msg = ("Settings saved, but python-socketio is missing — run "
                       "'pip install -r requirements-streaming.txt' to enable live alerts.")
            elif self.alert_sources:
                names = ", ".join(getattr(s, "name", "?") for s in self.alert_sources)
                msg = f"Settings saved. Connecting alerts: {names}…"
        return {"ok": True, "msg": msg}

    # ── model auto-detect ───────────────────────────────────────────────────────

    _VISION_HINTS = ("llava", "moondream", "vision", "bakllava", "minicpm-v",
                     "qwen2-vl", "qwen2.5vl", "janus", "llama3.2-vision")
    _EMBED_HINTS = ("embed", "bge-", "bge:", "nomic-embed", "all-minilm", "minilm",
                    "gte-", "e5-", "mxbai-embed", "snowflake-arctic-embed", "embeddinggemma")

    @classmethod
    def _categorize_model(cls, name: str) -> str:
        ln = name.lower()
        if any(h in ln for h in cls._EMBED_HINTS) or "embedding" in ln:
            return "embedding"
        if any(h in ln for h in cls._VISION_HINTS):
            return "vision"
        return "chat"

    def _ollama_tags(self) -> list[str]:
        try:
            resp = requests.get(self._ollama_base() + "/api/tags", timeout=5)
            resp.raise_for_status()
            return [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
        except Exception:
            return []

    def _openai_models(self) -> list[str]:
        """List models from the configured OpenAI-compatible / LiteLLM endpoint.

        Works whenever an API URL is set (e.g. a LiteLLM gateway), independent of
        the active provider, so the dropdowns can always show what's available.
        """
        if not self.config:
            return []
        raw = (
            os.environ.get("LLM_API_URL")
            or os.environ.get("OPENAI_API_URL")
            or (self.config.llm_api_url if self.config.llm_provider == "openai" else "")
        )
        if not raw or not raw.startswith("http"):
            return []
        base = raw.split("/chat/completions")[0].rstrip("/")
        url = base + "/models" if base.endswith("/v1") else base + "/v1/models"
        headers = {}
        key = self.config.llm_api_key or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", data if isinstance(data, list) else [])
            return [m.get("id", "") for m in items if isinstance(m, dict) and m.get("id")]
        except Exception:
            return []

    def get_models(self) -> dict[str, Any]:
        """Auto-detect available models live, grouped chat/vision/embedding.

        Always queries the API(s) fresh so newly-added models show up: the local
        Ollama daemon AND any configured OpenAI/LiteLLM gateway.
        """
        buckets: dict[str, set] = {"chat": set(), "vision": set(), "embedding": set()}
        for name in self._ollama_tags():
            buckets[self._categorize_model(name)].add(name)
        for name in self._openai_models():          # LiteLLM/OpenAI, if URL set
            buckets[self._categorize_model(name)].add(name)
        provider = self.config.llm_provider if self.config else "ollama"
        if provider == "claude-code":
            buckets["chat"].update(["sonnet", "opus", "haiku"])
        elif provider == "codex":
            buckets["chat"].update(["gpt-5-codex", "gpt-5", "o4-mini"])
        return {
            "provider": provider,
            "chat": sorted(buckets["chat"]),
            "vision": sorted(buckets["vision"]),
            "embedding": sorted(buckets["embedding"]),
        }

    def _apply_saved_game_settings(self) -> None:
        """Apply game settings saved from the panel (override .env)."""
        if not self.config:
            return
        try:
            from . import database

            store = json.loads(database.get_state("game_settings", "{}") or "{}")
        except Exception:
            return
        for key, val in store.items():
            if key == "game_driver":
                self.config.game_driver = str(val)
                continue
            ftype = _GAME_FIELD_TYPES.get(key)
            if ftype is not None:
                try:
                    setattr(self.config, key, _coerce_game_setting(val, ftype))
                except Exception:
                    pass

    def get_game_settings(self) -> dict[str, Any]:
        drivers: dict[str, Any] = {}
        for drv, meta in GAME_SETTINGS_SCHEMA.items():
            fields = []
            for f in meta["fields"]:
                val = getattr(self.config, f["key"], "") if self.config else ""
                if f["type"] == "list":
                    val = ", ".join(val) if isinstance(val, (list, tuple)) else (val or "")
                if val is None:
                    val = ""
                fields.append({**f, "value": val})
            drivers[drv] = {"label": meta["label"], "preview": meta["preview"], "fields": fields}
        return {
            "drivers": drivers,
            "current": self.config.game_driver if self.config else "minecraft",
        }

    def save_game_settings(self, driver: str, values: dict[str, Any]) -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        meta = GAME_SETTINGS_SCHEMA.get(driver)
        if not meta:
            return {"ok": False, "msg": f"Unknown driver: {driver}"}
        applied: dict[str, Any] = {}
        for f in meta["fields"]:
            if f["key"] in (values or {}):
                coerced = _coerce_game_setting(values[f["key"]], f["type"])
                setattr(self.config, f["key"], coerced)
                applied[f["key"]] = list(coerced) if isinstance(coerced, tuple) else coerced
        self.config.game_driver = driver
        try:
            from . import database

            store = json.loads(database.get_state("game_settings", "{}") or "{}")
            store.update(applied)
            store["game_driver"] = driver
            database.set_state("game_settings", json.dumps(store))
        except Exception:
            pass
        return {"ok": True, "msg": "Game settings saved."}

    def get_game_status(self) -> dict[str, Any]:
        running = bool(self.game_agent and self.game_agent.is_running())
        viewer_url = ""
        # Report the actually-running driver when there is one, else the configured
        # default — otherwise the panel always snaps back to the .env default.
        driver = getattr(self, "game_driver_key", None) or (
            self.config.game_driver if self.config else "minecraft"
        )
        if running and self.game_agent is not None:
            drv = getattr(self.game_agent, "driver", None)
            if drv is not None and hasattr(drv, "viewer_url"):
                try:
                    viewer_url = drv.viewer_url()
                except Exception:
                    viewer_url = ""
        return {
            "running": running,
            "driver": driver,
            "goal": self.game_agent.goal if self.game_agent else "",
            "viewer_url": viewer_url,
            "viewer_port": self.config.mc_viewer_port if self.config else None,
        }

    def open_game_view(self) -> dict[str, Any]:
        status = self.get_game_status()
        url = status.get("viewer_url")
        if not url:
            return {"ok": False, "msg": "Live view is only available while a Minecraft game is running."}
        # In headless web mode the browser opens the URL itself (built from its
        # own location, so it matches the LAN IP / Tailscale / tunnel host). Only
        # open server-side for the local desktop GUI.
        if _emit_js is None:
            try:
                import webbrowser

                webbrowser.open(url)
            except Exception:
                pass
        return {"ok": True, "url": url, "port": status.get("viewer_port")}

    def _build_game_driver(self, driver_name: str):
        if driver_name == "minecraft":
            from .games.minecraft import MinecraftDriver

            return MinecraftDriver(
                self.config,
                on_log=lambda line: self._push_chat("Minecraft", line, "system"),
            )
        if driver_name == "universal":
            from .games.universal import UniversalGameDriver

            return UniversalGameDriver(self.config, game_name=self.config.game_universal_name)
        if driver_name == "osu":
            from .games.osu import OsuDriver

            return OsuDriver(self.config)
        if driver_name == "factorio":
            from .games.factorio import FactorioDriver

            return FactorioDriver(self.config)
        if driver_name == "vrchat":
            from .games.vrchat import VRChatDriver

            return VRChatDriver(self.config)
        return None

    def start_game(self, goal: str = "", driver: str = "") -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        driver_name = (driver or self.config.game_driver or "minecraft").strip().lower()
        # If a game is already running, stop it first so switching drivers works
        # (otherwise the old game just keeps running).
        if self.game_agent and self.game_agent.is_running():
            if getattr(self, "game_driver_key", None) == driver_name:
                return {"ok": False, "msg": f"{driver_name} is already running."}
            self.stop_game()
            time.sleep(0.5)
        try:
            from .games.agent import GameAgent

            game_driver = self._build_game_driver(driver_name)
            if game_driver is None:
                return {"ok": False, "msg": f"Unknown game driver: {driver_name}"}
            # Remember + persist the chosen driver so status/UI reflect reality.
            self.game_driver_key = driver_name
            self.config.game_driver = driver_name
            try:
                from . import database

                store = json.loads(database.get_state("game_settings", "{}") or "{}")
                store["game_driver"] = driver_name
                database.set_state("game_settings", json.dumps(store))
            except Exception:
                pass
            if driver_name == "osu" and not self.config.osu_allow_online:
                self._push_chat(
                    "System",
                    "osu! automation on official servers is bannable. Running in "
                    "OFFLINE/solo mode only. Use at your own risk.",
                    "system",
                )

            default_goal = "explore and survive"
            if hasattr(game_driver, "default_goal"):
                try:
                    default_goal = game_driver.default_goal()
                except Exception:
                    pass
            self.game_agent = GameAgent(
                driver=game_driver,
                config=self.config,
                profile_getter=lambda: self.profile,
                narrate=self._game_narrate,
                on_update=self._game_update,
                remember=self._game_remember,
                tick_seconds=self.config.game_tick_seconds,
                goal=(goal.strip() or default_goal),
            )
            self.game_agent.start()
            return {"ok": True, "msg": "Game agent started."}
        except Exception as exc:
            self.game_agent = None
            return {"ok": False, "msg": str(exc)}

    def stop_game(self) -> dict[str, Any]:
        agent = self.game_agent
        # Drop the reference first so status flips to stopped immediately; the
        # daemon thread unwinds on its own (stop() also aborts the bridge).
        self.game_agent = None
        self.game_driver_key = None
        if agent:
            try:
                agent.stop()
            except Exception:
                pass
        self._avatar_dance(False)
        return {"ok": True, "msg": "Game agent stopped."}

    def set_game_goal(self, goal: str) -> dict[str, Any]:
        if not self.game_agent:
            return {"ok": False, "msg": "Game agent is not running."}
        self.game_agent.set_goal(goal)
        return {"ok": True}

    # ── singing ─────────────────────────────────────────────────────────────────

    def get_singing_status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.config.singing_enabled) if self.config else False,
            "backend": self.config.singing_backend if self.config else "cloud",
        }

    def sing(self, lyrics: str, melody_ref: str = "") -> dict[str, Any]:
        if (err := self._not_ready()):
            return err
        if not self.config.singing_enabled:
            return {"ok": False, "msg": "Singing is disabled. Set SINGING_ENABLED=true in .env."}
        if not lyrics or not lyrics.strip():
            return {"ok": False, "msg": "Give me some lyrics to sing."}

        def _job() -> None:
            if not self._acquire():
                return
            try:
                from .singing import make_singing_engine

                self._push_status("Composing a song...")
                engine = make_singing_engine(self.config)
                path = engine.sing(lyrics.strip(), melody_ref.strip() or None)
                out = getattr(self.config, "audio_output", "speaker")
                to_browser = out in ("browser", "both") and self.avatar is not None
                to_speaker = out in ("speaker", "both") or (out == "browser" and self.avatar is None)
                if self.avatar is not None and to_speaker:
                    try:
                        self.avatar.publish_speaking(True, "happy")
                    except Exception:
                        pass
                self._avatar_dance(True)
                self._push_status("Singing...")
                if to_browser:
                    # The overlay plays the song (and lip-syncs to it).
                    self.avatar.serve_audio(path)
                    self.avatar.publish_audio(
                        f"/browser-audio?t={int(time.time() * 1000)}", kind="singing",
                        emotion="happy", lipsync=True,
                    )
                if to_speaker:
                    cb = self._amplitude_cb() if self.avatar is not None else None
                    play_audio_file(path, self.config.speaker_device_index, on_amplitude=cb)
                elif to_browser:
                    # Browser plays async — keep dancing for ~the song's length.
                    try:
                        from .tts import _decode_audio_mono
                        from pathlib import Path as _P
                        samples, sr = _decode_audio_mono(_P(path))
                        dur = (samples.size / sr) if (samples is not None and sr) else 0
                    except Exception:
                        dur = 0
                    waited = 0.0
                    while dur and waited < dur and not self._stopped():
                        time.sleep(0.25)
                        waited += 0.25
            except Exception as exc:
                self._push_chat("System", f"Singing failed: {exc}", "system")
            finally:
                self._avatar_dance(False)
                if self.avatar is not None:
                    try:
                        self.avatar.publish_viseme(0.0)
                        self.avatar.publish_speaking(False, "happy")
                    except Exception:
                        pass
                self._release()
                self._push_status("Ready.")

        threading.Thread(target=_job, daemon=True).start()
        return {"ok": True, "msg": "Singing..."}

    # ── reminders ─────────────────────────────────────────────────────────────

    def get_reminders(self) -> list[dict[str, Any]]:
        return list_reminders(self.profile)

    def add_reminder_item(self, text: str, time_str: str) -> dict[str, Any]:
        try:
            due_dt = _parse_any_datetime(time_str)
            if due_dt is None:
                return {"ok": False, "msg": f"Could not parse date/time: {time_str}"}
            add_reminder(self.profile, text, due_dt)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def delete_reminder_item(self, reminder_id: str) -> dict[str, Any]:
        try:
            delete_reminder_by_id(self.profile, reminder_id)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ── alarms ────────────────────────────────────────────────────────────────

    def get_alarms(self) -> list[dict[str, Any]]:
        return list_alarms(self.profile)

    def add_alarm_item(self, time_str: str, label: str) -> dict[str, Any]:
        try:
            normalized = _extract_time_str(time_str)
            if normalized is None:
                return {"ok": False, "msg": f"Could not parse time: {time_str}"}
            add_alarm(self.profile, normalized, label=label)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def cancel_alarm_item(self, alarm_id: str) -> dict[str, Any]:
        try:
            cancel_alarm_by_id(self.profile, alarm_id)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ── to-do ─────────────────────────────────────────────────────────────────

    def get_todos(self) -> list[dict[str, Any]]:
        return list_todos(self.profile)

    def add_todo_item(self, text: str) -> dict[str, Any]:
        try:
            add_todo(self.profile, text)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def toggle_todo_item(self, todo_id: str) -> dict[str, Any]:
        try:
            toggle_todo(self.profile, todo_id)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def delete_todo_item(self, todo_id: str) -> dict[str, Any]:
        try:
            delete_todo(self.profile, todo_id)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ── shopping ──────────────────────────────────────────────────────────────

    def get_shopping(self) -> list[dict[str, Any]]:
        return list_shopping(self.profile)

    def add_shopping(self, text: str) -> dict[str, Any]:
        try:
            add_shopping_item(self.profile, text)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def toggle_shopping(self, item_id: str) -> dict[str, Any]:
        try:
            toggle_shopping_item(self.profile, item_id)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def clear_shopping_completed(self) -> dict[str, Any]:
        try:
            clear_shopping_done(self.profile)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def clear_shopping_everything(self) -> dict[str, Any]:
        try:
            clear_shopping_all(self.profile)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ── calendar ──────────────────────────────────────────────────────────────

    def get_calendar(self) -> list[dict[str, Any]]:
        return list_calendar_events(self.profile)

    def add_calendar(self, title: str, event_date: str, event_time: str) -> dict[str, Any]:
        try:
            add_calendar_event(self.profile, title, event_date=event_date, event_time=event_time)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def delete_calendar(self, event_id: str) -> dict[str, Any]:
        try:
            delete_calendar_event(self.profile, event_id)
            save_profile_by_id(self.active_profile_id, self.profile)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ── profiles ──────────────────────────────────────────────────────────────

    def get_profiles(self) -> list[dict[str, Any]]:
        return list_profiles()

    def switch_profile(self, profile_id: str) -> dict[str, Any]:
        try:
            self.profile = set_active_profile(profile_id)
            self.active_profile_id = profile_id
            self._push_state()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def create_new_profile(self, name: str) -> dict[str, Any]:
        try:
            p = create_profile(name)
            return {"ok": True, "profile_id": p["profile_id"]}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def clone_profile(self, source_id: str, name: str) -> dict[str, Any]:
        try:
            src = load_profile_by_id(source_id)
            p = create_profile(name, base_profile=src)
            return {"ok": True, "profile_id": p["profile_id"]}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def delete_profile_item(self, profile_id: str) -> dict[str, Any]:
        try:
            new_active = delete_profile(profile_id)
            if self.active_profile_id == profile_id:
                self.active_profile_id = new_active
                self.profile = load_profile_by_id(new_active)
                self._push_state()
            return {"ok": True, "new_active": new_active}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def export_profile(self, profile_id: str) -> dict[str, Any]:
        """Return a profile wrapped in a portable envelope for download.

        The frontend turns this into a .json file the user can move to another
        machine (e.g. local PC -> Raspberry Pi) and import there.
        """
        try:
            profile = load_profile_by_id(profile_id)
            name = str(profile.get("profile_name", profile_id)) or profile_id
            safe = _safe_profile_id(name)
            return {
                "ok": True,
                "filename": f"{safe}.nova-profile.json",
                "data": {
                    "nova_profile_export": True,
                    "version": 1,
                    "profile": profile,
                },
            }
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def import_profile(self, data: Any, name: str = "") -> dict[str, Any]:
        """Create a new profile from imported JSON (envelope or raw profile).

        Accepts either the export envelope produced by ``export_profile`` or a
        bare profile dict. The imported profile always becomes a NEW profile
        (its id is de-duplicated), so importing never overwrites an existing one.
        """
        try:
            if isinstance(data, str):
                data = json.loads(data)
            if not isinstance(data, dict):
                return {"ok": False, "msg": "Invalid profile file."}
            src = data.get("profile") if isinstance(data.get("profile"), dict) else data
            if not isinstance(src, dict) or not src:
                return {"ok": False, "msg": "Invalid profile file."}
            # A profile from another machine can carry an absolute VRM path that
            # is meaningless here. Reduce it to a filename served from this
            # install's uploads dir, and drop the machine-specific absolute path.
            details = src.get("profile_details")
            if isinstance(details, dict) and isinstance(details.get("avatar"), dict):
                av = details["avatar"]
                last = av.get("last_loaded_vrm_path")
                if isinstance(last, str) and last:
                    av["last_loaded_vrm_path"] = AvatarBridge._to_servable_url(last)
                av.pop("vrm_path", None)
            profile_name = (
                str(name).strip()
                or str(src.get("profile_name", "")).strip()
                or str(src.get("companion_name", "")).strip()
                or "Imported Profile"
            )
            p = create_profile(profile_name, base_profile=src)
            return {"ok": True, "profile_id": p["profile_id"], "profile_name": p["profile_name"]}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    def get_profile_detail(self, profile_id: str) -> dict[str, Any]:
        try:
            return load_profile_by_id(profile_id)
        except Exception:
            return {}

    def save_profile_detail(self, profile_id: str, data: dict) -> dict[str, Any]:
        try:
            save_profile_by_id(profile_id, data)
            if profile_id == self.active_profile_id:
                self.profile = load_profile_by_id(profile_id)
                self._push_state()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "msg": str(exc)}

    # ── settings / devices ────────────────────────────────────────────────────

    def get_audio_devices(self) -> dict[str, Any]:
        if not self._initialized:
            return {"mics": [], "speakers": [], "current_mic": None, "current_speaker": None}
        try:
            mics = list_input_devices_compact()
            speakers = list_output_devices_compact()
        except Exception:
            mics = []
            speakers = []
        return {
            "mics": mics,
            "speakers": speakers,
            "current_mic": self.config.mic_device_index,
            "current_speaker": self.config.speaker_device_index,
        }

    def apply_audio_devices(self, mic_index: Any, speaker_index: Any) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.config.mic_device_index = int(mic_index) if mic_index is not None else None
        self.config.speaker_device_index = int(speaker_index) if speaker_index is not None else None
        self.state.mic_calibrated = False
        self.state.speech_recognizer = None
        self.state.speech_recognizer_signature = None
        return {"ok": True, "msg": "Audio devices applied."}

    def recalibrate_mic(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        if not self._acquire():
            return {"ok": False, "msg": "System is busy."}
        try:
            self._push_status("Calibrating microphone...")
            self.state.speech_recognizer = None
            self.state.speech_recognizer_signature = None
            self.state.mic_calibrated = False
            recalibrate_microphone(self.config, self.state, announce=False)
            self._push_status("Calibration complete.")
            return {"ok": True, "msg": "Microphone calibrated."}
        except Exception as exc:
            self._push_status(f"Calibration failed: {exc}")
            return {"ok": False, "msg": str(exc)}
        finally:
            self._release()

    def get_performance_info(self) -> list[str]:
        if not self._initialized:
            return ["Still loading..."]
        lines = [
            f"Model: {self.config.model}",
            f"Provider: {self.config.llm_provider}",
            f"Performance profile: {self.config.performance_profile}",
            f"System: {self.config.system_summary}",
            "",
        ] + list(self.config.performance_notes)
        return lines

    # ── history ───────────────────────────────────────────────────────────────

    def get_recent_history(self) -> list[dict[str, str]]:
        try:
            entries = read_recent_history(50)
            result = []
            for entry in entries:
                role = entry.get("role", "system")
                text = entry.get("content", "")
                if role == "user":
                    author = self.profile.get("user_name", "You")
                elif role == "assistant":
                    author = self.profile.get("companion_name", "NovaAI")
                else:
                    author = "System"
                result.append({"author": author, "text": text, "role": role})
            return result
        except Exception:
            return []

    def clear_history(self) -> dict[str, Any]:
        reset_history()
        self._push_chat("System", "History cleared.", "system")
        return {"ok": True, "msg": "History cleared."}

    # ── reminder checker (background thread) ──────────────────────────────────

    def _push_alert(self, msg: str) -> None:
        """Push an alarm/reminder notification with sound to the frontend."""
        safe = json.dumps(msg)
        self._js(f"window.__onAlertNotification({safe})")

    def _speak_alert(self, text: str) -> None:
        """Speak an alert message via TTS if voice is enabled."""
        if not self._initialized or not self.config:
            return
        self._speak(text, "neutral")

    def start_reminder_checker(self) -> None:
        def _checker():
            while True:
                time.sleep(30)
                try:
                    fired = check_due_reminders(self.profile)
                    for r in fired:
                        msg = r.get("title", "Reminder!")
                        self._push_alert(f"Reminder: {msg}")
                        self._push_chat("System", f"\u23f0 Reminder: {msg}", "system")
                        self._speak_alert(f"Reminder: {msg}")
                    fired_alarms = check_due_alarms(self.profile)
                    for a in fired_alarms:
                        label = a.get("label", "Alarm!")
                        self._push_alert(f"Alarm: {label}")
                        self._push_chat("System", f"\u23f0 Alarm: {label}", "system")
                        self._speak_alert(f"Alarm: {label}")
                    if fired or fired_alarms:
                        self.profile = save_profile_by_id(
                            self.active_profile_id, self.profile
                        )
                        self._js("window.__onFeaturesChanged()")
                except Exception:
                    pass

        t = threading.Thread(target=_checker, daemon=True)
        t.start()


def _set_windows_app_id() -> None:
    """Set the Windows taskbar app identity before the GUI window is created."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except Exception:
        pass


def _set_window_icon() -> None:
    """Set the taskbar and title-bar icon on Windows via Win32 API."""
    if sys.platform != "win32" or not ICON_PATH.exists():
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040
        IMAGE_ICON = 1

        icon_path = str(ICON_PATH)
        h_small = user32.LoadImageW(0, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        h_big = user32.LoadImageW(
            0,
            icon_path,
            IMAGE_ICON,
            0,
            0,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )

        for _ in range(20):
            hwnd = user32.FindWindowW(None, WINDOW_TITLE)
            if hwnd:
                if h_small:
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
                if h_big:
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
                return
            time.sleep(0.25)
    except Exception:
        pass


def main() -> None:
    global _window
    if webview is None:
        raise SystemExit(
            "The desktop GUI needs pywebview, which isn't installed.\n"
            "Install it with:  pip install -r requirements-gui.txt\n"
            "Or run the headless browser UI instead:  python app.py --web"
        )
    # The desktop GUI is a local app, so its sibling services (avatar overlay,
    # Minecraft live view) stay bound to localhost only.
    os.environ.setdefault("NOVA_BIND_HOST", "127.0.0.1")
    _set_windows_app_id()

    api = Api()
    html_path = STATIC_DIR / "index.html"

    def _on_loaded():
        api.start_reminder_checker()
        threading.Thread(target=_set_window_icon, daemon=True).start()

    _window = webview.create_window(
        title=WINDOW_TITLE,
        url=str(html_path),
        js_api=api,
        width=1340,
        height=860,
        min_size=(960, 600),
        background_color="#0f0f14",
        text_select=True,
    )
    _window.events.loaded += _on_loaded
    webview.start(debug=False)
