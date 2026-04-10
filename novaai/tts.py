from __future__ import annotations

import ctypes
import os
import queue
import re
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
import torch
from TTS.api import TTS

from .audio_input import get_hostapi_names, normalize_audio_device_name
from .config import Config
from .models import SessionState
from .paths import AUDIO_DIR, ROOT_DIR, XTTS_STREAM_END
from .utils import console_safe_text


def resolve_optional_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    candidate = Path(path_value)
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate
    return candidate


def get_xtts_device(config: Config) -> str:
    if config.xtts_use_gpu and torch.cuda.is_available():
        return "cuda"
    return "cpu"


def get_default_output_device_index() -> int | None:
    default_device = sd.default.device
    if isinstance(default_device, (list, tuple)):
        if len(default_device) < 2:
            return None
        candidate = default_device[1]
    else:
        candidate = None

    if candidate is None:
        return None

    try:
        candidate_index = int(candidate)
    except (TypeError, ValueError):
        return None

    if candidate_index < 0:
        return None
    return candidate_index


def resolve_output_device_info(device_index: int | None) -> dict[str, Any]:
    try:
        if device_index is None:
            device = sd.query_devices(kind="output")
            resolved_index = get_default_output_device_index()
        else:
            device = sd.query_devices(device_index, "output")
            resolved_index = device_index
    except Exception as exc:
        chosen = (
            "the default speaker"
            if device_index is None
            else f"speaker #{device_index}"
        )
        raise RuntimeError(
            f"I couldn't access {chosen}. Refresh devices and try another option."
        ) from exc

    device_name = str(device.get("name", "Output device"))
    default_sample_rate = device.get("default_samplerate")
    if not isinstance(default_sample_rate, (int, float)) or default_sample_rate <= 0:
        raise RuntimeError(
            f"The speaker '{device_name}' did not report a valid sample rate."
        )

    return {
        "index": resolved_index,
        "name": normalize_audio_device_name(device_name),
        "default_sample_rate": int(default_sample_rate),
    }


def output_device_name_key(device_name: str) -> str:
    normalized = normalize_audio_device_name(device_name).lower()
    simplified = re.sub(r"[^a-z0-9]+", "", normalized)
    if not simplified:
        return normalized
    return simplified[:28]


def resolve_output_hostapi_name(
    device: dict[str, Any],
    hostapi_names: list[str],
) -> str:
    hostapi_index = device.get("hostapi")
    if (
        isinstance(hostapi_index, int)
        and 0 <= hostapi_index < len(hostapi_names)
    ):
        return hostapi_names[hostapi_index]
    return ""


def choose_compatible_output_device_index(
    output_device_index: int | None,
) -> int | None:
    if output_device_index is None:
        return None

    try:
        all_devices = sd.query_devices()
        selected_device = sd.query_devices(output_device_index, "output")
    except Exception:
        return output_device_index

    hostapi_names = get_hostapi_names()
    selected_hostapi = resolve_output_hostapi_name(selected_device, hostapi_names)
    if selected_hostapi not in {"Windows WASAPI", "Windows WDM-KS", "WDM-KS"}:
        return output_device_index

    selected_key = output_device_name_key(str(selected_device.get("name", "")))
    if not selected_key:
        return output_device_index

    hostapi_priority = {
        "Windows DirectSound": 0,
        "MME": 1,
        "Windows WASAPI": 2,
        "Windows WDM-KS": 3,
        "WDM-KS": 3,
        "ASIO": 4,
    }
    best_index = output_device_index
    best_score = (hostapi_priority.get(selected_hostapi, 9), output_device_index)

    for index, device in enumerate(all_devices):
        max_output_channels = device.get("max_output_channels", 0)
        if not isinstance(max_output_channels, (int, float)) or max_output_channels <= 0:
            continue

        device_key = output_device_name_key(str(device.get("name", "")))
        if device_key != selected_key:
            continue

        hostapi_name = resolve_output_hostapi_name(device, hostapi_names)
        score = (hostapi_priority.get(hostapi_name, 9), index)
        if score < best_score:
            best_score = score
            best_index = index

    return best_index


