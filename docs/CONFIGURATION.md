# ⚙️ Configuration Reference

NovaAI is configured through environment variables in the `.env` file. Copy `.env.example` to `.env` and adjust as needed.

---

## 🧠 Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTO_TUNE_PERFORMANCE` | `true` | Auto-detect hardware and optimise settings on startup |
| `AUTO_TUNE_GOAL` | `balanced` | Tuning strategy: `speed`, `balanced`, or `quality` |
| `AUTO_UPDATE_CHECK` | `true` | Check GitHub for version updates on startup |
| `AUTO_UPDATE_INSTALL` | `true` | Automatically install updates (non-git installs only) |
| `AUTO_UPDATE_CACHE_SECONDS` | `21600` | Cache update check results for this many seconds |
| `HF_HUB_DISABLE_SYMLINKS_WARNING` | `1` | Suppress Hugging Face Windows symlink warnings |
| `NOVA_GITHUB_REPO` | `https://github.com/cachenetworks/NovaAI` | GitHub repo for update checks |
| `NOVA_GITHUB_BRANCH` | `main` | GitHub branch for update checks |

---

## 🤖 LLM Settings

### Provider Selection

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | Chat backend: `ollama` or `openai` |
| `LLM_MODEL` | `dolphin3` | Model name |
| `LLM_API_URL` | *(auto)* | Custom endpoint URL (blank = use provider default) |
| `LLM_API_KEY` | *(none)* | API key for OpenAI-compatible providers |
| `LLM_KEEP_ALIVE` | `30m` | How long Ollama keeps the model loaded |
| `LLM_NUM_PREDICT` | `1200` | Maximum reply tokens |
| `LLM_TEMPERATURE` | `0.95` | Response creativity (0.0 = deterministic, 2.0 = wild) |

### Ollama-Specific

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `dolphin3` | Ollama model name (overridden by `LLM_MODEL` if set) |
| `OLLAMA_API_URL` | `http://127.0.0.1:11434/api/chat` | Ollama API endpoint |
| `OLLAMA_KEEP_ALIVE` | `30m` | Model keep-alive duration |
| `OLLAMA_NUM_PREDICT` | `1200` | Token budget |
| `OLLAMA_TEMPERATURE` | `0.95` | Temperature |

### OpenAI-Compatible

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_MODEL` | *(none)* | Model name for OpenAI-compatible providers |
| `OPENAI_API_URL` | *(none)* | API endpoint URL |
| `OPENAI_API_KEY` | *(none)* | API key |

> 💡 The `openai` provider works with OpenAI, LM Studio, LiteLLM, and any other OpenAI-compatible API.

---

## 🌐 Web Search

| Variable | Default | Description |
|----------|---------|-------------|
| `WEB_BROWSING_ENABLED` | `true` | Enable web search features |
| `WEB_AUTO_SEARCH` | `false` | Auto-search for likely current-event questions |
| `WEB_SEARCH_PROVIDER` | `searxng` | Backend: `searxng` or `duckduckgo` |
| `WEB_SEARCH_URL` | `https://searxng.nekosunevr.co.uk/` | SearXNG endpoint |
| `WEB_MAX_RESULTS` | `5` | Number of results per lookup |
| `WEB_TIMEOUT_SECONDS` | `15` | Timeout for web requests |
| `WEB_REGION` | `us-en` | Region code for search results |
| `WEB_SAFESEARCH` | `moderate` | Safe search level: `off`, `moderate`, or `strict` |

---

## 🎵 Media

| Variable | Default | Description |
|----------|---------|-------------|
| `MEDIA_REGION` | `GB` | Radio station region: `GB`, `US`, `AU`, `CA`, `DE`, `JP`, `FR` |
| `MUSIC_PROVIDER_DEFAULT` | `soundcloud` | Default music platform: `soundcloud`, `spotify`, `deezer` |
| `SOUNDCLOUD_STREAM_ENDPOINT` | `https://dl.nekosunevr.co.uk/api/stream` | SoundCloud stream resolver |

---

## 🔊 Text-to-Speech (TTS)

