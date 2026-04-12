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
from .config import Config, normalize_tts_provider, parse_input_mode
from .defaults import VOICE_COMMAND_ALIASES
from .models import CommandResult, SessionState, UserTurn
from .media import handle_media_request
from .storage import (
    append_history,
    ensure_runtime_dirs,
    list_profiles,
    load_profile,
    reset_history,
    save_profile,
    set_active_profile,
)
from .tts import (
    describe_tts_voice,
    get_xtts_device,
    list_xtts_speakers,
    play_audio_file,
    print_xtts_speakers,
    resolve_optional_path,
    should_play_audio_after_synthesis,
    speak_text,
)
from .utils import console_safe_text
from .web_search import (
    extract_web_query_from_request,
    fetch_web_context,
    should_auto_search,
)
from .features import (
    handle_feature_request,
    list_reminders,
    list_alarms,
    cancel_all_alarms,
    list_todos,
    toggle_todo,
    delete_todo,
    list_shopping,
    toggle_shopping_item,
    clear_shopping_done,
    list_calendar_events,
)
from .scheduler import FeatureScheduler


def print_welcome(profile: dict[str, Any], config: Config, state: SessionState) -> None:
    print()
    print(f"{profile['companion_name']} is ready.")
    print(
        f"Provider: {config.llm_provider} | Model: {config.model} | Input: {state.input_mode} | "
        f"Voice output: {'on' if state.voice_enabled else 'off'}"
    )
    print(
        f"TTS provider: {config.tts_provider} | TTS language: {config.tts_language} | "
        f"Speech recognition: {describe_stt_backend(config)} | "
        f"Language: {config.stt_language}"
    )
    if config.tts_provider == "xtts":
        print(
            f"XTTS voice: {describe_tts_voice(config)} | XTTS device: {get_xtts_device(config)}"
        )
        print(
            f"XTTS streaming: {'on' if config.xtts_stream_output else 'off'} "
            f"(buffer {config.xtts_stream_buffer_seconds:.1f}s) | "
            f"Reply limit: {config.llm_num_predict} tokens"
        )
    else:
        print(
            f"gTTS voice: {describe_tts_voice(config)} | "
            f"Reply limit: {config.llm_num_predict} tokens"
        )
    print(
        f"Web browsing: {'on' if config.web_browsing_enabled else 'off'} | "
        f"Auto-search: {'on' if config.web_auto_search else 'off'} | "
        f"Provider: {config.web_search_provider} | "
        f"Max results: {config.web_max_results}"
    )
    print(
        f"Media region: {config.media_region} | "
        f"Default music: {config.music_provider_default}"
    )
    if config.music_provider_default == "soundcloud":
        print(f"SoundCloud stream endpoint: {config.soundcloud_stream_endpoint}")
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
        "Commands: /help, /mode <voice|text>, /listen, /ask, /recalibrate, /mics, "
        "/mic <index|default>, /tts [xtts|gtts], /speakers, /speaker <name>, /voice [on|off], "
        "/web [on|off|auto on|auto off|clear|<query>], /play <query>, /radio <station>, /music <query>, /pause, /resume, /stop, "
        "/performance, /profiles, /profile, /profile use <id>, "
        "/name <new name>, /me <your name>, /remember <fact>, "
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
    print("/ask                    Alias for /listen")
    print("/recalibrate            Relearn the room noise before listening")
    print("/mics                   List available microphone devices")
    print("/mic                    Show the selected microphone")
    print("/mic <index>            Choose a microphone from /mics")
    print("/mic default            Use the system default microphone")
    print("/tts                    Show the current TTS provider")
    print("/tts xtts               Use XTTS-v2 voice synthesis (default)")
    print("/tts gtts               Use Google gTTS voice synthesis")
    print("/speakers               List available XTTS built-in voices (XTTS mode)")
    print("/speaker                Show the current XTTS voice (XTTS mode)")
    print("/speaker <name>         Switch XTTS built-in voice (XTTS mode)")
    print("/voice                  Toggle spoken replies on or off")
    print("/voice on               Always speak replies")
    print("/voice off              Stop speaking replies")
    print("/web                    Show web browsing status")
    print("/web on                 Enable web browsing")
    print("/web off                Disable web browsing")
    print("/web auto on            Auto-search for likely web/current-event prompts")
    print("/web auto off           Disable auto web search")
    print("/web clear              Clear queued web context")
    print("/web <query>            Search now and use results on the next reply")
    print("/play <query>           Play radio or open music on the preferred platform")
    print("/radio <station>        Play a radio station using your preferred region")
    print("/music <query>          Search the default music platform")
    print("/pause                  Pause current media playback")
    print("/resume                 Resume paused media playback")
    print("/stop                   Stop current media playback")
    print("/performance            Show the auto-tuned performance profile")
    print("/profiles               List saved profiles")
    print("/profile                Show the current saved profile")
    print("/profile use <id>       Switch to a different saved profile")
    print("/name <new name>        Rename your companion")
    print("/me <your name>         Set your name")
    print("/remember <fact>        Save something important for future chats")
    print("/reminder               List saved reminders")
    print("/alarm                  List saved alarms")
    print("/alarm off              Turn off all alarms")
    print("/todo                   List to-do items")
    print("/todo done <n>          Mark to-do item #n as done/undone")
    print("/todo delete <n>        Delete to-do item #n")
    print("/shopping               List shopping items")
    print("/shopping done <n>      Toggle shopping item #n as got/need")
    print("/shopping clear         Remove all checked-off shopping items")
    print("/calendar               List upcoming calendar events")
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
        f"Active settings: provider {config.llm_provider} | reply limit {config.llm_num_predict} | "
        f"STT {describe_stt_backend(config)} | "
        f"TTS {config.tts_provider}"
    )
    if config.tts_provider == "xtts":
        print(f"XTTS device: {get_xtts_device(config)} at speed {config.xtts_speed:.2f}")
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


