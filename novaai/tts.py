from __future__ import annotations

import ctypes
import os
import queue
import re
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
import torch
from TTS.api import TTS

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
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=2048,
        latency="high",
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
            audio_stream.write(
                np.ascontiguousarray(audio_chunk.reshape(-1, 1), dtype=np.float32)
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


def play_audio_file(audio_path: Path) -> None:
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
