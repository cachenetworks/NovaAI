# NovaAI

NovaAI is a voice companion built around pluggable chat providers, faster-whisper, and XTTS-v2.
It can listen through your microphone, reply in text, speak back with streamed audio, and now run in either a terminal or a desktop GUI.

## Features

- Chat via Ollama or OpenAI-compatible endpoints such as OpenAI, LM Studio, and LiteLLM
- Optional web browsing support (manual `/web <query>` or auto-search mode)
  - Web lookups now include short excerpts pulled from top result pages for more grounded answers.
  - Search backend is switchable between `searxng` and `duckduckgo`.
- Microphone input with `SpeechRecognition` and local `faster-whisper`
- XTTS-v2 voice output with streamed playback
- Selectable TTS backend: `xtts` (default) or `gtts`
- Desktop GUI with left-side tabs (`Main`, `Chat`, `Profiles`, `Settings`)
- Profile manager with create, clone, delete, activate, and advanced JSON editing
- Startup auto-tuning based on CPU, RAM, and CUDA GPU capability
- GitHub-backed version file plus optional startup auto-update
- Configurable companion profiles with rich metadata, behavior rules, and memory sections
- Windows-friendly setup with `setup.bat` that can install Python 3.11, Ollama, and the default Ollama model for you
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

If Python 3.11 or Ollama are missing, `setup.bat` uses `winget` to install them first and accepts the required `winget` source/package agreements automatically. It also creates `.env`, seeds `data/profile.json`, starts Ollama, pulls the default Ollama model, and preloads the faster-whisper and XTTS model files so the first app launch is less annoying. On first app launch, NovaAI migrates to a multi-profile store at `data/profiles.json`.

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
|   |-- profiles.example.json
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
- `novaai/storage.py`: multi-profile store, active profile switching, and history loading/saving
- `novaai/chat.py`: system prompt construction and provider-specific chat requests
- `novaai/audio_input.py`: microphone capture, STT, and mic calibration
- `novaai/tts.py`: XTTS/gTTS generation and playback handling
- `novaai/gui.py`: desktop chat window, hands-free controls, and mic mute
- `novaai/launcher.py`: entrypoint that chooses CLI or GUI mode
- `novaai/performance.py`: hardware detection and startup auto-tuning
- `novaai/updater.py`: GitHub version checks and optional self-update flow
- `novaai/cli.py`: command handling and the main terminal loop

## GUI Controls

- Left tabs:
- `Main`: session pulse + quick voice/chat actions
- `Chat`: transcript and message composer
- `Profiles`: create, clone, delete, activate, and edit profiles
- `Settings`: microphone/speaker selection and refresh
- Profile editor:
- Basic fields: profile name, description, companion/user names, tags, style, goals, memory notes
- Advanced mode: full profile JSON editor for deep customization

## Profile JSON Shape

Each profile now supports deep customization sections, including:

- top-level identity and style keys (`profile_name`, `companion_name`, `companion_style`, `shared_goals`, `memory_notes`)
- `profile_details.identity` for relationship and locale hints
- `profile_details.conversation` for formatting, pacing, and reply-length behavior
- `profile_details.personality_sliders` for tone calibration (warmth, sass, directness, etc.)
- `profile_details.boundaries` for roast/safety limits
- `profile_details.capabilities` for explicit “can do / cannot claim” contracts
- `profile_details.memory` for structured user facts/preferences
- `profile_details.voice` for speech delivery notes
- `profile_details.custom_rules` for strict must-follow rules and extra notes

## Commands

- `/help` shows commands
- `/mode voice` turns on hands-free microphone input
- `/mode text` switches back to typing
- `/listen` captures one spoken turn immediately
- `/ask` alias for `/listen`
- `/recalibrate` relearns room noise before listening
- `/mics` lists available microphone devices
- `/mic <index>` chooses a microphone
- `/mic default` switches back to the system default microphone
- `/tts` shows the current TTS provider
- `/tts xtts` switches to XTTS-v2 (default)
- `/tts gtts` switches to Google gTTS
- `/speakers` lists built-in XTTS voices (XTTS mode only)
- `/speaker <name>` switches XTTS voice (XTTS mode only)
- `/voice` toggles spoken replies on and off
- `/web` shows web browsing status
- `/web on` enables web browsing
- `/web off` disables web browsing
- `/web auto on` enables automatic web lookups for likely current-event prompts
- `/web auto off` disables automatic web lookups
- `/web clear` clears any queued web context
- `/web <query>` searches the web and applies the results to the next reply
- `/performance` shows the detected hardware and active performance profile
- `/profile` shows the saved companion profile
- `/profiles` lists available saved profiles
- `/profile use <profile_id>` switches the active profile
- `/name <new name>` renames the companion
- `/me <your name>` saves your name
- `/remember <fact>` stores a memory note
- `/reset` clears conversation history
- `/exit` quits the app

