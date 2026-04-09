from __future__ import annotations

from typing import Any

import numpy as np
import sounddevice as sd
import speech_recognition as sr
import torch

from .config import Config
from .models import SessionState, SpeechCapture, UserTurn
from .utils import console_safe_text


class SoundDeviceStream:
    def __init__(self, raw_stream: sd.RawInputStream):
        self.raw_stream = raw_stream

    def read(self, size: int) -> bytes:
        data, _overflowed = self.raw_stream.read(size)
        return bytes(data)

    def close(self) -> None:
        try:
            self.raw_stream.stop()
        except Exception:
            pass
        self.raw_stream.close()


class SoundDeviceMicrophone(sr.AudioSource):
    def __init__(
        self,
        device_index: int | None = None,
        sample_rate: int | None = None,
        chunk_size: int = 1024,
    ):
        assert device_index is None or isinstance(device_index, int)
        assert sample_rate is None or (
            isinstance(sample_rate, int) and sample_rate > 0
        )
        assert isinstance(chunk_size, int) and chunk_size > 0

        device_info = resolve_input_device_info(device_index)
        self.device_index = device_info["index"]
        self.device_name = device_info["name"]
        default_sample_rate = device_info["default_sample_rate"]

        self.SAMPLE_WIDTH = 2
        self.SAMPLE_RATE = sample_rate or default_sample_rate
        self.CHUNK = chunk_size
        self.stream: SoundDeviceStream | None = None
        self._raw_stream: sd.RawInputStream | None = None

    def __enter__(self) -> "SoundDeviceMicrophone":
        assert self.stream is None, "This audio source is already inside a context manager"
        try:
            self._raw_stream = sd.RawInputStream(
                samplerate=self.SAMPLE_RATE,
                blocksize=self.CHUNK,
                device=self.device_index,
                channels=1,
                dtype="int16",
            )
            self._raw_stream.start()
        except Exception as exc:
            raise RuntimeError(
                f"Could not open microphone '{self.device_name}'. {exc}"
            ) from exc

        self.stream = SoundDeviceStream(self._raw_stream)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.stream is not None:
            self.stream.close()
        self.stream = None
        self._raw_stream = None


def get_stt_device(config: Config) -> str:
    if config.stt_use_gpu and torch.cuda.is_available():
        return "cuda"
    return "cpu"


def get_stt_compute_type(config: Config) -> str:
    if config.stt_compute_type and config.stt_compute_type not in {"auto", "default"}:
        return config.stt_compute_type
    if get_stt_device(config) == "cuda":
        return "float16"
    return "int8"


def get_default_input_device_index() -> int | None:
    default_device = sd.default.device
    if isinstance(default_device, (list, tuple)):
        if not default_device:
            return None
        candidate = default_device[0]
    else:
        candidate = default_device

    if candidate is None:
        return None

    try:
        candidate_index = int(candidate)
    except (TypeError, ValueError):
        return None

    if candidate_index < 0:
        return None

    return candidate_index


def resolve_input_device_info(device_index: int | None) -> dict[str, Any]:
    try:
        if device_index is None:
            device = sd.query_devices(kind="input")
            resolved_index = get_default_input_device_index()
        else:
            device = sd.query_devices(device_index, "input")
            resolved_index = device_index
    except Exception as exc:
        chosen = (
            "the default microphone"
            if device_index is None
            else f"microphone #{device_index}"
        )
        raise RuntimeError(
            f"I couldn't access {chosen}. Use /mics to list available input devices."
        ) from exc

    device_name = str(device.get("name", "Input device"))
    default_sample_rate = device.get("default_samplerate")
    if not isinstance(default_sample_rate, (int, float)) or default_sample_rate <= 0:
        raise RuntimeError(
            f"The microphone '{device_name}' did not report a valid sample rate."
        )

    return {
        "index": resolved_index,
        "name": device_name,
        "default_sample_rate": int(default_sample_rate),
    }