def list_output_devices_compact(max_devices: int = 24) -> list[dict[str, Any]]:
    try:
        devices = sd.query_devices()
    except Exception as exc:
        raise RuntimeError(f"I couldn't list speaker devices. {exc}") from exc

    default_index = get_default_output_device_index()
    hostapi_names = get_hostapi_names()
    hostapi_priority = {
        # Favor the shared-mode APIs first for compatibility.
        "Windows DirectSound": 0,
        "MME": 1,
        "Windows WASAPI": 2,
        "WDM-KS": 3,
        "ASIO": 3,
        "Windows WDM-KS": 4,
    }
    ignored_names = {
        "primary sound driver",
        "microsoft sound mapper - output",
    }
    compact: dict[str, dict[str, Any]] = {}
    for index, device in enumerate(devices):
        max_output_channels = device.get("max_output_channels", 0)
        if not isinstance(max_output_channels, (int, float)) or max_output_channels <= 0:
            continue

        raw_name = str(device.get("name", "Output device"))
        normalized_name = normalize_audio_device_name(raw_name)
        if normalized_name.strip().lower() in ignored_names:
            continue

        hostapi_index = device.get("hostapi")
        hostapi_name = (
            hostapi_names[int(hostapi_index)]
            if isinstance(hostapi_index, int)
            and 0 <= hostapi_index < len(hostapi_names)
            else ""
        )
        candidate = {
            "index": index,
            "name": normalized_name,
            "hostapi": hostapi_name,
            "is_default": index == default_index,
            "_score": (
                0 if index == default_index else 1,
                hostapi_priority.get(hostapi_name, 9),
                -len(normalized_name),
                index,
            ),
        }

        existing = compact.get(output_device_name_key(normalized_name))
        if existing is None or candidate["_score"] < existing["_score"]:
            compact[output_device_name_key(normalized_name)] = candidate

    devices_out = sorted(
        compact.values(),
        key=lambda item: (0 if item["is_default"] else 1, item["name"].lower()),
    )
    if max_devices > 0:
        devices_out = devices_out[:max_devices]
    for item in devices_out:
        item.pop("_score", None)
    return devices_out


def describe_selected_speaker(config: Config) -> str:
    try:
        device_info = resolve_output_device_info(config.speaker_device_index)
    except RuntimeError:
        if config.speaker_device_index is None:
            return "default speaker"
        return f"speaker #{config.speaker_device_index}"

    if config.speaker_device_index is None:
        return f"default speaker ({device_info['name']})"
    return f"#{device_info['index']} ({device_info['name']})"


@dataclass(frozen=True)
class OutputPlaybackPlan:
    output_device_index: int | None
    sample_rate: int
    requires_resample: bool