In the GUI `Chat` tab, you can also click `Voice Ask` (or press `F8`) to capture a spoken prompt.
With web browsing enabled, natural requests like "Hey, can you check the weather for me?" will auto-trigger a web lookup even if `/web auto` is off.
Natural lookup also works for general topics like "can you search RTX 5090 price?" or "look up the latest Unreal Engine news."

## Configuration Highlights

- `AUTO_TUNE_PERFORMANCE`: enable or disable startup auto-tuning
- `AUTO_TUNE_GOAL`: choose `speed`, `balanced`, or `quality`
- `AUTO_UPDATE_CHECK`: check the GitHub `VERSION` file on startup
- `AUTO_UPDATE_INSTALL`: auto-install GitHub updates when the local copy is behind
- `AUTO_UPDATE_CACHE_SECONDS`: reuse the last update check result for this many seconds
- `HF_HUB_DISABLE_SYMLINKS_WARNING`: suppress the Windows symlink cache warning from Hugging Face
- `NOVA_GITHUB_REPO`: override the GitHub repo slug used for update checks
- `NOVA_GITHUB_BRANCH`: override the GitHub branch used for update checks
- `LLM_PROVIDER`: `ollama` or `openai` (`openai` also covers OpenAI-compatible servers like LM Studio and LiteLLM)
- `LLM_MODEL`: chat model name
- `LLM_API_URL`: custom chat endpoint URL; leave blank to use the provider default
- `LLM_API_KEY`: API key for OpenAI or compatible hosted endpoints
- `LLM_NUM_PREDICT`: reply token budget
- `TTS_PROVIDER`: `xtts` (default) or `gtts`
- `WEB_BROWSING_ENABLED`: enable web search features
- `WEB_AUTO_SEARCH`: automatically search for likely web/current-event prompts
- `WEB_SEARCH_PROVIDER`: search backend, currently `searxng` or `duckduckgo`
- `WEB_SEARCH_URL`: optional SearXNG `/search` endpoint, defaulting to `https://searxng.nekosunevr.co.uk/`
- `WEB_MAX_RESULTS`: number of search results to attach per lookup
- `WEB_TIMEOUT_SECONDS`: timeout for web search requests
- `WEB_REGION`: region code for web results (for example, `us-en`)
- `WEB_SAFESEARCH`: web safe-search mode (`off`, `moderate`, or `strict`)
- `VOICE_ENABLED`: whether spoken replies start enabled (default is `false`)
- `XTTS_SPEED`: speaking pace multiplier (`1.00` is natural speed)
- `XTTS_STREAM_OUTPUT`: stream speech while audio is generating
- `XTTS_CHUNK_MAX_CHARS`: safe per-chunk XTTS text limit
- `XTTS_MAX_TEXT_CHARS`: maximum total spoken text for one reply
- `STT_USE_GPU`: manual fallback if auto-tune is disabled
- `STT_MODEL`: faster-whisper model size, such as `small.en` or `medium.en`
- `MIC_DEVICE_INDEX`: manually pin a microphone from `/mics`
- `SPEAKER_DEVICE_INDEX`: pin a specific speaker/output device for playback

## Notes

- XTTS-v2 downloads large model files the first time it is used.
- gTTS does not require local model downloads, but it needs internet access.
- `faster-whisper` downloads its speech model the first time it is used.
- `setup.bat` now preloads those model files during setup so most users should not see those downloads on first launch anymore.
- Auto-update is conservative on purpose. If NovaAI sees a git checkout with local edits, it skips self-updating instead of risking your work.
- The GUI mic mute is app-level, which means it stops NovaAI from starting new listens. It does not change the Windows system microphone mute state.
- With auto-tune on, NovaAI overrides a few performance-sensitive values at startup so the app matches the current machine better.
- Auto-tune does not change `XTTS_SPEED`, so voice pace stays consistent across different machines.
- If you want to lock in your own values, set `AUTO_TUNE_PERFORMANCE=false` in `.env`.
- Voice output is saved to `audio/latest_reply.wav` (XTTS) or `audio/latest_reply.mp3` (gTTS) even when playback fails.
- Runtime data like `.env`, `data/profile.json`, `data/profiles.json`, `data/history.jsonl`, and generated audio are ignored by git.

## Contributing

The project is intentionally split into modules so different contributors can work in parallel without constantly editing one giant file. A good starting point is:

- voice or mic issues: `novaai/audio_input.py`
- personality or response logic: `novaai/chat.py`
- XTTS or playback issues: `novaai/tts.py`
- command flow or app behavior: `novaai/cli.py`

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