def parse_tts_provider(argument: str) -> str | None:
    normalized = argument.strip().lower()
    if normalized in {"xtts", "gtts", "google-tts", "google_tts", "google"}:
        return normalize_tts_provider(normalized)
    return None


def print_web_status(config: Config, state: SessionState) -> None:
    queued_query = state.pending_web_query or "none"
    queued_status = "yes" if state.pending_web_context else "no"
    print(
        "Web browsing: "
        f"{'on' if config.web_browsing_enabled else 'off'} | "
        f"Auto-search: {'on' if config.web_auto_search else 'off'} | "
        f"Provider: {config.web_search_provider} | "
        f"Max results: {config.web_max_results} | "
        f"Timeout: {config.web_timeout_seconds}s | "
        f"Region: {config.web_region} | "
        f"SafeSearch: {config.web_safesearch}"
    )
    if config.web_search_provider == "searxng":
        print(f"SearXNG URL: {config.web_search_url}")
    print(f"Queued web query: {queued_query} | Queued context ready: {queued_status}")


def handle_web_command(command: str, config: Config, state: SessionState) -> None:
    lowered = command.strip().lower()
    if lowered == "/web":
        print_web_status(config, state)
        return

    argument = command[4:].strip()
    if not argument:
        print_web_status(config, state)
        return

    lowered_argument = argument.lower()

    if lowered_argument in {"on", "off"}:
        config.web_browsing_enabled = lowered_argument == "on"
        if not config.web_browsing_enabled:
            state.pending_web_context = None
            state.pending_web_query = None
        print(
            f"Web browsing is now {'on' if config.web_browsing_enabled else 'off'}."
        )
        return

    if lowered_argument in {"clear", "reset"}:
        state.pending_web_context = None
        state.pending_web_query = None
        print("Cleared queued web context.")
        return

    if lowered_argument == "auto":
        print(
            f"Web auto-search is {'on' if config.web_auto_search else 'off'}."
        )
        return

    if lowered_argument.startswith("auto "):
        setting = parse_voice_setting(argument[5:])
        if setting is None:
            print("Use /web auto on or /web auto off.")
            return
        config.web_auto_search = setting
        print(f"Web auto-search is now {'on' if config.web_auto_search else 'off'}.")
        return

    if not config.web_browsing_enabled:
        print("Web browsing is off. Run /web on first.")
        return

    bundle = fetch_web_context(argument, config)
    state.pending_web_query = bundle.query
    state.pending_web_context = bundle.context
    print(
        f"Queued {bundle.result_count} web results for the next reply "
        f"(query: {bundle.query})."
    )


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
    if config.tts_provider != "xtts":
        print("XTTS speaker controls are only available when /tts xtts is active.")
        return

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

    if lowered in {"/listen", "/ask", "/voiceask"}:
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

    if lowered == "/tts":
        print(f"TTS provider is currently {config.tts_provider}.")
        return CommandResult(handled=True)

    if lowered.startswith("/tts "):
        selected_provider = parse_tts_provider(command[5:])
        if selected_provider is None:
            print("Use /tts xtts or /tts gtts.")
            return CommandResult(handled=True)
        config.tts_provider = selected_provider
        print(f"TTS provider is now {config.tts_provider}.")
        if config.tts_provider == "gtts":
            print("gTTS selected. XTTS speaker commands are disabled.")
        return CommandResult(handled=True)

    if lowered == "/speakers":
        if config.tts_provider != "xtts":
            print("XTTS speakers are only available when /tts xtts is active.")
        else:
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

    if lowered == "/web" or lowered.startswith("/web "):
        try:
            handle_web_command(command, config, state)
        except RuntimeError as exc:
            print(f"[Web] {exc}")
        return CommandResult(handled=True)

    if lowered.startswith("/play "):
        action = handle_media_request(f"play {command[6:].strip()}", profile, config)
        if action.handled:
            save_profile(profile)
            print(action.response)
        return CommandResult(handled=True)

    if lowered.startswith("/radio "):
        action = handle_media_request(f"play radio {command[7:].strip()}", profile, config)
        if action.handled:
            save_profile(profile)
            print(action.response)
        return CommandResult(handled=True)

    if lowered.startswith("/music "):
        action = handle_media_request(f"play {command[7:].strip()}", profile, config)
        if action.handled:
            save_profile(profile)
            print(action.response)
        return CommandResult(handled=True)

    if lowered in {"/pause", "/resume", "/stop"}:
        action = handle_media_request(lowered[1:], profile, config)
        if action.handled:
            print(action.response)
        return CommandResult(handled=True)

    if lowered == "/profile":
        print()
        print(json.dumps(profile, indent=2, ensure_ascii=False))
        print()
        return CommandResult(handled=True)

    if lowered.startswith("/profile use "):
        target_profile_id = command[13:].strip()
        if not target_profile_id:
            print("Use /profile use <profile_id>.")
            return CommandResult(handled=True)
        try:
            active_profile = set_active_profile(target_profile_id)
        except RuntimeError as exc:
            print(exc)
            return CommandResult(handled=True)
        profile.clear()
        profile.update(active_profile)
        print(f"Active profile is now {profile.get('profile_name', target_profile_id)}.")
        return CommandResult(handled=True)

    if lowered == "/profiles":
        print()
        print("Saved profiles:")
        for summary in list_profiles():
            suffix = " (active)" if summary["is_active"] else ""
            print(
                f"- {summary['profile_id']}: {summary['profile_name']} "
                f"[{summary['companion_name']}]"
                f"{suffix}"
            )
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

    if lowered == "/reminder":
        reminders = [r for r in list_reminders(profile) if not r.get("completed")]
        if not reminders:
            print("No upcoming reminders.")
        else:
            print()
            for i, r in enumerate(
                sorted(reminders, key=lambda x: x.get("due", "")), start=1
            ):
                print(f"  {i}. [{r.get('due', '?')}] {r.get('title', 'Untitled')}")
            print()
        return CommandResult(handled=True)

    if lowered == "/alarm":
        alarms = list_alarms(profile)
        active = [a for a in alarms if a.get("active")]
        if not active:
            print("No active alarms.")
        else:
            print()
            for i, a in enumerate(active, start=1):
                days = a.get("days")
                spec = a.get("specific_date", "")
                if spec:
                    schedule = f"on {spec}"
                elif days:
                    schedule = ", ".join(d.capitalize() for d in days)
                else:
                    schedule = "daily"
                print(f"  {i}. {a.get('label', 'Alarm')} — {schedule}")
            print()
        return CommandResult(handled=True)

    if lowered == "/alarm off":
        count = cancel_all_alarms(profile)
        save_profile(profile)
        print(f"Turned off {count} alarm(s)." if count else "No active alarms.")
        return CommandResult(handled=True)

    if lowered == "/todo":
        items = list_todos(profile)
        if not items:
            print("Your to-do list is empty.")
        else:
            print()
            for i, item in enumerate(items, start=1):
                marker = "✓" if item.get("done") else "•"
                print(f"  {i}. {marker} {item.get('text', '')}")
            print()
        return CommandResult(handled=True)

    if lowered.startswith("/todo done "):
        arg = command[11:].strip()
        try:
            n = int(arg) - 1
            items = list_todos(profile)
            if 0 <= n < len(items):
                toggle_todo(profile, items[n]["id"])
                save_profile(profile)
                state = "done" if items[n].get("done") is False else "undone"
                print(f"Marked '{items[n]['text']}' as {state}.")
            else:
                print(f"No to-do item #{n + 1}.")
        except ValueError:
            print("Use /todo done <number>.")
        return CommandResult(handled=True)

    if lowered.startswith("/todo delete "):
        arg = command[13:].strip()
        try:
            n = int(arg) - 1
            items = list_todos(profile)
            if 0 <= n < len(items):
                delete_todo(profile, items[n]["id"])
                save_profile(profile)
                print(f"Deleted '{items[n]['text']}'.")
            else:
                print(f"No to-do item #{n + 1}.")
        except ValueError:
            print("Use /todo delete <number>.")
        return CommandResult(handled=True)

    if lowered == "/shopping":
        items = list_shopping(profile)
        if not items:
            print("Your shopping list is empty.")
        else:
            print()
            for i, item in enumerate(items, start=1):
                marker = "✓" if item.get("done") else "•"
                print(f"  {i}. {marker} {item.get('text', '')}")
            print()
        return CommandResult(handled=True)

    if lowered.startswith("/shopping done "):
        arg = command[15:].strip()
        try:
            n = int(arg) - 1
            items = list_shopping(profile)
            if 0 <= n < len(items):
                toggle_shopping_item(profile, items[n]["id"])
                save_profile(profile)
                state = "checked" if not items[n].get("done") else "unchecked"
                print(f"Marked '{items[n]['text']}' as {state}.")
            else:
                print(f"No shopping item #{n + 1}.")
        except ValueError:
            print("Use /shopping done <number>.")
        return CommandResult(handled=True)

    if lowered == "/shopping clear":
        clear_shopping_done(profile)
        save_profile(profile)
        print("Cleared checked shopping items.")
        return CommandResult(handled=True)

    if lowered == "/calendar":
        events = list_calendar_events(profile)
        if not events:
            print("Your calendar is empty.")
        else:
            print()
            for i, ev in enumerate(events, start=1):
                date_part = ev.get("date", "?")
                time_part = f" {ev.get('time', '')}" if ev.get("time") else ""
                print(f"  {i}. [{date_part}{time_part}] {ev.get('title', 'Untitled')}")
            print()
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


