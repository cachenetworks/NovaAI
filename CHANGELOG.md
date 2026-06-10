# Changelog

All notable changes to **NovaAI** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project aims to follow [Semantic Versioning](https://semver.org/).

## [1.1.1] - Unreleased

The "Neuro-sama" line: NovaAI grows from a desktop companion into a
streamer-style AI VTuber — live Twitch chat, a VRM/MMD avatar, autonomous
game-playing (Minecraft and beyond), local singing, RAG learning, and a
single-port web dashboard. Runs on Windows, Linux (amd64 + Raspberry Pi 5),
and headless servers.

### Added

**AI companion & personality**
- Neuro-sama feature set: Twitch chat integration, RAG-based learning, and avatar lip-sync.
- RAG/learning supports local Ollama embeddings and local vision models (embeddinggemma, moondream).
- Claude Code & Codex CLI added as LLM providers (reuse your existing CLI login).

**Avatar (VRM / MMD)**
- VRM avatar with relaxed rest pose, emotion-driven body language, and human-like idle/dance motion (no more T-pose).
- Richer expressions: blush, shy, love, wink, flirty, sleeping/lay-down, and more.
- MMD dance mode: play `.vmd` motion + audio + camera on the VRM avatar, with full body retarget (torso, arms, legs), selectable axis conversion, and a live body-tuning panel.
- Dedicated MMD sidebar page (upload, list, play, delete); dances bundle motion + song + camera per set.
- Mouse camera on the web avatar view (orbit / zoom / pan); auto-framing of the VRM.
- Transparent avatar overlay for OBS (shows only the avatar), proxied through the single web port; overlay camera enabled in transparent mode.
- VRM upload moved to the dashboard.

**Streaming**
- Stream alerts, reactions, and tips ("stockings") overlay.
- Streamlabs / StreamElements token configuration in Settings.
- Twitch role-gated chat and reliable Twitch connect (anon + OAuth) with clear status and auth fallback.

**Minecraft & game-playing**
- Autonomous Minecraft bot: gather/craft own tools, farming (till/plant/harvest/bonemeal/trees), irrigation & infinite water source, smelting, mining with tool selection, fishing, animal breeding, exploration, villages & villager trading, building a house, hunting/cooking food, auto-eat to heal, sleep, and combat.
- Owner commands, hostile defense, and Microsoft-account auth; bot plays on its own when the owner is offline.
- Live browser view of the bot (prismarine-viewer) plus a combined Live View dashboard (3D world + inventory/crafting/furnace + thoughts + server chat), all served on one port.
- Chat/voice can drive the in-game bot; Mindcraft command translation.
- Phase 5 universal game drivers: vision + input, VRChat OSC, Factorio RCON, and osu!.
- Per-game settings panel (no more editing `.env` to switch servers).

**Singing**
- Fully-local singing using LRCLIB timed lyrics + XTTS, with optional backing mix.
- Bring your own backing via file or YouTube URL; auto-find YouTube instrumental; save & replay songs; gTTS support; vocals + backing merged into one file.

**Web / platform / settings**
- Settings panel with editable config sections, model dropdowns, and backend model auto-detect.
- Profile import/export; LAN / Tailscale access for web mode.
- Runs on Raspberry Pi 5 (aarch64) and amd64 Linux, including headless.
- TTS output to the browser (avatar) with speaker / browser / both toggle.
- Voice & Input toggles and a Media on/off toggle persist across restarts.
- GUI / Web installer modes; upload cap raised to 2 GB (configurable via `NOVA_MAX_UPLOAD_MB`).
- Cap Ollama context window via `OLLAMA_NUM_CTX` for small GPUs.
- `torchcodec` added to the CUDA PyTorch install for newer torchaudio.

### Fixed
- Lip-sync now moves the mouth for TTS on all playback paths.
- Reliable browser audio for voice and singing.
- Avatar WebSocket bridge works on `websockets >= 14`; VRM loaded from the running install (not a baked-in path).
- Handle broken XTTS / torchaudio native imports gracefully with a clear error.
- Minecraft bridge survives stray errors; auto-reconnect on disconnect/kick; live view renders even when the server MC is too new; bot no longer freezes on bad action parsing.
- Auto-recover from a corrupt SQLite DB instead of bricking startup.
- Normalize `NOVA_GITHUB_REPO` so update checks don't build a doubled URL.
- Stream-alert dedup/platform filtering; install missing socketio dependency.
- Send CLI prompts as UTF-8 (Windows cp1252 broke Codex stdin).
- Numerous MMD retarget, leg-IK, camera-zoom, and full-song-playback fixes.

## [1.1.0] - 2026-04-14

### Added
- Linux support.
- Alarm sounds and logo integration.
- Stop functionality for voice generation and chat input.

### Changed
- Refactored chat functionality; improved date/time parsing in reminders and alarms.
- Code structure refactor for readability and maintainability.

## [1.0.0] - 2026-04-13

First stable release — readiness, polish, and a multi-provider installer.

### Added
- App-readiness checks so actions can't fire before initialization completes.
- Multi-provider installer: support multiple LLM backends with richer configuration.
- Avatar System documentation (feature overview + usage).
- Alert notifications with sound for reminders and alarms.
- Logo/branding assets, installer banner, and a Windows window icon (via Win32 API).

### Changed
- Enhanced dashboard layout and controls.
- Installer GPU flow: selectable CUDA version, CUDA-enabled PyTorch by default, and a hardened native command runner (`Invoke-Native`).
- Shortcut now uses `logo.ico` from the data directory.

## [0.4.0] - 2026-04-10

The "huge updates" release — NovaAI becomes an Alexa-style assistant with a web GUI.

### Added
- Web browsing feature (enable / disable / query web context).
- Multiple TTS providers (XTTS and gTTS) with configuration options.
- Radio and music: internet radio + SoundCloud music playback.
- Reminders, alarms, to-do lists, shopping lists, and calendar.
- Web GUI: pywebview + Tailwind CSS frontend with a loading screen and dynamic init messages.

### Changed
- Unified Python setup script, replacing the old batch scripts.

## [0.3.0] - 2026-04-09

Audio subsystem overhaul and profile management.

### Added
- Speaker device selection in the GUI and audio handling.
- Profile management with the new `profiles.json` format.

### Changed
- Audio device handling is host-API-aware and prioritizes the device's native sample rate.
- Refactored audio playback and aligned XTTS speed configuration.

### Fixed
- Audio error handling and added audio resampling.

## [0.2.0] - 2026-04-09

### Added
- GUI setup flow and GitHub auto-updater.

### Changed
- `setup.bat` updated for Python and Ollama installation.
- Code-structure refactor for readability and maintainability.

## [0.1.0] - 2026-04-09

### Added
- Initial NovaAI companion app.
- Refactored into a modular package.
- Startup auto-tuning for performance optimization.

[1.1.1]: https://github.com/NekoSuneVR/NovaAI/compare/v1.1.0...1.1.1
[1.1.0]: https://github.com/NekoSuneVR/NovaAI/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/NekoSuneVR/NovaAI/compare/v0.4.0...v1.0.0
[0.4.0]: https://github.com/NekoSuneVR/NovaAI/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/NekoSuneVR/NovaAI/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/NekoSuneVR/NovaAI/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/NekoSuneVR/NovaAI/releases/tag/v0.1.0
