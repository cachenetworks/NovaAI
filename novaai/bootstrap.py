from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from .audio_input import ensure_stt_model  # noqa: E402
from .config import Config  # noqa: E402
from .models import SessionState  # noqa: E402
from .storage import ensure_runtime_dirs, load_profile  # noqa: E402
from .tts import ensure_xtts_model  # noqa: E402


def preload_runtime_assets() -> None:
    ensure_runtime_dirs()
    config = Config.from_env()
    load_profile()
    state = SessionState(
        voice_enabled=config.voice_enabled,
        input_mode=config.input_mode,
    )

    if config.stt_provider == "faster-whisper":
        ensure_stt_model(config, state)

    if config.tts_provider == "xtts":
        ensure_xtts_model(config, state)


def main() -> None:
    preload_runtime_assets()


if __name__ == "__main__":
    main()