class StreamingLinearResampler:
    def __init__(self, source_sample_rate: int, target_sample_rate: int) -> None:
        self.source_sample_rate = max(1, int(source_sample_rate))
        self.target_sample_rate = max(1, int(target_sample_rate))
        self._step = float(self.source_sample_rate) / float(self.target_sample_rate)
        self._buffer = np.empty((0, 1), dtype=np.float32)
        self._next_source_position = 0.0

    def process(self, audio: np.ndarray) -> np.ndarray:
        audio_array = np.asarray(audio, dtype=np.float32).reshape(-1, 1)
        if audio_array.size == 0:
            return np.empty((0,), dtype=np.float32)

        if self._buffer.size == 0:
            self._buffer = audio_array.copy()
        else:
            self._buffer = np.concatenate([self._buffer, audio_array], axis=0)

        resampled = self._consume_available()
        return np.ascontiguousarray(resampled.reshape(-1), dtype=np.float32)

    def flush(self) -> np.ndarray:
        if self._buffer.size == 0:
            return np.empty((0,), dtype=np.float32)

        # Pad with the final frame once so the last interpolation window can finish cleanly.
        self._buffer = np.concatenate([self._buffer, self._buffer[-1:, :]], axis=0)
        resampled = self._consume_available()
        self._buffer = np.empty((0, 1), dtype=np.float32)
        self._next_source_position = 0.0
        return np.ascontiguousarray(resampled.reshape(-1), dtype=np.float32)

    def _consume_available(self) -> np.ndarray:
        if self._buffer.shape[0] < 2:
            return np.empty((0, 1), dtype=np.float32)

        outputs: list[np.ndarray] = []
        max_source_position = float(self._buffer.shape[0] - 1)
        while self._next_source_position <= max_source_position:
            low_index = int(self._next_source_position)
            high_index = min(low_index + 1, self._buffer.shape[0] - 1)
            blend = self._next_source_position - low_index
            sample = (
                (1.0 - blend) * self._buffer[low_index]
                + blend * self._buffer[high_index]
            ).astype(np.float32)
            outputs.append(sample)
            self._next_source_position += self._step

        consumed_prefix = max(0, int(self._next_source_position) - 1)
        if consumed_prefix > 0:
            self._buffer = self._buffer[consumed_prefix:, :]
            self._next_source_position -= consumed_prefix

        if not outputs:
            return np.empty((0, 1), dtype=np.float32)
        return np.stack(outputs, axis=0)


def can_use_output_sample_rate(
    output_device_index: int | None,
    sample_rate: int,
    channels: int = 1,
) -> bool:
    try:
        sd.check_output_settings(
            device=output_device_index,
            channels=max(1, int(channels)),
            dtype="float32",
            samplerate=max(8000, int(sample_rate)),
        )
    except Exception:
        return False
    return True


def choose_output_playback_plan(
    output_device_index: int | None,
    source_sample_rate: int,
    channels: int = 1,
) -> OutputPlaybackPlan:
    resolved_output_device_index = choose_compatible_output_device_index(
        output_device_index
    )
    normalized_source_rate = max(8000, int(source_sample_rate))
    device_default_rate: int | None = None
    try:
        device_info = resolve_output_device_info(resolved_output_device_index)
        device_default_rate = max(8000, int(device_info["default_sample_rate"]))
    except RuntimeError:
        device_default_rate = None

    # Prefer the device's native default rate first. A few Windows drivers "accept"
    # uncommon rates but still run the stream at their native mode, which can sound
    # chipmunked. Using the default device rate avoids that class of mismatch.
    if device_default_rate is not None and can_use_output_sample_rate(
        resolved_output_device_index,
        device_default_rate,
        channels=channels,
    ):
        return OutputPlaybackPlan(
            output_device_index=resolved_output_device_index,
            sample_rate=device_default_rate,
            requires_resample=device_default_rate != normalized_source_rate,
        )

    if can_use_output_sample_rate(
        resolved_output_device_index,
        normalized_source_rate,
        channels=channels,
    ):
        return OutputPlaybackPlan(
            output_device_index=resolved_output_device_index,
            sample_rate=normalized_source_rate,
            requires_resample=False,
        )

    candidate_rates: list[int] = []
    if device_default_rate is not None:
        candidate_rates.append(device_default_rate)

    candidate_rates.extend([48000, 44100])
    seen_rates = {normalized_source_rate}
    for candidate_rate in candidate_rates:
        if candidate_rate in seen_rates:
            continue
        seen_rates.add(candidate_rate)
        if can_use_output_sample_rate(
            resolved_output_device_index,
            candidate_rate,
            channels=channels,
        ):
            return OutputPlaybackPlan(
                output_device_index=resolved_output_device_index,
                sample_rate=candidate_rate,
                requires_resample=candidate_rate != normalized_source_rate,
            )

    fallback_rate = next(
        (
            candidate_rate
            for candidate_rate in candidate_rates
            if candidate_rate != normalized_source_rate
        ),
        normalized_source_rate,
    )
    return OutputPlaybackPlan(
        output_device_index=resolved_output_device_index,
        sample_rate=fallback_rate,
        requires_resample=fallback_rate != normalized_source_rate,
    )


