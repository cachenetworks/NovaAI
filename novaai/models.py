from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

# These are heavy, optional, voice-only dependencies. They are referenced here
# only as type annotations, and `from __future__ import annotations` keeps those
# annotations as strings that are never evaluated at runtime — so importing them
# under TYPE_CHECKING lets NovaAI run text-only (CLI / headless web) without
# torch, coqui-tts, or PortAudio installed.
if TYPE_CHECKING:
    import speech_recognition as sr
    import torch
    from TTS.api import TTS


@dataclass
class SessionState:
    voice_enabled: bool
    input_mode: str
    pending_web_context: str | None = None
    pending_web_query: str | None = None
    speech_recognizer: sr.Recognizer | None = None
    speech_recognizer_signature: tuple[Any, ...] | None = None
    mic_calibrated: bool = False
    stt_model_instance: Any = None
    stt_model_signature: tuple[Any, ...] | None = None
    xtts_model: TTS | None = None
    xtts_device: str | None = None
    xtts_speakers: list[str] | None = None
    xtts_cached_voice_key: str | None = None
    xtts_cached_conditioning: tuple[torch.Tensor, torch.Tensor] | None = None


@dataclass
class UserTurn:
    text: str
    from_voice: bool


@dataclass
class CommandResult:
    handled: bool
    injected_turn: UserTurn | None = None
    should_exit: bool = False


@dataclass
class SpeechCapture:
    status: str
    text: str = ""
    confidence: float | None = None
    language: str = ""
    device_name: str = ""
    error: str = ""
