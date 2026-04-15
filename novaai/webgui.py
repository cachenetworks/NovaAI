"""NovaAI - pywebview desktop GUI with Tailwind CSS frontend."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import webview

from .audio_input import (
    describe_selected_microphone,
    describe_stt_backend,
    list_input_devices_compact,
    recalibrate_microphone,
    recognize_speech,
)
from .chat import request_reply
from .config import Config
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

STATIC_DIR = Path(__file__).resolve().parent / "static"
ICON_PATH = Path(__file__).resolve().parent.parent / "data" / "logo.ico"
_window: webview.Window | None = None


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
        self.busy = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Heavy init — called from JS once the loading screen is visible."""
        ensure_runtime_dirs()
        self.config = Config.from_env()
        self.active_profile_id = get_active_profile_id()
        self.profile = load_profile() or {}
        self.state = SessionState(
            voice_enabled=False,
            input_mode=self.config.input_mode,
        )
        self.config.voice_enabled = False
        self.hands_free_enabled = self.config.input_mode == "voice"
        self._initialized = True
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
        global _window
        if _window:
            try:
                _window.evaluate_js(code)
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
        self._push_state()
        return {"voice_enabled": self.state.voice_enabled}

    def toggle_handsfree(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.hands_free_enabled = not self.hands_free_enabled
        self.config.input_mode = "voice" if self.hands_free_enabled else "text"
        self._push_state()
        if self.hands_free_enabled and not self.busy and not self.mic_muted and self.session_started:
            threading.Thread(target=self._auto_listen, daemon=True).start()
        return {"hands_free": self.hands_free_enabled}

    def toggle_mic(self) -> dict[str, Any]:
        self.mic_muted = not self.mic_muted
        self._push_state()
        if not self.mic_muted and self.hands_free_enabled and not self.busy and self.session_started:
            threading.Thread(target=self._auto_listen, daemon=True).start()
        return {"mic_muted": self.mic_muted}

    def toggle_web_search(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.config.web_browsing_enabled = not self.config.web_browsing_enabled
        self._push_state()
        return {"web_search": self.config.web_browsing_enabled}

    def toggle_auto_search(self) -> dict[str, Any]:
        if (err := self._not_ready()): return err
        self.config.web_auto_search = not self.config.web_auto_search
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

        # Media
        media_action = handle_media_request(user_text, self.profile, self.config)
        if media_action.handled:
            self.profile = save_profile_by_id(self.active_profile_id, self.profile)
            append_history("user", user_text)
            append_history("assistant", media_action.response)
            self._push_chat(companion, media_action.response, "assistant")
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
                try:
                    speak_text(feature_result.response, self.config, self.state)
                except Exception:
                    pass
            self._push_status("Ready.")
            return "Feature request handled."

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

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
        reply = request_reply(user_text, self.profile, self.config, web_context=web_context)

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        append_history("user", user_text)
        append_history("assistant", reply)
        self._push_chat(companion, reply, "assistant")

        if self.state.voice_enabled and not self._stopped():
            self._push_status("Speaking...")
            try:
                audio_path = speak_text(reply, self.config, self.state)
                if should_play_audio_after_synthesis(self.config) and not self._stopped():
                    play_audio_file(audio_path, self.config.speaker_device_index)
            except Exception:
                pass

        if self._stopped():
            self._push_status("Stopped.")
            return "Stopped."

        if from_voice and self.hands_free_enabled and not self.mic_muted:
            self._push_status("Listening...")
            threading.Thread(target=self._auto_listen, daemon=True).start()
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
        try:
            audio_path = speak_text(text, self.config, self.state)
            if should_play_audio_after_synthesis(self.config):
                play_audio_file(audio_path, self.config.speaker_device_index)
        except Exception:
            pass

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

        icon_path = str(ICON_PATH)
        h_small = user32.LoadImageW(0, icon_path, 1, 16, 16, LR_LOADFROMFILE)
        h_big = user32.LoadImageW(0, icon_path, 1, 32, 32, LR_LOADFROMFILE)

        # Try multiple ways to find our window handle
        hwnd = user32.FindWindowW(None, "NovaAI Studio")
        if not hwnd:
            hwnd = user32.GetForegroundWindow()
        if hwnd:
            if h_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
            if h_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
    except Exception:
        pass


def main() -> None:
    global _window
    api = Api()
    html_path = STATIC_DIR / "index.html"

    def _on_loaded():
        api.start_reminder_checker()
        threading.Thread(target=_set_window_icon, daemon=True).start()

    _window = webview.create_window(
        title="NovaAI Studio",
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