def resample_audio_for_output(
    audio: np.ndarray,
    source_sample_rate: int,
    target_sample_rate: int,
) -> np.ndarray:
    audio_array = np.asarray(audio, dtype=np.float32)
    if audio_array.size == 0 or source_sample_rate == target_sample_rate:
        return np.ascontiguousarray(audio_array, dtype=np.float32)

    squeeze_output = False
    if audio_array.ndim == 1:
        audio_array = audio_array.reshape(-1, 1)
        squeeze_output = True

    source_length = audio_array.shape[0]
    if source_length == 1:
        repeated = np.repeat(
            audio_array,
            max(1, int(round(target_sample_rate / source_sample_rate))),
            axis=0,
        )
        return repeated.reshape(-1) if squeeze_output else repeated

    target_length = max(
        1,
        int(round(source_length * float(target_sample_rate) / float(source_sample_rate))),
    )
    source_positions = np.arange(source_length, dtype=np.float32)
    target_positions = np.linspace(
        0,
        source_length - 1,
        num=target_length,
        dtype=np.float32,
    )

    channels: list[np.ndarray] = []
    for channel_index in range(audio_array.shape[1]):
        channel = np.interp(
            target_positions,
            source_positions,
            audio_array[:, channel_index],
        ).astype(np.float32)
        channels.append(channel)

    resampled = np.stack(channels, axis=1)
    if squeeze_output:
        return np.ascontiguousarray(resampled.reshape(-1), dtype=np.float32)
    return np.ascontiguousarray(resampled, dtype=np.float32)


def ensure_xtts_model(config: Config, state: SessionState) -> TTS:
    desired_device = get_xtts_device(config)
    if state.xtts_model is None or state.xtts_device != desired_device:
        model = TTS(config.xtts_model_name, progress_bar=False)
        model.to(desired_device)
        state.xtts_model = model
        state.xtts_device = desired_device
        state.xtts_speakers = list(model.speakers or [])
        state.xtts_cached_voice_key = None
        state.xtts_cached_conditioning = None
    return state.xtts_model


def list_xtts_speakers(config: Config, state: SessionState) -> list[str]:
    model = ensure_xtts_model(config, state)
    speakers = list(model.speakers or [])
    state.xtts_speakers = speakers
    return speakers


def print_xtts_speakers(config: Config, state: SessionState) -> None:
    speakers = list_xtts_speakers(config, state)
    print()
    if not speakers:
        print("No built-in XTTS speakers were reported by the current model.")
        print()
        return

    print("Available XTTS speakers:")
    for speaker in speakers:
        suffix = " (current)" if speaker == config.xtts_speaker else ""
        print(console_safe_text(f"- {speaker}{suffix}"))
    print()


def describe_tts_voice(config: Config) -> str:
    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)
    if speaker_wav is not None:
        return f"reference voice file ({speaker_wav})"
    return config.xtts_speaker