def _drain_scheduler_events(
    events: list[tuple[str, dict]],
    profile: dict,
    config: "Config",
    state: "SessionState",
) -> None:
    """Print and optionally speak any reminder/alarm events that just fired."""
    for kind, item in events:
        if kind == "reminder":
            msg = f"Reminder: {item.get('title', 'Untitled')}"
        else:
            msg = f"Alarm: {item.get('label', 'Untitled')}"
        print()
        print(f"[{kind.capitalize()}] {msg}")
        print()
        if state.voice_enabled:
            try:
                audio_path = speak_text(msg, config, state)
                if should_play_audio_after_synthesis(config):
                    play_audio_file(audio_path, config.speaker_device_index)
            except Exception:
                pass


def main() -> None:
    ensure_runtime_dirs()
    config = Config.from_env()
    profile = load_profile()
    state = SessionState(
        voice_enabled=config.voice_enabled,
        input_mode=config.input_mode,
    )

    scheduler = FeatureScheduler(profile, save_profile)
    scheduler.start()

    print_welcome(profile, config, state)

    while True:
        # Deliver any reminders / alarms that fired since the last iteration
        _drain_scheduler_events(scheduler.drain(), profile, config, state)

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
            scheduler.stop()
            print("See you soon.")
            break

        if not user_text:
            continue

        # ── Feature NLP (reminders, alarms, todo, shopping, calendar) ──────
        feature_result = handle_feature_request(user_text, profile)
        if feature_result.handled:
            if feature_result.save_needed:
                save_profile(profile)
            append_history("user", user_text)
            append_history("assistant", feature_result.response)
            print()
            print(console_safe_text(
                f"{profile['companion_name']}: {feature_result.response}"
            ))
            print()
            if state.voice_enabled:
                try:
                    audio_path = speak_text(feature_result.response, config, state)
                    if should_play_audio_after_synthesis(config):
                        play_audio_file(audio_path, config.speaker_device_index)
                except Exception:
                    pass
            continue
        # ───────────────────────────────────────────────────────────────────

        try:
            media_action = handle_media_request(user_text, profile, config)
        except RuntimeError as exc:
            print()
            print(f"[Media] {exc}")
            print()
            continue

        if media_action.handled:
            save_profile(profile)
            append_history("user", user_text)
            append_history("assistant", media_action.response)
            print()
            print(console_safe_text(f"{profile['companion_name']}: {media_action.response}"))
            print()
            continue

        web_context: str | None = None
        if config.web_browsing_enabled:
            web_query = state.pending_web_query
            if state.pending_web_context:
                web_context = state.pending_web_context
                state.pending_web_context = None
                state.pending_web_query = None
                if web_query:
                    print(f"[Web] Using queued results for: {web_query}")
            else:
                if not web_query:
                    inferred_query = extract_web_query_from_request(user_text)
                    if inferred_query:
                        web_query = inferred_query
                        print(f"[Web] Interpreted your request as lookup: {web_query}")
                if not web_query and config.web_auto_search and should_auto_search(user_text):
                    web_query = user_text
                if web_query:
                    try:
                        bundle = fetch_web_context(web_query, config)
                    except RuntimeError as exc:
                        print(f"[Web] {exc}")
                    else:
                        web_context = bundle.context
                        print(
                            f"[Web] Found {bundle.result_count} results for: {bundle.query}"
                        )
                    finally:
                        state.pending_web_query = None

        try:
            reply = request_reply(user_text, profile, config, web_context=web_context)
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
                if should_play_audio_after_synthesis(config):
                    play_audio_file(audio_path, config.speaker_device_index)
            except Exception as exc:
                latest_path = audio_path or "audio/latest_reply.(wav|mp3)"
                print(
                    "[Voice] Voice generation or playback failed. "
                    f"The latest audio file is at {latest_path}: {exc}"
                )
