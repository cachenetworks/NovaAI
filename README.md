# 🤖 NovaAI

### *Your brutally honest AI companion that actually talks back.*

[![Python 3.11](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.0-violet)](VERSION)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows)](https://microsoft.com)

NovaAI is a voice-powered desktop companion built with Python. It listens through your mic, thinks with local or cloud LLMs, and speaks back with a cloned voice — all wrapped in a slick dark-themed UI.

Think Alexa, but with *attitude* and zero cloud lock-in. 🔥

---

## ✨ Features at a Glance

| | Feature | Details |
|---|---------|---------|
| 🧠 | **LLM Chat** | Ollama, OpenAI, LM Studio, LiteLLM — your pick |
| 🎙️ | **Voice Input** | Local `faster-whisper` STT — no audio leaves your machine |
| 🔊 | **Voice Output** | XTTS-v2 streamed synthesis with cloned voices (or Google TTS lite) |
| 🌐 | **Web Search** | Manual or auto-triggered lookups via SearXNG / DuckDuckGo |
| 🎵 | **Music & Radio** | SoundCloud search, internet radio, in-app playback |
| ⏰ | **Reminders & Alarms** | Natural language: *"remind me to call mum at 3pm"* |
| 📋 | **To-Do & Shopping** | Checkbox lists that sync across voice and GUI |
| 📅 | **Calendar** | Track events with dates and times |
| 👤 | **Profiles** | Multiple companion personalities — create, clone, switch |
| ⚡ | **Auto-Tune** | Detects your hardware, adjusts models and GPU usage |
| 🔄 | **Self-Update** | Checks GitHub for new versions on startup |
| 🗄️ | **SQLite Storage** | Everything in one clean database — no scattered JSON |

---

## 🚀 Quick Start

### ⚡ One-Line Install (fresh machine)

Open PowerShell and paste:

```powershell
powershell -c "irm https://raw.githubusercontent.com/cachenetworks/NovaAI/main/install.ps1 | iex"
```

> This interactive installer handles **everything** — Python, Ollama, model downloads, NVIDIA GPU setup, desktop shortcut — the works. Just answer a few questions and sit back.

### 🔧 Already have the repo?

```powershell
python setup.py
```

First run does the full setup, then launches the GUI. Subsequent runs skip straight to launch.

### 📋 All commands

```powershell
python setup.py              # Setup (if needed) + launch GUI
python setup.py --launch     # 🖥️ Launch GUI
python setup.py --terminal   # ⌨️ Terminal mode
python setup.py --setup      # 🔧 Re-run setup only
python setup.py --update     # 🔄 Check for updates
```

---

## 🖥️ The Desktop GUI

NovaAI runs as a native desktop window powered by **pywebview + Tailwind CSS** — a proper web-rendered UI that looks and feels modern, not some grey widget nightmare.

| Page | What It Does |
|------|-------------|
| 📊 **Dashboard** | Session controls, toggle voice/mic/hands-free, live status |
| 💬 **Chat** | Full conversation view with text + voice input |
| 🔔 **Reminders** | Time-based reminders and recurring alarms |
| 📅 **Calendar** | Events with date/time tracking |
| 🛒 **Shopping** | Checkbox shopping list |
| ✅ **To-Do** | Task list with done/delete |
| 👤 **Profiles** | Create, clone, switch, or delete personalities |
| ⚙️ **Settings** | Audio devices, web search, LLM/TTS/STT config |

> 💡 **Pro tip:** Voice replies, hands-free mode, and mic mute can all be toggled *before* starting a session. Configure everything first, then hit Start.

---

## ⌨️ Terminal Commands

For the keyboard warriors out there:

<details>
<summary>📖 Click to expand full command list</summary>

### 🗣️ Voice & Input

| Command | What It Does |
|---------|-------------|
| `/mode voice` | Hands-free mic input |
| `/mode text` | Switch back to typing |
| `/listen` or `/ask` | Capture one spoken turn |
| `/voice` | Toggle spoken replies on/off |
| `/recalibrate` | Re-tune mic noise gate |
| `/mics` | List available microphones |
| `/mic <index>` | Choose a specific mic |
| `/mic default` | Reset to system default |
| `/speakers` | List XTTS voices |
| `/speaker <name>` | Switch XTTS voice |
| `/tts` | Show current TTS provider |
| `/tts xtts` / `/tts gtts` | Switch TTS engine |

### 🌐 Web Search

| Command | What It Does |
|---------|-------------|
| `/web` | Show web search status |
| `/web on` / `/web off` | Enable/disable web search |
| `/web auto on` / `/web auto off` | Toggle auto-search for current events |
| `/web clear` | Clear queued web context |
| `/web <query>` | Search and feed results to next reply |

### 🎵 Media

| Command | What It Does |
|---------|-------------|
| `/play <query>` | Play a radio station or search music |
| `/radio <station>` | Tune into a known station |
| `/music <query>` | Search your default music platform |
| `/pause` / `/resume` / `/stop` | Playback controls |

### 👤 Profiles & History

| Command | What It Does |
|---------|-------------|
| `/profile` | Show current profile |
| `/profiles` | List all profiles |
| `/profile use <id>` | Switch profiles |
| `/name <new name>` | Rename the companion |
| `/me <name>` | Set your name |
| `/remember <fact>` | Store a memory note |
| `/reset` | Clear conversation history |
| `/performance` | Show hardware and tuning info |
| `/exit` | Quit |

</details>

> 🗣️ **Natural language works too!** Say *"remind me to call the dentist at 3pm"*, *"play Capital FM"*, or *"add milk to my shopping list"* — NovaAI handles it.

---

## 🎭 Profiles — Make It Yours

Each companion profile is deeply customisable. Go wild:

| Section | What You Can Tweak |
|---------|-------------------|
| 🏷️ **Identity** | Name, pronouns, role, relationship style |
| 💬 **Conversation** | Reply length, pacing, verbosity, formatting |
| 🎚️ **Personality Sliders** | Warmth, sass, directness, patience, playfulness, formality |
| 🚧 **Boundaries** | Roast intensity, avoided topics, safety overrides |
| 🧠 **Memory** | Likes, dislikes, personal facts, inside jokes, projects |
| 🔊 **Voice** | Speech style, delivery notes, persona keywords |
| 📜 **Custom Rules** | Hard must-follow rules and soft preferences |

Want a sarcastic best friend? A patient tutor? A no-nonsense project manager? Just create a new profile and dial the sliders. 🎛️

---

## 🗄️ Data Storage

All runtime data lives in a single **SQLite database** at `data/novaai.db`:

- 💬 Chat history
- 👤 Profiles and all their feature data (reminders, todos, shopping, calendar, alarms)
- ⚙️ App state (active profile, settings)

> 📦 On first run, existing JSON files (`profiles.json`, `history.jsonl`) are **automatically migrated** into the database. No manual steps needed.

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and tweak what you need:

<details>
<summary>📖 Click to expand full configuration reference</summary>

### 🧠 Core

| Setting | Default | Description |
|---------|---------|-------------|
| `AUTO_TUNE_PERFORMANCE` | `true` | Auto-detect hardware and tune settings |
| `AUTO_TUNE_GOAL` | `balanced` | Tuning goal: `speed`, `balanced`, or `quality` |
| `AUTO_UPDATE_CHECK` | `true` | Check GitHub for updates on startup |
| `AUTO_UPDATE_INSTALL` | `true` | Auto-install updates for non-git installs |

### 🤖 LLM

| Setting | Default | Description |
|---------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | Chat backend: `ollama` or `openai` |
| `LLM_MODEL` / `OLLAMA_MODEL` | `dolphin3` | Which model to use |
| `LLM_API_URL` | *(auto)* | Custom chat endpoint URL |
| `LLM_API_KEY` | *(none)* | API key for OpenAI-compatible endpoints |
| `LLM_NUM_PREDICT` | `1200` | Reply token budget |
| `LLM_TEMPERATURE` | `0.95` | Response creativity |

### 🌐 Web Search

| Setting | Default | Description |
|---------|---------|-------------|
| `WEB_BROWSING_ENABLED` | `true` | Enable web search features |
| `WEB_AUTO_SEARCH` | `false` | Auto-search for current-event questions |
| `WEB_SEARCH_PROVIDER` | `searxng` | Backend: `searxng` or `duckduckgo` |
| `WEB_SEARCH_URL` | *(built-in)* | SearXNG endpoint URL |
| `WEB_MAX_RESULTS` | `5` | Results per lookup |
| `WEB_SAFESEARCH` | `moderate` | Safe search: `off`, `moderate`, `strict` |

### 🎵 Media

| Setting | Default | Description |
|---------|---------|-------------|
| `MEDIA_REGION` | `GB` | Radio region (`GB`, `US`, `AU`, `CA`, etc.) |
| `MUSIC_PROVIDER_DEFAULT` | `soundcloud` | Default music platform |

### 🔊 Voice & TTS

| Setting | Default | Description |
|---------|---------|-------------|
| `VOICE_ENABLED` | `false` | Start with voice replies on |
| `TTS_PROVIDER` | `xtts` | Voice engine: `xtts` or `gtts` |
| `XTTS_SPEED` | `1.0` | Speaking pace multiplier |
| `XTTS_USE_GPU` | `true` | Use GPU for voice synthesis |
| `XTTS_STREAM_OUTPUT` | `true` | Stream audio while generating |
| `XTTS_SPEAKER` | `Ana Florence` | XTTS voice name |

### 🎙️ Speech-to-Text

| Setting | Default | Description |
|---------|---------|-------------|
| `STT_PROVIDER` | `faster-whisper` | STT engine |
| `STT_MODEL` | `small.en` | Whisper model size |
| `STT_USE_GPU` | `true` | Use GPU for transcription |
| `INPUT_MODE` | `voice` | Default input: `voice` or `text` |

### 🔈 Audio Devices

| Setting | Default | Description |
|---------|---------|-------------|
| `MIC_DEVICE_INDEX` | *(auto)* | Pin a specific microphone |
| `SPEAKER_DEVICE_INDEX` | *(auto)* | Pin a specific speaker |

</details>

---

## 📁 Project Layout

```
NovaAI/
├── app.py                    # 🚪 Entry point
├── setup.py                  # 🔧 Setup, launch, and update — all in one
├── install.ps1               # ⚡ One-line PowerShell installer
├── requirements.txt          # 📦 Python dependencies
├── VERSION                   # 🏷️ Current version
├── .env.example              # ⚙️ Configuration template
│
├── data/
│   ├── novaai.db             # 🗄️ SQLite database (runtime)
│   └── profile.example.json  # 📝 Example profile
│
└── novaai/
    ├── launcher.py           # 🚪 CLI vs GUI routing + auto-update
    ├── webgui.py             # 🖥️ pywebview desktop GUI backend
    ├── cli.py                # ⌨️ Terminal chat loop + commands
    ├── chat.py               # 🧠 System prompt + LLM requests
    ├── config.py             # ⚙️ Environment parsing + runtime config
    ├── database.py           # 🗄️ SQLite schema + CRUD operations
    ├── storage.py            # 💾 Profile/history API (SQLite-backed)
    ├── features.py           # ⏰ Reminders, alarms, todos, shopping, calendar
    ├── audio_input.py        # 🎙️ Mic capture + faster-whisper STT
    ├── tts.py                # 🔊 XTTS-v2 / gTTS synthesis + playback
    ├── media.py              # 🎵 Radio + music platform integration
    ├── media_player.py       # ▶️ In-app audio playback (ffplay)
    ├── performance.py        # ⚡ Hardware detection + auto-tuning
    ├── updater.py            # 🔄 GitHub version check + self-update
    ├── web_search.py         # 🌐 SearXNG / DuckDuckGo search
    ├── defaults.py           # 📋 Default profile template
    ├── models.py             # 📦 Shared dataclasses
    ├── paths.py              # 📍 Path constants
    └── static/
        └── index.html        # 🎨 Tailwind CSS frontend
```

---

## 📚 Documentation

<details>
<summary>🧠 How the Chat Pipeline Works</summary>

When you send a message (text or voice), NovaAI runs through this pipeline:

1. **Media check** — is it a play/radio/music request? Handle it directly.
2. **Feature check** — is it a reminder, alarm, todo, shopping, or calendar request? Parse and handle.
3. **Web search** — if enabled, check for explicit `/web` queries, inferred lookups (*"what's the weather?"*), or auto-search triggers.
4. **LLM request** — build a system prompt from the active profile, attach conversation history and any web context, send to the LLM.
5. **Voice output** — if voice is enabled, synthesise the reply with XTTS-v2 or gTTS and play it back.
6. **Hands-free loop** — if hands-free mode is on, immediately start listening for the next turn.

The entire pipeline runs in a background thread so the UI stays responsive.

</details>

<details>
<summary>🎙️ Voice & Audio Architecture</summary>

### Speech-to-Text (STT)
- Engine: `faster-whisper` (local) or Google Web Speech API
- Mic capture via `SpeechRecognition` library
- Automatic noise calibration on first listen
- Configurable silence detection, energy threshold, and VAD

### Text-to-Speech (TTS)
- **XTTS-v2** (default): local neural TTS with voice cloning, GPU-accelerated, streamed output
- **gTTS** (fallback): Google's cloud TTS — lightweight but needs internet
- Audio saved to `audio/latest_reply.wav` (XTTS) or `.mp3` (gTTS)
- Playback via `sounddevice` with configurable output device

### Audio Devices
- Mic and speaker can be pinned via `.env` or the Settings page
- `/mics` and `/speakers` commands list available devices with indices
- Recalibration re-tunes the noise gate without restarting

</details>

<details>
<summary>🗄️ Database Schema</summary>

NovaAI uses SQLite (`data/novaai.db`) with three tables:

**`profiles`** — one row per companion profile
```sql
profile_id   TEXT PRIMARY KEY   -- e.g. "default", "snarky-bot"
profile_name TEXT               -- display name
data         TEXT               -- full profile JSON blob
created_at   TEXT               -- ISO timestamp
updated_at   TEXT               -- ISO timestamp
```

**`history`** — one row per chat message
```sql
id        INTEGER PRIMARY KEY AUTOINCREMENT
timestamp TEXT                -- ISO timestamp
role      TEXT                -- "user", "assistant", or "system"
content   TEXT                -- message text
```

**`app_state`** — key/value settings store
```sql
key   TEXT PRIMARY KEY        -- e.g. "active_profile_id"
value TEXT                    -- the value
```

Feature data (reminders, alarms, todos, shopping, calendar) lives inside the profile JSON blob under `profile_details`, so it's saved/loaded with the profile automatically.

</details>

<details>
<summary>⚡ Performance Auto-Tuning</summary>

When `AUTO_TUNE_PERFORMANCE=true`, NovaAI detects your hardware at startup and picks a performance profile:

| What It Checks | What It Adjusts |
|----------------|----------------|
| CPU core count | Request timeouts |
| Available RAM | Token budget |
| CUDA GPU presence | TTS/STT GPU acceleration |
| VRAM amount | Whisper model size, XTTS streaming settings |

**Tuning goals:**
- `speed` — smaller models, aggressive timeouts, prioritise response time
- `balanced` — sensible defaults for most hardware
- `quality` — larger models, longer timeouts, prioritise output quality

> ⚠️ Auto-tune **never** changes `XTTS_SPEED`, so your companion's voice pace stays consistent across machines.

</details>

<details>
<summary>🔄 Auto-Update System</summary>

NovaAI can check for and install updates from GitHub:

1. On startup, compares local `VERSION` to the remote `VERSION` on your configured branch
2. If a newer version exists and `AUTO_UPDATE_INSTALL=true`, downloads and applies the update
3. Restarts itself with the new code

**Safety guards:**
- Git checkouts with local edits are **never** auto-updated
- Update results are cached for `AUTO_UPDATE_CACHE_SECONDS` (default: 6 hours) to avoid hammering GitHub
- Manual updates always available via `python setup.py --update`

</details>

<details>
<summary>🎵 Media & Radio</summary>

NovaAI intercepts natural media requests:

- *"play Capital FM"* → finds and streams the radio station
- *"play synthwave on SoundCloud"* → searches and plays a track
- *"pause"* / *"resume"* / *"stop"* → controls the current stream

**Supported radio regions:** UK, US, Australia, Canada, Germany, Japan (with fallback to internet-radio.com search)

**Music platforms:** SoundCloud (default), with Spotify and Deezer as search options

In-app playback uses `ffplay` for radio streams and resolved audio URLs.

</details>

---

## 💡 Good to Know

- 📥 **First run downloads models** — XTTS-v2 and faster-whisper grab model files on first use. `python setup.py` preloads them so you're not waiting forever.
- 🔇 **Mic mute is app-level** — it stops NovaAI from listening. It doesn't touch your Windows system mic.
- 🔒 **Git-safe updates** — if NovaAI detects a git checkout with local edits, self-update is skipped to protect your work.
- 💾 **Audio is always saved** — voice replies land in `audio/latest_reply.wav` even if playback fails. Useful for debugging.
- 🌍 **Works offline** — with Ollama and XTTS, the entire pipeline runs locally. Web search is optional.

---

## 🤝 Contributing

The codebase is modular by design — pick an area and dive in:

| Area | File(s) | Difficulty |
|------|---------|-----------|
| 🎙️ Voice / mic issues | `novaai/audio_input.py` | Medium |
| 🧠 Personality / responses | `novaai/chat.py` | Easy |
| 🔊 TTS / playback | `novaai/tts.py` | Medium |
| ⌨️ Commands / app flow | `novaai/cli.py` | Easy |
| 🎨 GUI frontend | `novaai/static/index.html` | Easy |
| 🖥️ GUI backend | `novaai/webgui.py` | Medium |
| ⏰ Features (reminders etc.) | `novaai/features.py` | Easy |
| 🗄️ Data / profiles | `novaai/storage.py` + `novaai/database.py` | Medium |
| 🌐 Web search | `novaai/web_search.py` | Medium |
| 🎵 Media / radio | `novaai/media.py` | Medium |

PRs welcome! If you're not sure where to start, open an issue and we'll point you in the right direction. 🫡

---

## 📄 License

MIT License — see [LICENSE](LICENSE).

---

<div align="center">

Built with spite, sarcasm, and way too much caffeine ☕ by [CacheNetworks](https://github.com/cachenetworks)

**If NovaAI roasts you, that's a feature, not a bug.** 😏

</div>
