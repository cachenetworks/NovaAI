# Changelog

All notable changes to **NovaAI** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project aims to follow [Semantic Versioning](https://semver.org/).

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

[1.1.0]: https://github.com/NekoSuneVR/NovaAI/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/NekoSuneVR/NovaAI/compare/v0.4.0...v1.0.0
[0.4.0]: https://github.com/NekoSuneVR/NovaAI/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/NekoSuneVR/NovaAI/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/NekoSuneVR/NovaAI/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/NekoSuneVR/NovaAI/releases/tag/v0.1.0
