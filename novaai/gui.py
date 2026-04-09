from __future__ import annotations

import json
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

from .audio_input import (
    describe_selected_microphone,
    describe_stt_backend,
    recalibrate_microphone,
    recognize_speech,
)
from .chat import request_reply
from .config import Config
from .models import SessionState
from .storage import (
    append_history,
    ensure_runtime_dirs,
    load_profile,
    read_recent_history,
    reset_history,
)
from .tts import describe_tts_voice, get_xtts_device, play_audio_file, speak_text


class NovaAIGui:
    def __init__(self, auto_listen_on_launch: bool = True):
        ensure_runtime_dirs()
        self.config = Config.from_env()
        self.profile = load_profile()
        self.state = SessionState(
            voice_enabled=self.config.voice_enabled,
            input_mode=self.config.input_mode,
        )

        self.root = tk.Tk()
        self.root.title(f"{self.profile['companion_name']} Control")
        self.root.geometry("1180x780")
        self.root.minsize(980, 640)
        self.root.configure(bg="#08111f")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.hands_free_enabled = self.config.input_mode == "voice"
        self.mic_muted = False
        self.busy = False
        self.busy_reason = ""
        self.closing = False
        self.auto_listen_on_launch = auto_listen_on_launch

        self.status_text = tk.StringVar(value="Ready.")
        self.performance_text = tk.StringVar()
        self.mic_text = tk.StringVar()
        self.voice_text = tk.StringVar()
        self.mode_text = tk.StringVar()

        self._build_ui()
        self._load_recent_history()
        self._refresh_summary_labels()
        self._refresh_controls()
        self._append_system_message(
            "NovaAI GUI is ready. Use Listen Now for one turn or toggle hands-free mode."
        )
        self._append_system_message(
            "Mic mute is app-level: it blocks new captures and stops hands-free from starting another listen."
        )

        if self.auto_listen_on_launch and self.hands_free_enabled and not self.mic_muted:
            self.root.after(900, lambda: self.start_listen(auto=True))

    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=3)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self.root, bg="#08111f", padx=20, pady=18)
        header.grid(row=0, column=0, columnspan=2, sticky="nsew")
        header.grid_columnconfigure(0, weight=1)

        title = tk.Label(
            header,
            text=f"{self.profile['companion_name']} Control Deck",
            bg="#08111f",
            fg="#f8fafc",
            font=("Segoe UI Semibold", 20),
        )
        title.grid(row=0, column=0, sticky="w")

        subtitle = tk.Label(
            header,
            text=(
                f"Model {self.config.model} | "
                f"STT {describe_stt_backend(self.config)} | "
                f"XTTS {describe_tts_voice(self.config)} on {get_xtts_device(self.config)}"
            ),
            bg="#08111f",
            fg="#93a4bc",
            font=("Segoe UI", 10),
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(6, 0))

        transcript_frame = tk.Frame(self.root, bg="#08111f", padx=20, pady=0)
        transcript_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 20))
        transcript_frame.grid_rowconfigure(0, weight=1)
        transcript_frame.grid_columnconfigure(0, weight=1)

        self.transcript = scrolledtext.ScrolledText(
            transcript_frame,
            wrap="word",
            bg="#0f1b2d",
            fg="#dde7f3",
            insertbackground="#dde7f3",
            relief="flat",
            borderwidth=0,
            padx=18,
            pady=18,
            font=("Segoe UI", 11),
        )
        self.transcript.grid(row=0, column=0, sticky="nsew")
        self.transcript.configure(state="disabled")
        self.transcript.tag_configure("system_name", foreground="#7dd3fc", font=("Segoe UI Semibold", 10))
        self.transcript.tag_configure("system_body", foreground="#9fb4c9", font=("Segoe UI", 10))
        self.transcript.tag_configure("user_name", foreground="#fbbf24", font=("Segoe UI Semibold", 10))
        self.transcript.tag_configure("user_body", foreground="#f8fafc", font=("Segoe UI", 11))
        self.transcript.tag_configure("assistant_name", foreground="#86efac", font=("Segoe UI Semibold", 10))
        self.transcript.tag_configure("assistant_body", foreground="#ecfccb", font=("Segoe UI", 11))

        composer = tk.Frame(transcript_frame, bg="#08111f", pady=14)
        composer.grid(row=1, column=0, sticky="ew")
        composer.grid_columnconfigure(0, weight=1)

        self.message_entry = tk.Entry(
            composer,
            bg="#13233a",
            fg="#f8fafc",
            insertbackground="#f8fafc",
            relief="flat",
            font=("Segoe UI", 11),
        )
        self.message_entry.grid(row=0, column=0, sticky="ew", ipady=11)
        self.message_entry.bind("<Return>", self._on_send_pressed)

        self.send_button = tk.Button(
            composer,
            text="Send",
            command=self.send_text_message,
            bg="#38bdf8",
            fg="#08111f",
            activebackground="#7dd3fc",
            activeforeground="#08111f",
            relief="flat",
            padx=18,
            pady=10,
            font=("Segoe UI Semibold", 10),
        )
        self.send_button.grid(row=0, column=1, padx=(12, 0))

        side_panel = tk.Frame(self.root, bg="#08111f", padx=0, pady=0)
        side_panel.grid(row=1, column=1, sticky="nsew", padx=(0, 20), pady=(0, 20))
        side_panel.grid_columnconfigure(0, weight=1)

        self.summary_card = self._make_card(side_panel, "Session")
        self.summary_card.grid(row=0, column=0, sticky="ew")

        tk.Label(
            self.summary_card,
            textvariable=self.performance_text,
            justify="left",
            anchor="w",
            bg="#0f1b2d",
            fg="#dde7f3",
            font=("Segoe UI", 10),
        ).pack(fill="x")
        tk.Label(
            self.summary_card,
            textvariable=self.mic_text,
            justify="left",
            anchor="w",
            bg="#0f1b2d",
            fg="#9fb4c9",
            font=("Segoe UI", 10),
            pady=6,
        ).pack(fill="x")
        tk.Label(
            self.summary_card,
            textvariable=self.voice_text,
            justify="left",
            anchor="w",
            bg="#0f1b2d",
            fg="#9fb4c9",
            font=("Segoe UI", 10),
        ).pack(fill="x")
        tk.Label(
            self.summary_card,
            textvariable=self.mode_text,
            justify="left",
            anchor="w",
            bg="#0f1b2d",
            fg="#9fb4c9",
            font=("Segoe UI", 10),
            pady=6,
        ).pack(fill="x")

        controls_card = self._make_card(side_panel, "Controls")
        controls_card.grid(row=1, column=0, sticky="ew", pady=(14, 0))

        self.listen_button = self._make_action_button(
            controls_card, "Listen Now", self.start_listen_once
        )
        self.listen_button.pack(fill="x")

        self.hands_free_button = self._make_action_button(
            controls_card, "Hands-free: Off", self.toggle_hands_free
        )
        self.hands_free_button.pack(fill="x", pady=(10, 0))

        self.mic_button = self._make_action_button(
            controls_card, "Mic: Live", self.toggle_mic_muted
        )
        self.mic_button.pack(fill="x", pady=(10, 0))

        self.voice_button = self._make_action_button(
            controls_card, "Voice Replies: On", self.toggle_voice_output
        )
        self.voice_button.pack(fill="x", pady=(10, 0))

        self.recalibrate_button = self._make_action_button(
            controls_card, "Recalibrate Mic", self.start_recalibration
        )
        self.recalibrate_button.pack(fill="x", pady=(10, 0))

        self.performance_button = self._make_action_button(
            controls_card, "Show Performance", self.show_performance
        )
        self.performance_button.pack(fill="x", pady=(10, 0))

        self.clear_button = self._make_action_button(
            controls_card, "Clear History", self.clear_history
        )
        self.clear_button.pack(fill="x", pady=(10, 0))

        status_card = self._make_card(side_panel, "Status")
        status_card.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        tk.Label(
            status_card,
            textvariable=self.status_text,
            justify="left",
            anchor="w",
            wraplength=300,
            bg="#0f1b2d",
            fg="#fde68a",
            font=("Segoe UI", 10),
        ).pack(fill="x")

    def _make_card(self, parent: tk.Widget, title: str) -> tk.Frame:
        card = tk.Frame(parent, bg="#0f1b2d", padx=16, pady=16, highlightthickness=1)
        card.configure(highlightbackground="#17304e", highlightcolor="#17304e")
        tk.Label(
            card,
            text=title,
            bg="#0f1b2d",
            fg="#f8fafc",
            font=("Segoe UI Semibold", 12),
            pady=2,
        ).pack(anchor="w")
        return card

    def _make_action_button(
        self,
        parent: tk.Widget,
        text: str,
        command: object,
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg="#13233a",
            fg="#f8fafc",
            activebackground="#1d3557",
            activeforeground="#f8fafc",
            relief="flat",
            padx=12,
            pady=10,
            font=("Segoe UI Semibold", 10),
            anchor="w",
        )

    def _load_recent_history(self) -> None:
        for message in read_recent_history(self.config.history_turns):
            role = message.get("role")
            content = message.get("content", "")
            if role == "user":
                self._append_message(self.profile["user_name"], content, "user")
            elif role == "assistant":
                self._append_message(self.profile["companion_name"], content, "assistant")

    def _append_message(self, author: str, text: str, role: str) -> None:
        tag_prefix = {
            "system": "system",
            "user": "user",
            "assistant": "assistant",
        }[role]

        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{author}\n", f"{tag_prefix}_name")
        self.transcript.insert("end", f"{text}\n\n", f"{tag_prefix}_body")
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def _append_system_message(self, text: str) -> None:
        self._append_message("System", text, "system")

    def _refresh_summary_labels(self) -> None:
        self.performance_text.set(
            f"Profile: {self.config.performance_profile}\n"
            f"Auto-tune: {'on' if self.config.auto_tune_performance else 'off'} "
            f"({self.config.auto_tune_goal})\n"
            f"Hardware: {self.config.system_summary}"
        )
        self.mic_text.set(
            f"Microphone: {describe_selected_microphone(self.config)}\n"
            f"Speech recognition: {describe_stt_backend(self.config)}"
        )
        self.voice_text.set(
            f"Voice replies: {'on' if self.state.voice_enabled else 'off'}\n"
            f"XTTS voice: {describe_tts_voice(self.config)}"
        )
        self.mode_text.set(
            f"Hands-free: {'on' if self.hands_free_enabled else 'off'}\n"
            f"Mic muted: {'yes' if self.mic_muted else 'no'}"
        )
        self.root.title(f"{self.profile['companion_name']} Control")

    def _refresh_controls(self) -> None:
        busy = self.busy
        listen_state = "disabled" if busy or self.mic_muted else "normal"
        send_state = "disabled" if busy else "normal"
        action_state = "disabled" if busy else "normal"

        self.send_button.configure(state=send_state)
        self.message_entry.configure(state="normal" if not busy else "disabled")
        self.listen_button.configure(state=listen_state)
        self.recalibrate_button.configure(state=action_state)
        self.performance_button.configure(state="normal")
        self.clear_button.configure(state=action_state)

        self.hands_free_button.configure(
            text=f"Hands-free: {'On' if self.hands_free_enabled else 'Off'}"
        )
        self.voice_button.configure(
            text=f"Voice Replies: {'On' if self.state.voice_enabled else 'Off'}"
        )

        if self.mic_muted:
            self.mic_button.configure(
                text="Mic: Muted",
                bg="#7f1d1d",
                activebackground="#991b1b",
            )
        else:
            self.mic_button.configure(
                text="Mic: Live",
                bg="#13233a",
                activebackground="#1d3557",
            )

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
            self.status_text.set(f"NovaAI is busy {self.busy_reason or 'right now'}.")
            return False
        self._set_busy(True, reason)
        return True

    def _finish_task(self, next_status: str = "Ready.") -> None:
        self._set_busy(False)
        self.status_text.set(next_status)

    def _schedule_auto_listen(self) -> None:
        if self.closing or self.busy or not self.hands_free_enabled or self.mic_muted:
            return
        self.root.after(350, lambda: self.start_listen(auto=True))

    def _on_send_pressed(self, _event: object) -> None:
        self.send_text_message()

    def send_text_message(self) -> None:
        raw_text = self.message_entry.get().strip()
        if not raw_text:
            return
        self.message_entry.delete(0, "end")

        if raw_text.startswith("/"):
            self._handle_gui_command(raw_text)
            return

        if not self._begin_task("replying"):
            return

        self.status_text.set("Thinking...")
        worker = threading.Thread(
            target=self._reply_worker,
            args=(raw_text, False),
            daemon=True,
        )
        worker.start()

    def _handle_gui_command(self, command: str) -> None:
        lowered = command.strip().lower()

        if lowered == "/listen":
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

        if lowered == "/profile":
            self._append_system_message(
                json.dumps(self.profile, indent=2, ensure_ascii=False)
            )
            return

        if lowered == "/help":
            self._append_system_message(
                "GUI commands: /listen, /performance, /reset, /voice, "
                "/mode voice, /mode text, /recalibrate, /profile."
            )
            return

        self._append_system_message(
            "That slash command is not wired into the GUI yet. Use the buttons on the right or the CLI if you want the full command set."
        )

    def start_listen_once(self) -> None:
        self.start_listen(auto=False)

    def start_listen(self, auto: bool) -> None:
        if self.mic_muted:
            self.status_text.set("Mic is muted. Unmute it before listening.")
            return

        if not self._begin_task("listening"):
            return

        self.status_text.set("Listening...")
        worker = threading.Thread(
            target=self._voice_turn_worker,
            args=(auto,),
            daemon=True,
        )
        worker.start()

    def _voice_turn_worker(self, auto: bool) -> None:
        next_status = "Ready."
        try:
            result = recognize_speech(self.config, self.state, announce=False)

            if result.status == "timeout":
                next_status = "No speech detected."
                return

            if result.status == "unknown":
                next_status = "I heard something but could not make it out."
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
            next_status = f"Microphone error: {exc}"
            self._safe_ui(lambda: self._append_system_message(next_status))
        finally:
            self._safe_ui(lambda: self._finish_task(next_status))
            if self.hands_free_enabled and not self.mic_muted and not self.closing:
                self._safe_ui(self._schedule_auto_listen)

    def _reply_worker(self, user_text: str, from_voice: bool) -> None:
        next_status = "Ready."
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
        self._safe_ui(lambda: self._append_message(self.profile["user_name"], user_text, "user"))
        self._safe_ui(lambda: self.status_text.set("Thinking..."))

        reply = request_reply(user_text, self.profile, self.config)
        append_history("user", user_text)
        append_history("assistant", reply)

        self._safe_ui(
            lambda: self._append_message(self.profile["companion_name"], reply, "assistant")
        )

        if self.state.voice_enabled:
            self._safe_ui(lambda: self.status_text.set("Speaking..."))
            audio_path = speak_text(reply, self.config, self.state)
            if not self.config.xtts_stream_output:
                play_audio_file(audio_path)

        if from_voice and self.hands_free_enabled and not self.mic_muted:
            return "Reply finished. Hands-free will listen again."
        return "Ready."

    def toggle_hands_free(self) -> None:
        self.hands_free_enabled = not self.hands_free_enabled
        self.config.input_mode = "voice" if self.hands_free_enabled else "text"
        self._refresh_summary_labels()
        self._refresh_controls()

        if self.hands_free_enabled:
            self.status_text.set("Hands-free mode is on.")
            if not self.busy and not self.mic_muted:
                self.root.after(300, lambda: self.start_listen(auto=True))
            return

        self.status_text.set("Hands-free mode is off.")

    def toggle_mic_muted(self) -> None:
        self.mic_muted = not self.mic_muted
        self._refresh_summary_labels()
        self._refresh_controls()

        if self.mic_muted:
            if self.busy and self.busy_reason == "listening":
                self.status_text.set(
                    "Mic muted. The current listen will finish, then NovaAI will stop listening."
                )
            else:
                self.status_text.set("Mic muted.")
            return

        self.status_text.set("Mic live.")
        if self.hands_free_enabled and not self.busy:
            self.root.after(250, lambda: self.start_listen(auto=True))

    def toggle_voice_output(self) -> None:
        self.state.voice_enabled = not self.state.voice_enabled
        self._refresh_summary_labels()
        self._refresh_controls()
        self.status_text.set(
            f"Voice replies {'enabled' if self.state.voice_enabled else 'disabled'}."
        )

    def start_recalibration(self) -> None:
        if not self._begin_task("recalibrating"):
            return

        self.status_text.set("Calibrating microphone...")
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
            f"Performance profile: {self.config.performance_profile}",
            f"Auto-tune: {'on' if self.config.auto_tune_performance else 'off'} "
            f"({self.config.auto_tune_goal})",
            f"Hardware: {self.config.system_summary}",
            f"Reply limit: {self.config.ollama_num_predict}",
            f"STT: {describe_stt_backend(self.config)}",
            f"XTTS: {get_xtts_device(self.config)} at speed {self.config.xtts_speed:.2f}",
        ]
        lines.extend(self.config.performance_notes)
        self._append_system_message("\n".join(lines))
        self.status_text.set("Performance summary posted.")

    def clear_history(self) -> None:
        if self.busy:
            self.status_text.set("Wait for the current task to finish before clearing history.")
            return

        confirmed = messagebox.askyesno(
            "Clear history",
            "Delete the saved conversation history for NovaAI?",
            parent=self.root,
        )
        if not confirmed:
            return

        reset_history()
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", "end")
        self.transcript.configure(state="disabled")
        self._append_system_message("Conversation history cleared.")
        self.status_text.set("Conversation history cleared.")

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
