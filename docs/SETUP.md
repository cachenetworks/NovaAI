# 🔧 Setup Guide

Everything you need to get NovaAI running on Windows or Linux.

---

## ⚡ One-Line Install (fresh machine)

**Windows** — open PowerShell and paste:

```powershell
powershell -c "irm https://raw.githubusercontent.com/cachenetworks/NovaAI/main/install.ps1 | iex"
```

**Linux** — open a terminal and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/cachenetworks/NovaAI/main/install.sh | bash
```

Both installers handle everything — Python, LLM provider, Ollama, NVIDIA GPU, desktop shortcut/launcher. Just answer a few questions.

### Prerequisites (handled automatically by the installer)

- **Windows 10/11** (64-bit) or **Linux** (Ubuntu, Debian, Fedora, Arch, etc.)
- **Python 3.11+** — installed via winget (Windows) or your package manager (Linux)
- **Internet connection** for initial setup
- **~4 GB disk space** for models and dependencies
- **(Optional)** NVIDIA GPU with CUDA for faster voice
- **(Linux)** `ffmpeg` for audio playback: `sudo apt install ffmpeg`

---

## 🚀 Already have the repo? Setup + Launch

```powershell
python setup.py
```

First run does the full setup, then launches the GUI. Subsequent runs skip straight to launch.

### What setup does

| Step | What It Does |
|------|-------------|
| 1️⃣ | Creates a `.venv` virtual environment |
| 2️⃣ | Installs all Python packages from `requirements.txt` |
| 3️⃣ | Creates `data/` and `audio/` directories, seeds `.env` and `data/profile.json` |
| 4️⃣ | Checks for Ollama — installs via `winget` if missing |
| 5️⃣ | Starts the Ollama server |
| 6️⃣ | Pulls the default chat model (`dolphin3`) |
| 7️⃣ | Preloads faster-whisper and XTTS-v2 model files |
| 8️⃣ | Writes the setup marker so it won't run again |

---

## 🖥️ Launch Options

```powershell
# Default — setup if needed, then launch GUI
python setup.py

# Launch GUI (skip setup if already done)
python setup.py --launch

# Terminal chat mode
python setup.py --terminal

# Re-run setup only (no launch)
python setup.py --setup

# Check for updates and apply
python setup.py --update
```

### First launch

On the very first app launch:
- Any legacy JSON data files are automatically migrated to SQLite
- The default companion profile is created if none exists
- Voice replies start **OFF** by default (toggle from Dashboard or Settings)

---

## ⚡ GPU Acceleration (Optional)

If you have an NVIDIA GPU and want significantly faster voice synthesis:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 torch torchaudio torchcodec
```

This replaces the CPU-only PyTorch with CUDA-enabled builds. Voice generation can go from 10+ seconds to under 2 seconds.

> ⚠️ Make sure your NVIDIA drivers are up to date. NovaAI auto-detects CUDA availability at startup.

---

## 🔄 Updating

### Automatic updates

With `AUTO_UPDATE_CHECK=true` and `AUTO_UPDATE_INSTALL=true` in `.env`, NovaAI checks GitHub on startup and self-updates if a new version is available.

### Manual update

```powershell
python setup.py --update
```

### Safety

- Git checkouts with local edits are **never** auto-updated
- Update checks are cached for 6 hours to avoid rate limits
- Failed updates are skipped gracefully — your current version keeps running

---

## 🔧 Troubleshooting

### Ollama won't start

- Check if Ollama is already running: visit `http://127.0.0.1:11434/api/tags` in a browser
- Try starting it manually: `ollama serve`
- Check if another process is using port 11434

### `ModuleNotFoundError`

Run setup again to ensure all dependencies are installed:

```powershell
python setup.py --setup
```

### Models downloading slowly

XTTS-v2 and faster-whisper models are several GB. The first download takes time depending on your connection. Setup preloads them so the app launch is faster.

### No sound output

- Check Settings > Audio Devices and make sure the right speaker is selected
- Try `/speakers` in terminal mode to list available output devices
- Make sure your system volume isn't muted
