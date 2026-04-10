# NovaAI

NovaAI is a local voice companion built on Ollama, faster-whisper, and XTTS-v2.
It can listen through your microphone, reply in text, speak back with streamed audio, and now run in either a terminal or a desktop GUI.

## Features

- Local Ollama chat with persistent recent history
- Microphone input with `SpeechRecognition` and local `faster-whisper`
- XTTS-v2 voice output with streamed playback
- Desktop GUI with hands-free controls and an app-level mic mute toggle
- Startup auto-tuning based on CPU, RAM, and CUDA GPU capability
- GitHub-backed version file plus optional startup auto-update
- Configurable companion profile and memory notes
- Windows-friendly setup with `setup.bat` that can install Python 3.11, Ollama, and the default model for you
- Modular Python package layout so contributors can work on one area at a time

## Quick Start

1. Run the full Windows setup:

```powershell
.\setup.bat
```

2. Start the GUI:

```powershell
.\launch_gui.bat
```

3. Or start the terminal version:

```powershell
.\.venv\Scripts\python.exe app.py
```

If Python 3.11 or Ollama are missing, `setup.bat` uses `winget` to install them first and accepts the required `winget` source/package agreements automatically. It also creates `.env`, creates `data/profile.json`, starts Ollama, pulls the model from `OLLAMA_MODEL`, and preloads the faster-whisper and XTTS model files so the first app launch is less annoying.

When `AUTO_UPDATE_CHECK=true`, NovaAI compares your local `VERSION` file to the latest `VERSION` on GitHub during startup. If `AUTO_UPDATE_INSTALL=true` too, clean non-git installs update themselves automatically and then restart.

You can also force a manual update at any time:

```powershell
.\update.bat
```

## Optional GPU Upgrade

If you have an NVIDIA GPU and want faster XTTS replies, upgrade PyTorch after setup:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 torch torchaudio torchcodec
```

## Project Layout

```text
NovaAI/
|-- app.py
|-- launch_gui.bat
|-- setup.bat
|-- update.bat
|-- requirements.txt
|-- LICENSE
|-- VERSION
|-- .env.example
|-- README.md
|-- data/
|   |-- profile.example.json
|-- novaai/
|   |-- __init__.py
|   |-- __main__.py
|   |-- audio_input.py
|   |-- chat.py
|   |-- cli.py
|   |-- config.py
|   |-- defaults.py
|   |-- gui.py
|   |-- launcher.py
|   |-- models.py
|   |-- performance.py
|   |-- paths.py
|   |-- storage.py
|   |-- tts.py
|   |-- updater.py
|   |-- utils.py
```

## Module Guide

- `novaai/config.py`: environment parsing and runtime configuration
- `novaai/storage.py`: profile and chat history loading/saving
- `novaai/chat.py`: system prompt construction and Ollama requests
- `novaai/audio_input.py`: microphone capture, STT, and mic calibration
- `novaai/tts.py`: XTTS generation, streamed playback, and WAV output
- `novaai/gui.py`: desktop chat window, hands-free controls, and mic mute
- `novaai/launcher.py`: entrypoint that chooses CLI or GUI mode
- `novaai/performance.py`: hardware detection and startup auto-tuning
- `novaai/updater.py`: GitHub version checks and optional self-update flow
- `novaai/cli.py`: command handling and the main terminal loop

## GUI Controls

- `Listen Now`: capture one spoken turn immediately
- `Hands-free`: keep listening after each reply
- `Mic: Live/Muted`: block new microphone captures without closing the app
- `Voice Replies`: toggle spoken output on or off
- `Recalibrate Mic`: relearn room noise for the current microphone
- `Show Performance`: post the active hardware profile in the chat panel
- `Clear History`: delete saved conversation history

## Commands

- `/help` shows commands
- `/mode voice` turns on hands-free microphone input
- `/mode text` switches back to typing
- `/listen` captures one spoken turn immediately
- `/recalibrate` relearns room noise before listening
- `/mics` lists available microphone devices
- `/mic <index>` chooses a microphone
- `/mic default` switches back to the system default microphone
- `/speakers` lists built-in XTTS voices
- `/speaker <name>` switches XTTS voice
- `/voice` toggles spoken replies on and off
- `/performance` shows the detected hardware and active performance profile
- `/profile` shows the saved companion profile
- `/name <new name>` renames the companion
- `/me <your name>` saves your name
- `/remember <fact>` stores a memory note
- `/reset` clears conversation history
- `/exit` quits the app

## Configuration Highlights

- `AUTO_TUNE_PERFORMANCE`: enable or disable startup auto-tuning
- `AUTO_TUNE_GOAL`: choose `speed`, `balanced`, or `quality`
- `AUTO_UPDATE_CHECK`: check the GitHub `VERSION` file on startup
- `AUTO_UPDATE_INSTALL`: auto-install GitHub updates when the local copy is behind
- `AUTO_UPDATE_CACHE_SECONDS`: reuse the last update check result for this many seconds
- `HF_HUB_DISABLE_SYMLINKS_WARNING`: suppress the Windows symlink cache warning from Hugging Face
- `NOVA_GITHUB_REPO`: override the GitHub repo slug used for update checks
- `NOVA_GITHUB_BRANCH`: override the GitHub branch used for update checks
- `OLLAMA_MODEL`: the Ollama chat model name
- `OLLAMA_NUM_PREDICT`: reply token budget
- `VOICE_ENABLED`: whether spoken replies start enabled (default is `false`)
- `XTTS_STREAM_OUTPUT`: stream speech while audio is generating
- `XTTS_CHUNK_MAX_CHARS`: safe per-chunk XTTS text limit
- `XTTS_MAX_TEXT_CHARS`: maximum total spoken text for one reply
- `STT_USE_GPU`: manual fallback if auto-tune is disabled
- `STT_MODEL`: faster-whisper model size, such as `small.en` or `medium.en`
- `MIC_DEVICE_INDEX`: manually pin a microphone from `/mics`
- `SPEAKER_DEVICE_INDEX`: pin a specific speaker/output device for playback

## Notes

- XTTS-v2 downloads large model files the first time it is used.
- `faster-whisper` downloads its speech model the first time it is used.
- `setup.bat` now preloads those model files during setup so most users should not see those downloads on first launch anymore.
- Auto-update is conservative on purpose. If NovaAI sees a git checkout with local edits, it skips self-updating instead of risking your work.
- The GUI mic mute is app-level, which means it stops NovaAI from starting new listens. It does not change the Windows system microphone mute state.
- With auto-tune on, NovaAI overrides a few performance-sensitive values at startup so the app matches the current machine better.
- If you want to lock in your own values, set `AUTO_TUNE_PERFORMANCE=false` in `.env`.
- Voice output is saved to `audio/latest_reply.wav` even when playback fails.
- Runtime data like `.env`, `data/profile.json`, `data/history.jsonl`, and generated audio are ignored by git.

## Contributing

The project is intentionally split into modules so different contributors can work in parallel without constantly editing one giant file. A good starting point is:

- voice or mic issues: `novaai/audio_input.py`
- personality or response logic: `novaai/chat.py`
- XTTS or playback issues: `novaai/tts.py`
- command flow or app behavior: `novaai/cli.py`

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
