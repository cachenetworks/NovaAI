# NovaAI

NovaAI is a local voice companion built on Ollama, faster-whisper, and XTTS-v2.
It can listen through your microphone, reply in text, and speak back with streamed audio.

## Features

- Local Ollama chat with persistent recent history
- Microphone input with `SpeechRecognition` and local `faster-whisper`
- XTTS-v2 voice output with streamed playback
- Configurable companion profile and memory notes
- Windows-friendly setup with `setup.bat`
- Modular Python package layout so contributors can work on one area at a time

## Quick Start

1. Install Ollama for Windows.
2. Pull a chat model, for example:

```powershell
ollama pull dolphin3
```

3. Run the project setup:

```powershell
.\setup.bat
```

4. Start NovaAI:

```powershell
.\.venv\Scripts\python.exe app.py
```

If `.env` or `data/profile.json` do not exist yet, `setup.bat` will create them from the example files.

## Optional GPU Upgrade

If you have an NVIDIA GPU and want faster XTTS replies, upgrade PyTorch after setup:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 torch torchaudio torchcodec
```

## Project Layout

```text
NovaAI/
|-- app.py
|-- setup.bat
|-- requirements.txt
|-- LICENSE
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
|   |-- models.py
|   |-- paths.py
|   |-- storage.py
|   |-- tts.py
|   |-- utils.py
```

## Module Guide

- `novaai/config.py`: environment parsing and runtime configuration
- `novaai/storage.py`: profile and chat history loading/saving
- `novaai/chat.py`: system prompt construction and Ollama requests
- `novaai/audio_input.py`: microphone capture, STT, and mic calibration
- `novaai/tts.py`: XTTS generation, streamed playback, and WAV output
- `novaai/cli.py`: command handling and the main terminal loop

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
- `/profile` shows the saved companion profile
- `/name <new name>` renames the companion
- `/me <your name>` saves your name
- `/remember <fact>` stores a memory note
- `/reset` clears conversation history
- `/exit` quits the app

## Configuration Highlights

- `OLLAMA_MODEL`: the Ollama chat model name
- `OLLAMA_NUM_PREDICT`: reply token budget
- `XTTS_STREAM_OUTPUT`: stream speech while audio is generating
- `XTTS_CHUNK_MAX_CHARS`: safe per-chunk XTTS text limit
- `XTTS_MAX_TEXT_CHARS`: maximum total spoken text for one reply
- `STT_MODEL`: faster-whisper model size, such as `small.en` or `medium.en`
- `MIC_DEVICE_INDEX`: manually pin a microphone from `/mics`

## Notes

- XTTS-v2 downloads large model files the first time it is used.
- `faster-whisper` downloads its speech model the first time it is used.
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