def list_input_devices() -> list[dict[str, Any]]:
    try:
        devices = sd.query_devices()
    except Exception as exc:
        raise RuntimeError(f"I couldn't list microphone devices. {exc}") from exc

    default_index = get_default_input_device_index()
    input_devices: list[dict[str, Any]] = []
    for index, device in enumerate(devices):
        max_input_channels = device.get("max_input_channels", 0)
        if isinstance(max_input_channels, (int, float)) and max_input_channels > 0:
            input_devices.append(
                {
                    "index": index,
                    "name": str(device.get("name", "Input device")),
                    "is_default": index == default_index,
                }
            )
    return input_devices


def describe_selected_microphone(config: Config) -> str:
    try:
        device_info = resolve_input_device_info(config.mic_device_index)
    except RuntimeError:
        if config.mic_device_index is None:
            return "default microphone"
        return f"microphone #{config.mic_device_index}"

    if device_info["index"] is None:
        return f"default microphone ({device_info['name']})"

    if config.mic_device_index is None:
        return f"default microphone ({device_info['name']})"

    return f"#{device_info['index']} ({device_info['name']})"


def get_speech_recognizer_signature(config: Config) -> tuple[Any, ...]:
    return (
        config.mic_device_index,
        config.mic_sample_rate,
        config.mic_chunk_size,
        config.stt_energy_threshold,
        config.stt_dynamic_energy_threshold,
        config.stt_pause_threshold_seconds,
        config.stt_non_speaking_duration_seconds,
    )


def build_speech_recognizer(config: Config) -> sr.Recognizer:
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = max(50, config.stt_energy_threshold)
    recognizer.dynamic_energy_threshold = config.stt_dynamic_energy_threshold
    recognizer.pause_threshold = max(0.5, config.stt_pause_threshold_seconds)
    recognizer.non_speaking_duration = min(
        recognizer.pause_threshold,
        max(0.5, config.stt_non_speaking_duration_seconds),
    )
    recognizer.phrase_threshold = 0.2
    return recognizer


def ensure_speech_recognizer(config: Config, state: SessionState) -> sr.Recognizer:
    signature = get_speech_recognizer_signature(config)
    if (
        state.speech_recognizer is None
        or state.speech_recognizer_signature != signature
    ):
        state.speech_recognizer = build_speech_recognizer(config)
        state.speech_recognizer_signature = signature
        state.mic_calibrated = False
    return state.speech_recognizer


def get_stt_model_signature(config: Config) -> tuple[Any, ...]:
    return (
        config.stt_provider,
        config.stt_model,
        get_stt_device(config),
        get_stt_compute_type(config),
    )


def ensure_stt_model(config: Config, state: SessionState) -> Any:
    if config.stt_provider != "faster-whisper":
        return None

    signature = get_stt_model_signature(config)
    if state.stt_model_instance is not None and state.stt_model_signature == signature:
        return state.stt_model_instance

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        ) from exc

    try:
        state.stt_model_instance = WhisperModel(
            config.stt_model,
            device=get_stt_device(config),
            compute_type=get_stt_compute_type(config),
        )
        state.stt_model_signature = signature
        return state.stt_model_instance
    except Exception as exc:
        raise RuntimeError(
            f"I couldn't load the speech model '{config.stt_model}'. {exc}"
        ) from exc


def recalibrate_microphone(
    config: Config,
    state: SessionState,
    announce: bool = True,
) -> None:
    recognizer = ensure_speech_recognizer(config, state)
    if config.stt_ambient_duration_seconds <= 0:
        state.mic_calibrated = True
        return

    if announce:
        print()
        print(
            f"[Mic] Calibrating {describe_selected_microphone(config)} for "
            f"{config.stt_ambient_duration_seconds:.1f}s. Stay quiet for a moment."
        )

    with SoundDeviceMicrophone(
        device_index=config.mic_device_index,
        sample_rate=config.mic_sample_rate,
        chunk_size=config.mic_chunk_size,
    ) as source:
        recognizer.adjust_for_ambient_noise(
            source, duration=config.stt_ambient_duration_seconds
        )

    state.mic_calibrated = True
    if announce:
        print("[Mic] Calibration complete.")


def print_input_devices() -> None:
    devices = list_input_devices()
    print()
    if not devices:
        print("No microphone input devices were found.")
        print()
        return

    print("Available microphones:")
    for device in devices:
        suffix = " (default)" if device["is_default"] else ""
        print(f"{device['index']}: {device['name']}{suffix}")
    print()