def split_long_text_fragment(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
            continue

        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        chunks.append(current)
        current = word

    if current:
        chunks.append(current)

    return chunks


def split_text_for_xtts(text: str, max_chars: int) -> list[str]:
    normalized_text = " ".join(text.split())
    if not normalized_text:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", normalized_text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if not sentence:
            continue

        sentence_parts = split_long_text_fragment(sentence, max_chars)
        for part in sentence_parts:
            if not current:
                current = part
                continue

            candidate = f"{current} {part}"
            if len(candidate) <= max_chars:
                current = candidate
                continue

            chunks.append(current)
            current = part

    if current:
        chunks.append(current)

    return chunks or [normalized_text]


def trim_text_for_tts(text: str, max_chars: int) -> str:
    normalized_text = " ".join(text.split())
    if len(normalized_text) <= max_chars:
        return normalized_text

    trimmed = normalized_text[: max_chars + 1]
    boundary = max(
        trimmed.rfind(". "),
        trimmed.rfind("! "),
        trimmed.rfind("? "),
        trimmed.rfind(", "),
        trimmed.rfind("; "),
        trimmed.rfind(": "),
        trimmed.rfind(" "),
    )
    if boundary > 0:
        trimmed = trimmed[:boundary]
    else:
        trimmed = trimmed[:max_chars]

    return trimmed.rstrip(" ,;:")


def get_xtts_output_sample_rate(model: TTS) -> int:
    sample_rate = getattr(model.synthesizer, "output_sample_rate", None)
    if isinstance(sample_rate, int) and sample_rate > 0:
        return sample_rate

    audio_config = getattr(
        getattr(model.synthesizer.tts_model, "config", None), "audio", None
    )
    output_sample_rate = getattr(audio_config, "output_sample_rate", None)
    if isinstance(output_sample_rate, int) and output_sample_rate > 0:
        return output_sample_rate

    return 24000


def resolve_xtts_conditioning(
    config: Config,
    state: SessionState,
    model: TTS,
) -> tuple[torch.Tensor, torch.Tensor]:
    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)
    xtts_model = model.synthesizer.tts_model

    if speaker_wav is not None:
        if not speaker_wav.exists():
            raise RuntimeError(
                f"XTTS speaker reference file was not found: {speaker_wav}"
            )

        resolved_path = str(speaker_wav.resolve())
        cache_key = f"speaker_wav:{resolved_path}"
        if (
            state.xtts_cached_voice_key == cache_key
            and state.xtts_cached_conditioning is not None
        ):
            return state.xtts_cached_conditioning

        conditioning = xtts_model.get_conditioning_latents(audio_path=resolved_path)
        state.xtts_cached_voice_key = cache_key
        state.xtts_cached_conditioning = conditioning
        return conditioning

    available_speakers = state.xtts_speakers or list(model.speakers or [])
    if available_speakers and config.xtts_speaker not in available_speakers:
        raise RuntimeError(
            f"XTTS speaker '{config.xtts_speaker}' was not found. "
            "Run /speakers to list valid voices."
        )

    speaker_data = xtts_model.speaker_manager.speakers.get(config.xtts_speaker)
    if not speaker_data:
        raise RuntimeError(
            f"XTTS speaker '{config.xtts_speaker}' did not expose streaming data."
        )

    return speaker_data["gpt_cond_latent"], speaker_data["speaker_embedding"]