| Variable | Default | Description |
|----------|---------|-------------|
| `TTS_PROVIDER` | `xtts` | Voice engine: `xtts` (local neural) or `gtts` (Google cloud) |
| `VOICE_ENABLED` | `false` | Start with voice replies enabled |
| `XTTS_MODEL_NAME` | `tts_models/multilingual/multi-dataset/xtts_v2` | XTTS model |
| `XTTS_LANGUAGE` | `en` | Speech language |
| `XTTS_SPEAKER` | `Ana Florence` | Voice name (use `/speakers` to list options) |
| `XTTS_SPEAKER_WAV` | *(none)* | Path to a custom voice clone WAV file |
| `XTTS_USE_GPU` | `true` | Use GPU for voice synthesis |
| `XTTS_STREAM_OUTPUT` | `true` | Stream audio while generating |
| `XTTS_STREAM_CHUNK_SIZE` | `20` | Streaming chunk size |
| `XTTS_STREAM_BUFFER_SECONDS` | `1.8` | Stream buffer duration |
| `XTTS_CHUNK_MAX_CHARS` | `240` | Max characters per TTS chunk |
| `XTTS_MAX_TEXT_CHARS` | `5000` | Max total spoken text per reply |
| `XTTS_SPEED` | `1.00` | Speaking pace (never overridden by auto-tune) |

---

## 🎙️ Speech-to-Text (STT)

| Variable | Default | Description |
|----------|---------|-------------|
| `STT_PROVIDER` | `faster-whisper` | STT engine: `faster-whisper` or `google` |
| `STT_USE_GPU` | `true` | Use GPU for transcription |
| `STT_MODEL` | `small.en` | Whisper model: `tiny.en`, `base.en`, `small.en`, `medium.en`, `large-v3` |
| `STT_COMPUTE_TYPE` | *(auto)* | Compute type (auto-detected based on hardware) |
| `STT_BEAM_SIZE` | `5` | Beam search width |
| `STT_BEST_OF` | `5` | Best-of-N sampling |
| `STT_VAD_FILTER` | `false` | Voice Activity Detection filter |
| `STT_LANGUAGE` | `en-US` | Recognition language |
| `STT_TIMEOUT_SECONDS` | `15` | Max wait time for speech |
| `STT_PHRASE_TIME_LIMIT_SECONDS` | `30` | Max single phrase duration |
| `STT_PAUSE_THRESHOLD_SECONDS` | `1.8` | Silence duration to end a phrase |
| `STT_NON_SPEAKING_DURATION_SECONDS` | `1.2` | Non-speaking duration threshold |
| `STT_AMBIENT_DURATION_SECONDS` | `0.6` | Ambient noise calibration duration |
| `STT_ENERGY_THRESHOLD` | `300` | Mic energy threshold for speech detection |
| `STT_DYNAMIC_ENERGY_THRESHOLD` | `true` | Dynamically adjust energy threshold |
| `INPUT_MODE` | `voice` | Default input mode: `voice` (hands-free) or `text` |

---

## 🔈 Audio Devices

| Variable | Default | Description |
|----------|---------|-------------|
| `MIC_DEVICE_INDEX` | *(auto)* | Pin a specific microphone by index (see `/mics`) |
| `SPEAKER_DEVICE_INDEX` | *(auto)* | Pin a specific speaker by index |
| `MIC_SAMPLE_RATE` | *(auto)* | Override mic sample rate |
| `MIC_CHUNK_SIZE` | `1024` | Audio capture chunk size |

---

## 💡 Tips

- Set `AUTO_TUNE_PERFORMANCE=false` if you want full manual control over performance settings.
- Use `AUTO_TUNE_GOAL=speed` on weaker hardware for snappier responses with smaller models.
- `XTTS_SPEED` is the one setting auto-tune **never** touches — your companion's voice stays consistent.
- Leave `LLM_API_URL` blank to use the provider's default endpoint. Only set it if you're running a custom server.
- `HISTORY_TURNS=10` means the LLM sees the last 10 exchanges for context. Increase for better memory, decrease for faster responses.
