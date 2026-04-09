from __future__ import annotations

import json
from typing import Any

from .audio_input import (
    capture_voice_turn,
    describe_selected_microphone,
    describe_stt_backend,
    print_input_devices,
    recalibrate_microphone,
    resolve_input_device_info,
)
from .chat import request_reply
from .config import Config, parse_input_mode
from .defaults import VOICE_COMMAND_ALIASES
from .models import CommandResult, SessionState, UserTurn
from .storage import (
    append_history,
    ensure_runtime_dirs,
    load_profile,
    reset_history,
    save_profile,
)
from .tts import (
    describe_tts_voice,
    get_xtts_device,
    list_xtts_speakers,
    play_audio_file,
    print_xtts_speakers,
    resolve_optional_path,
    speak_text,
)
from .utils import console_safe_text


def print_welcome(profile: dict[str, Any], config: Config, state: SessionState) -> None:
    print()
    print(f"{profile['companion_name']} is ready.")
    print(
        f"Model: {config.model} | Input: {state.input_mode} | "
        f"Voice output: {'on' if state.voice_enabled else 'off'}"
    )
    print(
        f"XTTS language: {config.tts_language} | "
        f"Speech recognition: {describe_stt_backend(config)} | "
        f"Language: {config.stt_language}"
    )
    print(
        f"XTTS voice: {describe_tts_voice(config)} | XTTS device: {get_xtts_device(config)}"
    )
    print(
        f"XTTS streaming: {'on' if config.xtts_stream_output else 'off'} "
        f"(buffer {config.xtts_stream_buffer_seconds:.1f}s) | "
        f"Reply limit: {config.ollama_num_predict} tokens"
    )
    print(
        f"Performance: {config.performance_profile} | "
        f"Auto-tune: {'on' if config.auto_tune_performance else 'off'} "
        f"({config.auto_tune_goal})"
    )
    print(f"Hardware: {config.system_summary}")
    print(f"Microphone: {describe_selected_microphone(config)}")
    print(
        "Hands-free mode listens after each reply. Text mode keeps the keyboard prompt."
    )
    print(
        "Commands: /help, /mode <voice|text>, /listen, /recalibrate, /mics, "
        "/mic <index|default>, /speakers, /speaker <name>, /voice [on|off], "
        "/performance, "
        "/profile, /name <new name>, /me <your name>, /remember <fact>, "
        "/reset, /exit"
    )
    print()


def print_help() -> None:
    print()
    print("/help                   Show commands")
    print("/mode                   Show the current input mode")
    print("/mode voice             Turn on hands-free microphone input")
    print("/mode text              Switch back to keyboard input")
    print("/listen                 Capture one spoken turn right now")
    print("/recalibrate            Relearn the room noise before listening")
    print("/mics                   List available microphone devices")
    print("/mic                    Show the selected microphone")
    print("/mic <index>            Choose a microphone from /mics")
    print("/mic default            Use the system default microphone")
    print("/speakers               List available XTTS built-in voices")
    print("/speaker                Show the current XTTS voice")
    print("/speaker <name>         Switch to a different XTTS built-in voice")
    print("/voice                  Toggle spoken replies on or off")
    print("/voice on               Always speak replies")
    print("/voice off              Stop speaking replies")
    print("/performance            Show the auto-tuned performance profile")
    print("/profile                Show the current saved profile")
    print("/name <new name>        Rename your companion")
    print("/me <your name>         Set your name")
    print("/remember <fact>        Save something important for future chats")
    print("/reset                  Clear conversation history")
    print("/exit                   Quit the app")
    print()


def print_performance_summary(config: Config) -> None:
    print()
    print(f"Performance profile: {config.performance_profile}")
    print(
        f"Auto-tune: {'on' if config.auto_tune_performance else 'off'} "
        f"({config.auto_tune_goal})"
    )
    print(f"Hardware: {config.system_summary}")
    print(
        f"Active settings: reply limit {config.ollama_num_predict} | "
        f"STT {describe_stt_backend(config)} | "
        f"XTTS {get_xtts_device(config)} at speed {config.xtts_speed:.2f}"
    )
    for note in config.performance_notes:
        print(f"- {note}")
    print()


