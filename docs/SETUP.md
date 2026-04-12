# 🔧 Setup Guide

Everything you need to get NovaAI running on Windows.

---

## 📋 Prerequisites

- **Windows 10 or 11** (64-bit)
- **Internet connection** for initial setup
- **~4 GB disk space** for models and dependencies
- **(Optional)** NVIDIA GPU with CUDA for faster voice

> 💡 Don't have Python or Ollama installed? No worries — `setup.bat` handles both.

---

## 🚀 Automatic Setup

```powershell
.\setup.bat
```

This single script does **everything**:

| Step | What It Does |
|------|-------------|
| 1️⃣ | Checks for Python 3.11 — installs via `winget` if missing |
| 2️⃣ | Creates a `.venv` virtual environment |
| 3️⃣ | Installs all Python packages from `requirements.txt` |
| 4️⃣ | Creates `data/` and `audio/` directories, seeds `.env` and `data/profile.json` |
| 5️⃣ | Checks for Ollama — installs via `winget` if missing |
| 6️⃣ | Starts the Ollama server |
| 7️⃣ | Pulls the default chat model (`dolphin3`) |
| 8️⃣ | Preloads faster-whisper and XTTS-v2 model files |

After setup completes, you'll see instructions for launching.

---

## 🖥️ Launching

### Desktop GUI (recommended)

```powershell
.\launch_gui.bat
```

### Terminal mode

```powershell
.\.venv\Scripts\python.exe app.py
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
.\update.bat
```

### Safety

- Git checkouts with local edits are **never** auto-updated
- Update checks are cached for 6 hours to avoid rate limits
- Failed updates are skipped gracefully — your current version keeps running

---

## 🔧 Troubleshooting

### `'powershell' is not recognized`

The setup script uses full paths for PowerShell. If you still see this, make sure `%SystemRoot%\System32\WindowsPowerShell\v1.0\` exists.

### Ollama won't start

- Check if Ollama is already running: visit `http://127.0.0.1:11434/api/tags` in a browser
- Try starting it manually: `ollama serve`
- Check if another process is using port 11434

### `ModuleNotFoundError`

Run setup again to ensure all dependencies are installed:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Models downloading slowly

XTTS-v2 and faster-whisper models are several GB. The first download takes time depending on your connection. `setup.bat` preloads them so the app launch is faster.

### No sound output

- Check Settings > Audio Devices and make sure the right speaker is selected
- Try `/speakers` in terminal mode to list available output devices
- Make sure your system volume isn't muted