def write_wav_audio(
    audio_path: Path,
    audio_chunks: list[np.ndarray],
    sample_rate: int,
) -> Path:
    if not audio_chunks:
        raise RuntimeError("XTTS did not generate any audio.")

    full_audio = np.concatenate(audio_chunks)
    pcm_audio = np.clip(full_audio, -1.0, 1.0)
    pcm_audio = (pcm_audio * 32767.0).astype(np.int16)

    with wave.open(str(audio_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_audio.tobytes())

    return audio_path


def synthesize_xtts_to_file(
    text: str,
    config: Config,
    state: SessionState,
    model: TTS,
    output_path: Path,
) -> Path:
    speaker_wav = resolve_optional_path(config.xtts_speaker_wav)
    clipped_text = trim_text_for_tts(text, config.xtts_max_text_chars)
    text_chunks = split_text_for_xtts(clipped_text, config.xtts_chunk_max_chars)
    audio_chunks: list[np.ndarray] = []

    base_kwargs: dict[str, Any] = {
        "language": config.tts_language,
        "speed": config.xtts_speed,
        "split_sentences": False,
    }

    if speaker_wav is not None:
        if not speaker_wav.exists():
            raise RuntimeError(
                f"XTTS speaker reference file was not found: {speaker_wav}"
            )
        base_kwargs["speaker_wav"] = str(speaker_wav)
    else:
        available_speakers = state.xtts_speakers or list(model.speakers or [])
        if available_speakers and config.xtts_speaker not in available_speakers:
            raise RuntimeError(
                f"XTTS speaker '{config.xtts_speaker}' was not found. "
                "Run /speakers to list valid voices."
            )
        base_kwargs["speaker"] = config.xtts_speaker

    for text_chunk in text_chunks:
        chunk_audio = model.tts(text=text_chunk, **base_kwargs)
        audio_chunks.append(np.asarray(chunk_audio, dtype=np.float32))

    return write_wav_audio(output_path, audio_chunks, get_xtts_output_sample_rate(model))


def produce_xtts_stream_chunks(
    text: str,
    config: Config,
    state: SessionState,
    model: TTS,
    chunk_queue: queue.SimpleQueue[object],
    producer_errors: list[Exception],
) -> None:
    xtts_model = model.synthesizer.tts_model

    try:
        gpt_cond_latent, speaker_embedding = resolve_xtts_conditioning(
            config, state, model
        )
        clipped_text = trim_text_for_tts(text, config.xtts_max_text_chars)
        for text_chunk in split_text_for_xtts(
            clipped_text, config.xtts_chunk_max_chars
        ):
            chunk_generator = xtts_model.inference_stream(
                text=text_chunk,
                language=config.tts_language,
                gpt_cond_latent=gpt_cond_latent,
                speaker_embedding=speaker_embedding,
                stream_chunk_size=config.xtts_stream_chunk_size,
                speed=config.xtts_speed,
                enable_text_splitting=False,
            )

            for chunk in chunk_generator:
                audio_chunk = chunk.detach().float().cpu().numpy().reshape(-1)
                if audio_chunk.size == 0:
                    continue
                chunk_queue.put(audio_chunk.copy())
    except Exception as exc:
        producer_errors.append(exc)
    finally:
        chunk_queue.put(XTTS_STREAM_END)


def stream_xtts_audio(
    text: str,
    config: Config,
    state: SessionState,
    model: TTS,
    output_path: Path,
) -> Path:
    sample_rate = get_xtts_output_sample_rate(model)
    playback_plan = choose_output_playback_plan(
        config.speaker_device_index,
        sample_rate,
    )
    audio_chunks: list[np.ndarray] = []
    chunk_queue: queue.SimpleQueue[object] = queue.SimpleQueue()
    producer_errors: list[Exception] = []
    producer_thread = threading.Thread(
        target=produce_xtts_stream_chunks,
        args=(text, config, state, model, chunk_queue, producer_errors),
        daemon=True,
    )
    producer_thread.start()

    target_buffer_samples = int(sample_rate * config.xtts_stream_buffer_seconds)
    buffered_chunks: list[np.ndarray] = []
    buffered_samples = 0
    stream_finished = False

    while buffered_samples < target_buffer_samples:
        chunk_or_end = chunk_queue.get()
        if chunk_or_end is XTTS_STREAM_END:
            stream_finished = True
            break
        assert isinstance(chunk_or_end, np.ndarray)
        buffered_chunks.append(chunk_or_end)
        buffered_samples += chunk_or_end.size

    audio_stream = sd.OutputStream(
        samplerate=playback_plan.sample_rate,
        channels=1,
        dtype="float32",
        blocksize=2048,
        latency="high",
        device=playback_plan.output_device_index,
    )
    stream_resampler = (
        StreamingLinearResampler(sample_rate, playback_plan.sample_rate)
        if playback_plan.requires_resample
        else None
    )

    try:
        audio_stream.start()
        pending_chunks = buffered_chunks

        while True:
            if pending_chunks:
                audio_chunk = pending_chunks.pop(0)
            elif stream_finished:
                break
            else:
                chunk_or_end = chunk_queue.get()
                if chunk_or_end is XTTS_STREAM_END:
                    stream_finished = True
                    break
                assert isinstance(chunk_or_end, np.ndarray)
                audio_chunk = chunk_or_end

            audio_chunks.append(audio_chunk)
            playback_chunk = (
                stream_resampler.process(audio_chunk)
                if stream_resampler is not None
                else np.ascontiguousarray(audio_chunk, dtype=np.float32)
            )
            if playback_chunk.size == 0:
                continue
            audio_stream.write(
                np.ascontiguousarray(playback_chunk.reshape(-1, 1), dtype=np.float32)
            )

        if stream_resampler is not None:
            final_chunk = stream_resampler.flush()
            if final_chunk.size > 0:
                audio_stream.write(
                    np.ascontiguousarray(final_chunk.reshape(-1, 1), dtype=np.float32)
                )
    finally:
        try:
            audio_stream.stop()
        except Exception:
            pass
        audio_stream.close()
        producer_thread.join()

    if producer_errors:
        raise RuntimeError(f"XTTS streaming failed. {producer_errors[0]}")

    return write_wav_audio(output_path, audio_chunks, sample_rate)


def speak_text(text: str, config: Config, state: SessionState) -> Path:
    cleaned_text = trim_text_for_tts(text, config.xtts_max_text_chars)
    output_path = AUDIO_DIR / "latest_reply.wav"
    model = ensure_xtts_model(config, state)

    if config.xtts_stream_output:
        return stream_xtts_audio(cleaned_text, config, state, model, output_path)

    return synthesize_xtts_to_file(cleaned_text, config, state, model, output_path)


def get_mci_error(error_code: int) -> str:
    buffer = ctypes.create_unicode_buffer(255)
    ctypes.windll.winmm.mciGetErrorStringW(error_code, buffer, len(buffer))
    return buffer.value or f"MCI error {error_code}"


def play_wav_with_sounddevice(
    audio_path: Path,
    output_device_index: int | None = None,
) -> None:
    with wave.open(str(audio_path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width != 2:
        raise RuntimeError(
            "Only 16-bit PCM WAV playback is supported for direct device output."
        )

    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels)
    else:
        audio = audio.reshape(-1, 1)

    playback_plan = choose_output_playback_plan(
        output_device_index,
        sample_rate,
        channels=channels,
    )
    playback_audio = (
        resample_audio_for_output(
            audio,
            sample_rate,
            playback_plan.sample_rate,
        )
        if playback_plan.requires_resample
        else np.ascontiguousarray(audio, dtype=np.float32)
    )

    try:
        sd.play(
            playback_audio,
            samplerate=playback_plan.sample_rate,
            device=playback_plan.output_device_index,
            blocking=True,
        )
    except Exception as exc:
        selected = (
            "the default speaker"
            if output_device_index is None
            else f"speaker #{output_device_index}"
        )
        raise RuntimeError(f"Could not play audio on {selected}. {exc}") from exc


def play_audio_file(
    audio_path: Path,
    output_device_index: int | None = None,
) -> None:
    if audio_path.suffix.lower() == ".wav":
        play_wav_with_sounddevice(audio_path, output_device_index)
        return

    if os.name != "nt":
        raise RuntimeError("Automatic audio playback is only implemented for Windows.")

    alias = "ai_companion_audio"
    winmm = ctypes.windll.winmm

    def send(command: str) -> None:
        error_code = winmm.mciSendStringW(command, None, 0, None)
        if error_code:
            raise RuntimeError(get_mci_error(error_code))

    try:
        send(f"close {alias}")
    except RuntimeError:
        pass

    try:
        if audio_path.suffix.lower() == ".wav":
            send(f'open "{audio_path}" type waveaudio alias {alias}')
        else:
            send(f'open "{audio_path}" type mpegvideo alias {alias}')
        send(f"play {alias} wait")
    finally:
        try:
            send(f"close {alias}")
        except RuntimeError:
            pass