def parse_voice_setting(argument: str) -> bool | None:
    normalized = argument.strip().lower()
    if normalized in {"on", "true", "1", "yes"}:
        return True
    if normalized in {"off", "false", "0", "no"}:
        return False
    return None


def handle_microphone_command(
    command: str,
    config: Config,
    state: SessionState,
) -> None:
    lowered = command.lower()
    if lowered == "/mic":
        print(f"Microphone is currently {describe_selected_microphone(config)}.")
        return

    selection = command[5:].strip()
    if not selection:
        print("Use /mic <index> or /mic default.")
        return

    if selection.lower() == "default":
        config.mic_device_index = None
        state.speech_recognizer = None
        state.speech_recognizer_signature = None
        state.mic_calibrated = False
        print(f"Microphone is now {describe_selected_microphone(config)}.")
        return

    try:
        device_index = int(selection)
        device_info = resolve_input_device_info(device_index)
    except ValueError:
        print("Use /mic <index> or /mic default.")
        return
    except RuntimeError as exc:
        print(exc)
        return

    config.mic_device_index = device_index
    state.speech_recognizer = None
    state.speech_recognizer_signature = None
    state.mic_calibrated = False
    print(f"Microphone is now #{device_info['index']} ({device_info['name']}).")


def handle_speaker_command(
    command: str,
    config: Config,
    state: SessionState,
) -> None:
    lowered = command.lower()
    if lowered == "/speaker":
        print(console_safe_text(f"XTTS voice is currently {describe_tts_voice(config)}."))
        return

    selection = command[9:].strip()
    if not selection:
        print("Use /speaker <name>.")
        return

    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)
    if speaker_wav is not None:
        print(
            "XTTS is currently using XTTS_SPEAKER_WAV. "
            "Clear that setting to use built-in speakers."
        )
        return

    available_speakers = list_xtts_speakers(config, state)
    selected_speaker = next(
        (speaker for speaker in available_speakers if speaker.lower() == selection.lower()),
        None,
    )
    if selected_speaker is None:
        print("That XTTS speaker was not found. Run /speakers to list valid names.")
        return

    config.xtts_speaker = selected_speaker
    print(console_safe_text(f"XTTS voice is now {selected_speaker}."))


def map_spoken_command(text: str) -> str:
    normalized = " ".join(text.strip().lower().split())
    return VOICE_COMMAND_ALIASES.get(normalized, text)


def handle_command(
    incoming_text: str,
    profile: dict[str, Any],
    state: SessionState,
    config: Config,
) -> CommandResult:
    command = incoming_text.strip()
    lowered = command.lower()

    if lowered == "/help":
        print_help()
        return CommandResult(handled=True)

    if lowered == "/mode":
        print(f"Input mode is {state.input_mode}.")
        return CommandResult(handled=True)

    if lowered.startswith("/mode "):
        new_mode = parse_input_mode(command[6:])
        if new_mode is None:
            print("Use /mode voice or /mode text.")
            return CommandResult(handled=True)
        state.input_mode = new_mode
        print(f"Input mode is now {new_mode}.")
        return CommandResult(handled=True)

    if lowered == "/listen":
        voice_turn = capture_voice_turn(config, profile, state)
        return CommandResult(handled=True, injected_turn=voice_turn)

    if lowered == "/recalibrate":
        state.speech_recognizer = None
        state.speech_recognizer_signature = None
        state.mic_calibrated = False
        recalibrate_microphone(config, state)
        return CommandResult(handled=True)

    if lowered == "/mics":
        try:
            print_input_devices()
        except RuntimeError as exc:
            print(exc)
        return CommandResult(handled=True)

    if lowered == "/mic" or lowered.startswith("/mic "):
        handle_microphone_command(command, config, state)
        return CommandResult(handled=True)

    if lowered == "/speakers":
        try:
            print_xtts_speakers(config, state)
        except RuntimeError as exc:
            print(exc)
        return CommandResult(handled=True)

    if lowered == "/speaker" or lowered.startswith("/speaker "):
        try:
            handle_speaker_command(command, config, state)
        except RuntimeError as exc:
            print(exc)
        return CommandResult(handled=True)

    if lowered == "/voice":
        state.voice_enabled = not state.voice_enabled
        print(f"Voice output is now {'on' if state.voice_enabled else 'off'}.")
        return CommandResult(handled=True)

    if lowered.startswith("/voice "):
        setting = parse_voice_setting(command[7:])
        if setting is None:
            print("Use /voice, /voice on, or /voice off.")
            return CommandResult(handled=True)
        state.voice_enabled = setting
        print(f"Voice output is now {'on' if state.voice_enabled else 'off'}.")
        return CommandResult(handled=True)

    if lowered == "/profile":
        print()
        print(json.dumps(profile, indent=2, ensure_ascii=False))
        print()
        return CommandResult(handled=True)

    if lowered in {"/performance", "/perf"}:
        print_performance_summary(config)
        return CommandResult(handled=True)

    if lowered == "/reset":
        reset_history()
        print("Conversation history cleared.")
        return CommandResult(handled=True)

    if lowered == "/exit":
        return CommandResult(handled=True, should_exit=True)

    if lowered.startswith("/name "):
        new_name = command[6:].strip()
        if new_name:
            profile["companion_name"] = new_name
            save_profile(profile)
            print(f"Your companion is now named {new_name}.")
        return CommandResult(handled=True)

    if lowered.startswith("/me "):
        new_name = command[4:].strip()
        if new_name:
            profile["user_name"] = new_name
            save_profile(profile)
            print(f"Saved your name as {new_name}.")
        return CommandResult(handled=True)

    if lowered.startswith("/remember "):
        note = command[10:].strip()
        if note:
            notes = profile.setdefault("memory_notes", [])
            if note not in notes:
                notes.append(note)
                save_profile(profile)
                print("Saved that memory note.")
            else:
                print("That memory note is already saved.")
        return CommandResult(handled=True)

    return CommandResult(handled=False)