def describe_stt_backend(config: Config) -> str:
    if config.stt_provider == "google":
        return "google"
    return (
        f"faster-whisper ({config.stt_model}, "
        f"{get_stt_device(config)}/{get_stt_compute_type(config)})"
    )


def normalize_stt_language_for_whisper(language: str) -> str | None:
    normalized = language.strip().lower()
    if not normalized or normalized == "auto":
        return None
    if "-" in normalized:
        normalized = normalized.split("-", 1)[0]
    return normalized


def transcribe_audio_with_faster_whisper(
    audio: sr.AudioData,
    config: Config,
    state: SessionState,
) -> tuple[str, str]:
    model = ensure_stt_model(config, state)
    whisper_language = normalize_stt_language_for_whisper(config.stt_language)
    audio_bytes = audio.get_raw_data(convert_rate=16000, convert_width=2)
    audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
    audio_array /= 32768.0

    segments, info = model.transcribe(
        audio_array,
        language=whisper_language,
        task="transcribe",
        beam_size=config.stt_beam_size,
        best_of=max(config.stt_beam_size, config.stt_best_of),
        vad_filter=config.stt_vad_filter,
        condition_on_previous_text=False,
        without_timestamps=True,
        temperature=0.0,
    )

    text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
    detected_language = getattr(info, "language", None) or whisper_language or ""
    return text.strip(), str(detected_language)


def transcribe_audio_with_google(
    recognizer: sr.Recognizer,
    audio: sr.AudioData,
    config: Config,
) -> tuple[str, str]:
    try:
        text = recognizer.recognize_google(audio, language=config.stt_language).strip()
    except sr.UnknownValueError:
        return "", config.stt_language
    except sr.RequestError as exc:
        raise RuntimeError(
            "Speech recognition could not reach the recognition service. "
            "Check your internet connection."
        ) from exc

    return text, config.stt_language


def recognize_speech(
    config: Config,
    state: SessionState,
    announce: bool = True,
) -> SpeechCapture:
    recognizer = ensure_speech_recognizer(config, state)
    if not state.mic_calibrated:
        recalibrate_microphone(config, state, announce=announce)

    with SoundDeviceMicrophone(
        device_index=config.mic_device_index,
        sample_rate=config.mic_sample_rate,
        chunk_size=config.mic_chunk_size,
    ) as source:
        try:
            audio = recognizer.listen(
                source,
                timeout=config.stt_timeout_seconds,
                phrase_time_limit=config.stt_phrase_time_limit_seconds,
            )
        except sr.WaitTimeoutError:
            return SpeechCapture(
                status="timeout",
                language=config.stt_language,
                device_name=source.device_name,
            )

    try:
        if config.stt_provider == "google":
            text, detected_language = transcribe_audio_with_google(
                recognizer, audio, config
            )
        else:
            text, detected_language = transcribe_audio_with_faster_whisper(
                audio, config, state
            )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Speech recognition failed. {exc}") from exc

    if not text:
        return SpeechCapture(
            status="unknown",
            language=detected_language or config.stt_language,
            device_name=source.device_name,
            error="I heard audio, but I couldn't understand the words clearly.",
        )

    return SpeechCapture(
        status="ok",
        text=text,
        language=detected_language or config.stt_language,
        device_name=source.device_name,
    )


def capture_voice_turn(
    config: Config,
    profile: dict[str, Any],
    state: SessionState,
) -> UserTurn | None:
    print()
    print(
        f"[Listening] Speak to {profile['companion_name']} now with "
        f"{describe_selected_microphone(config)}."
    )

    result = recognize_speech(config, state)
    if result.status == "timeout":
        print("[Listening] I didn't hear anything that sounded like speech.")
        return None

    if result.status == "unknown":
        print("[Listening] I heard you, but I couldn't understand the words.")
        return None

    if result.status != "ok":
        raise RuntimeError(
            result.error or "Speech recognition did not return a usable result."
        )

    print(console_safe_text(f"{profile['user_name']}: {result.text}"))
    return UserTurn(text=result.text, from_voice=True)