def get_next_user_turn(
    profile: dict[str, Any],
    state: SessionState,
    config: Config,
) -> UserTurn | None:
    if state.input_mode == "voice":
        try:
            return capture_voice_turn(config, profile, state)
        except RuntimeError as exc:
            print()
            print(f"[Mic] {exc}")
            print("[Mic] Switching back to text mode so you can keep chatting.")
            print()
            state.input_mode = "text"
            return None

    try:
        prompt_name = profile["user_name"]
        user_text = input(f"{prompt_name}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSee you soon.")
        raise SystemExit from None

    if not user_text:
        return None

    return UserTurn(text=user_text, from_voice=False)


def resolve_user_turn(
    turn: UserTurn,
    profile: dict[str, Any],
    state: SessionState,
    config: Config,
) -> tuple[str, bool]:
    current_turn = turn

    while True:
        incoming_text = (
            map_spoken_command(current_turn.text)
            if current_turn.from_voice
            else current_turn.text
        )
        result = handle_command(incoming_text, profile, state, config)

        if result.should_exit:
            return "", True

        if result.injected_turn is not None:
            current_turn = result.injected_turn
            continue

        if result.handled:
            return "", False

        return incoming_text, False


def main() -> None:
    ensure_runtime_dirs()
    config = Config.from_env()
    profile = load_profile()
    state = SessionState(
        voice_enabled=config.voice_enabled,
        input_mode=config.input_mode,
    )

    print_welcome(profile, config, state)

    while True:
        try:
            turn = get_next_user_turn(profile, state, config)
        except SystemExit:
            break

        if turn is None:
            continue

        try:
            user_text, should_exit = resolve_user_turn(turn, profile, state, config)
        except RuntimeError as exc:
            print()
            print(f"[Mic] {exc}")
            print("[Mic] Staying in text mode for now.")
            print()
            state.input_mode = "text"
            continue

        if should_exit:
            print("See you soon.")
            break

        if not user_text:
            continue

        try:
            reply = request_reply(user_text, profile, config)
        except RuntimeError as exc:
            print()
            print(f"[Companion error] {exc}")
            print()
            continue

        append_history("user", user_text)
        append_history("assistant", reply)

        print()
        print(console_safe_text(f"{profile['companion_name']}: {reply}"))
        print()

        if state.voice_enabled:
            audio_path = None
            try:
                audio_path = speak_text(reply, config, state)
                if not config.xtts_stream_output:
                    play_audio_file(audio_path)
            except Exception as exc:
                latest_path = audio_path or "audio/latest_reply.wav"
                print(
                    "[Voice] Voice generation or playback failed. "
                    f"The latest audio file is at {latest_path}: {exc}"
                )
