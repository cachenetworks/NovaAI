#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# NovaAI — Linux installer
#
# Run with:
#   curl -fsSL https://raw.githubusercontent.com/cachenetworks/NovaAI/main/install.sh | bash
#
# Or if you already downloaded it:
#   chmod +x install.sh && ./install.sh
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_URL="https://github.com/cachenetworks/NovaAI"
REPO_BRANCH="main"
INSTALL_DIR="$HOME/NovaAI"
PYTHON_MIN="3.11"

# ── Colors ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
DIM='\033[2m'
WHITE='\033[1;37m'
NC='\033[0m'

step()  { echo -e "  ${MAGENTA}[$1]${NC} $2"; }
ok()    { echo -e "    ${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "    ${YELLOW}[!!]${NC} $1"; }
fail()  { echo -e "    ${RED}[X]${NC}  $1"; }
info()  { echo -e "         ${DIM}$1${NC}"; }

# ── Banner ───────────────────────────────────────────────────────────────────

show_banner() {
    echo ""
    echo -e "                 ${MAGENTA}o   o   o${NC}"
    echo -e "                 ${MAGENTA}|   |   |${NC}"
    echo -e "             ${MAGENTA}o--+-----------+--o${NC}"
    echo -e "             ${MAGENTA}o--${MAGENTA}|${NC}  ${WHITE}N o v a${NC}  ${MAGENTA}|${MAGENTA}--o${NC}"
    echo -e "             ${MAGENTA}o--${MAGENTA}|${NC}    ${CYAN}A I${NC}    ${MAGENTA}|${MAGENTA}--o${NC}"
    echo -e "             ${MAGENTA}o--${MAGENTA}|${NC}  ${DIM}[${NC} ${MAGENTA}***${NC} ${DIM}]${NC}  ${MAGENTA}|${MAGENTA}--o${NC}"
    echo -e "             ${MAGENTA}o--+-----------+--o${NC}"
    echo -e "                 ${MAGENTA}|   |   |${NC}"
    echo -e "                 ${MAGENTA}o   o   o${NC}"
    echo ""
    echo -e "        ${DIM}Your AI companion, built to vibe with you${NC}"
    echo ""
    echo -e "        ${DIM}This installer will set up everything you need.${NC}"
    echo -e "        ${DIM}Grab a coffee -- this might take a few minutes.${NC}"
    echo ""
}

# ── Helpers ──────────────────────────────────────────────────────────────────

ask_yes_no() {
    local question="$1"
    local default="${2:-y}"
    local hint
    if [[ "$default" == "y" ]]; then hint="[Y/n]"; else hint="[y/N]"; fi

    echo ""
    echo -ne "  ${CYAN}?${NC} $question $hint "
    read -r answer
    answer="${answer:-$default}"
    case "${answer,,}" in
        y|yes) return 0 ;;
        *)     return 1 ;;
    esac
}

ask_choice() {
    local question="$1"
    shift
    local options=("$@")
    local default=1

    echo ""
    echo -e "  ${CYAN}?${NC} $question"
    for i in "${!options[@]}"; do
        local num=$((i + 1))
        if [[ $num -eq $default ]]; then
            echo -e "    ${MAGENTA}> [$num]${NC} ${WHITE}${options[$i]}${NC}"
        else
            echo -e "      ${MAGENTA}[$num]${NC} ${DIM}${options[$i]}${NC}"
        fi
    done
    echo -ne "    Enter choice (1-${#options[@]}) [default: $default]: "
    read -r answer
    answer="${answer:-$default}"
    if [[ "$answer" =~ ^[0-9]+$ ]] && (( answer >= 1 && answer <= ${#options[@]} )); then
        echo "$answer"
    else
        echo "$default"
    fi
}

ask_input() {
    local prompt="$1"
    local default="${2:-}"

    echo ""
    if [[ -n "$default" ]]; then
        echo -ne "  ${CYAN}?${NC} $prompt [default: $default]: "
    else
        echo -ne "  ${CYAN}?${NC} $prompt: "
    fi
    read -r answer
    echo "${answer:-$default}"
}

has_cmd() { command -v "$1" &>/dev/null; }

version_ge() {
    # Returns 0 if $1 >= $2
    printf '%s\n%s\n' "$2" "$1" | sort -V -C
}

set_env_value() {
    local file="$1" key="$2" value="$3"
    [[ -f "$file" ]] || return
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

# True when there's no graphical display (e.g. a headless Raspberry Pi over SSH).
is_headless() {
    [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]
}

# Detect the system package manager + a sudo prefix (so we can install system libs).
detect_pkg_manager() {
    PKG_MGR=""
    PKG_INSTALL=""
    if has_cmd apt-get; then
        PKG_MGR="apt"; PKG_INSTALL="apt-get install -y"
    elif has_cmd dnf; then
        PKG_MGR="dnf"; PKG_INSTALL="dnf install -y"
    elif has_cmd pacman; then
        PKG_MGR="pacman"; PKG_INSTALL="pacman -S --noconfirm"
    fi
    SUDO=""
    if [[ "$(id -u)" != "0" ]] && has_cmd sudo; then SUDO="sudo"; fi
}

# Install the system libraries the chosen profile needs (best-effort, non-fatal).
install_system_deps() {
    detect_pkg_manager
    if [[ -z "$PKG_MGR" ]]; then
        warn "No known package manager (apt/dnf/pacman). Install system deps manually if needed:"
        info "  ffmpeg (audio), libportaudio2 (mic, voice profile), WebKitGTK (desktop GUI)."
        return
    fi

    # Map generic deps to per-distro package names.
    local pkgs=()
    case "$PKG_MGR" in
        apt)
            pkgs+=("ffmpeg")
            [[ "$NEED_VOICE" == "true" ]] && pkgs+=("libportaudio2" "portaudio19-dev")
            [[ "$NEED_GUI" == "true" ]] && pkgs+=("gir1.2-webkit2-4.1" "python3-gi" "gir1.2-gtk-3.0")
            ;;
        dnf)
            pkgs+=("ffmpeg")
            [[ "$NEED_VOICE" == "true" ]] && pkgs+=("portaudio" "portaudio-devel")
            [[ "$NEED_GUI" == "true" ]] && pkgs+=("webkit2gtk4.1" "python3-gobject" "gtk3")
            ;;
        pacman)
            pkgs+=("ffmpeg")
            [[ "$NEED_VOICE" == "true" ]] && pkgs+=("portaudio")
            [[ "$NEED_GUI" == "true" ]] && pkgs+=("webkit2gtk" "python-gobject" "gtk3")
            ;;
    esac

    info "Installing system packages: ${pkgs[*]}"
    if ! $SUDO $PKG_INSTALL "${pkgs[@]}"; then
        warn "Some system packages failed to install. NovaAI may still work; install them manually if a feature is missing."
    else
        ok "System packages installed."
    fi
}

# Ask which feature profile to install. Sets INSTALL_PROFILE / NEED_VOICE / NEED_GUI.
choose_install_profile() {
    local arch; arch="$(uname -m)"
    local default_hint="Minimal recommended for Raspberry Pi / headless servers."
    [[ "$arch" == "aarch64" || "$arch" == "arm"* ]] && default_hint="Detected ARM ($arch) — Minimal is recommended."

    info "$default_hint"
    local choice
    choice=$(ask_choice "Which feature set do you want to install?" \
        "Minimal       — text chat + browser web UI (smallest, recommended for Pi)" \
        "+ Voice       — also speech in/out, XTTS, embeddings (large; needs mic/speakers)" \
        "+ Desktop GUI — also the native pywebview window (needs a display)" \
        "Everything    — voice + desktop GUI")

    NEED_VOICE=false
    NEED_GUI=false
    case "$choice" in
        1) INSTALL_PROFILE="minimal" ;;
        2) INSTALL_PROFILE="voice"; NEED_VOICE=true ;;
        3) INSTALL_PROFILE="gui";   NEED_GUI=true ;;
        4) INSTALL_PROFILE="full";  NEED_VOICE=true; NEED_GUI=true ;;
        *) INSTALL_PROFILE="minimal" ;;
    esac
    ok "Install profile: $INSTALL_PROFILE"
}

# ── Step 1: Python ───────────────────────────────────────────────────────────

ensure_python() {
    step "1/7" "Checking for Python ${PYTHON_MIN}+..."

    local python_cmd=""
    for cmd in python3 python; do
        if has_cmd "$cmd"; then
            local ver
            ver=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+\.\d+' | head -1)
            if [[ -n "$ver" ]] && version_ge "$ver" "$PYTHON_MIN"; then
                python_cmd="$cmd"
                ok "Found $cmd $ver"
                echo "$python_cmd"
                return
            fi
        fi
    done

    fail "Python ${PYTHON_MIN}+ not found."
    echo ""
    info "Install Python ${PYTHON_MIN}+ using your package manager:"
    info "  Ubuntu/Debian:  sudo apt install python3.11 python3.11-venv"
    info "  Fedora:         sudo dnf install python3.11"
    info "  Arch:           sudo pacman -S python"
    info "  macOS:          brew install python@3.11"
    echo ""
    exit 1
}

# ── Step 2: LLM Provider ────────────────────────────────────────────────────

choose_llm_provider() {
    step "2/7" "Choose your LLM provider..."
    echo ""
    info "NovaAI works with local and cloud LLMs."
    info "Pick what works for you — you can always change it later in .env"
    echo ""

    local choice
    choice=$(ask_choice "Which LLM provider do you want to use?" \
        "Ollama        — free, runs locally, no API key needed (recommended)" \
        "OpenAI        — GPT-4o, GPT-4, etc. (requires API key)" \
        "OpenRouter    — tons of models, one API key (requires API key)" \
        "LM Studio     — local OpenAI-compatible server (no API key)" \
        "Custom        — any OpenAI-compatible endpoint")

    # Defaults
    LLM_PROVIDER="ollama"
    LLM_API_URL=""
    LLM_API_KEY=""
    LLM_MODEL="dolphin3"
    NEED_OLLAMA=true

    case "$choice" in
        1)
            LLM_PROVIDER="ollama"
            NEED_OLLAMA=true
            LLM_MODEL=$(ask_input "Which Ollama model?" "dolphin3")
            info "Popular models: dolphin3, llama3.1, mistral, gemma2, phi3"
            if ask_yes_no "Use an existing Ollama server endpoint instead of installing/running Ollama here?" "n"; then
                LLM_API_URL=$(ask_input "Enter Ollama endpoint URL (base URL or /api/chat)" "http://127.0.0.1:11434/api/chat")
                NEED_OLLAMA=false
                ok "Using Ollama server at: $LLM_API_URL"
            else
                ok "Using local Ollama with model: $LLM_MODEL"
            fi
            ;;
        2)
            LLM_PROVIDER="openai"
            NEED_OLLAMA=false
            LLM_API_URL="https://api.openai.com/v1/chat/completions"
            LLM_API_KEY=$(ask_input "Enter your OpenAI API key")
            [[ -z "$LLM_API_KEY" ]] && warn "No API key entered. You can add it later in .env (LLM_API_KEY=)"
            LLM_MODEL=$(ask_input "Which OpenAI model?" "gpt-4o-mini")
            info "Popular models: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo"
            ok "Using OpenAI with model: $LLM_MODEL"
            ;;
        3)
            LLM_PROVIDER="openai"
            NEED_OLLAMA=false
            LLM_API_URL="https://openrouter.ai/api/v1/chat/completions"
            LLM_API_KEY=$(ask_input "Enter your OpenRouter API key")
            if [[ -z "$LLM_API_KEY" ]]; then
                warn "No API key entered. You can add it later in .env (LLM_API_KEY=)"
                info "Get a key at: https://openrouter.ai/keys"
            fi
            LLM_MODEL=$(ask_input "Which model?" "meta-llama/llama-3.1-8b-instruct:free")
            info "Browse models at: https://openrouter.ai/models"
            ok "Using OpenRouter with model: $LLM_MODEL"
            ;;
        4)
            LLM_PROVIDER="openai"
            NEED_OLLAMA=false
            LLM_API_URL="http://localhost:1234/v1/chat/completions"
            LLM_MODEL=$(ask_input "Which model is loaded in LM Studio?" "local-model")
            info "Make sure LM Studio's local server is running before you start NovaAI."
            ok "Using LM Studio at localhost:1234"
            ;;
        5)
            LLM_PROVIDER="openai"
            NEED_OLLAMA=false
            LLM_API_URL=$(ask_input "Enter the API endpoint URL (e.g. https://my-server.com/v1/chat/completions)")
            LLM_API_KEY=$(ask_input "Enter the API key (leave blank if none)")
            LLM_MODEL=$(ask_input "Which model?" "default")
            ok "Using custom endpoint: $LLM_API_URL"
            ;;
    esac
}

# ── Step 3: Ollama ───────────────────────────────────────────────────────────

ensure_ollama() {
    if [[ "$NEED_OLLAMA" != "true" ]]; then
        step "3/7" "Skipping local Ollama install/start (not needed)."
        OLLAMA_EXE=""
        return
    fi

    step "3/7" "Checking for Ollama..."

    if has_cmd ollama; then
        OLLAMA_EXE="ollama"
        ok "Found Ollama: $(command -v ollama)"
        return
    fi

    warn "Ollama not found."

    if ask_yes_no "Install Ollama now?"; then
        if has_cmd curl; then
            info "Installing Ollama..."
            curl -fsSL https://ollama.com/install.sh | sh
            if has_cmd ollama; then
                OLLAMA_EXE="ollama"
                ok "Ollama installed."
                return
            fi
        else
            warn "curl not found. Install Ollama manually from https://ollama.com/download"
        fi
    fi

    OLLAMA_EXE=""
    info "Skipping Ollama. You can install it later."
}

# ── Step 4: Download ─────────────────────────────────────────────────────────

get_novaai() {
    step "4/7" "Downloading NovaAI..."

    if [[ -f "$INSTALL_DIR/setup.py" ]]; then
        ok "NovaAI already exists at $INSTALL_DIR"
        if ! ask_yes_no "Re-download / update it?" "n"; then
            return
        fi
    fi

    if has_cmd git; then
        if [[ -d "$INSTALL_DIR/.git" ]]; then
            info "Pulling latest changes..."
            if ! git -C "$INSTALL_DIR" pull origin "$REPO_BRANCH" --ff-only 2>&1; then
                warn "git pull failed. Trying fresh clone instead..."
                rm -rf "$INSTALL_DIR"
                git clone --branch "$REPO_BRANCH" --single-branch "$REPO_URL" "$INSTALL_DIR"
            fi
            ok "Updated via git."
        else
            info "Cloning from GitHub..."
            git clone --branch "$REPO_BRANCH" --single-branch "$REPO_URL" "$INSTALL_DIR"
            ok "Cloned to $INSTALL_DIR"
        fi
    else
        info "git not found — downloading as ZIP..."
        local zip_url="$REPO_URL/archive/refs/heads/$REPO_BRANCH.zip"
        local zip_path="/tmp/novaai-download.zip"
        local extract_path="/tmp/novaai-extract"

        if has_cmd curl; then
            curl -fsSL "$zip_url" -o "$zip_path"
        elif has_cmd wget; then
            wget -q "$zip_url" -O "$zip_path"
        else
            fail "Neither git, curl, nor wget found. Cannot download NovaAI."
            exit 1
        fi

        rm -rf "$extract_path"
        unzip -qo "$zip_path" -d "$extract_path"
        mkdir -p "$INSTALL_DIR"
        cp -rf "$extract_path"/NovaAI-*/* "$INSTALL_DIR/"
        rm -f "$zip_path"
        rm -rf "$extract_path"
        ok "Downloaded and extracted to $INSTALL_DIR"
    fi
}

# ── Step 5: Setup + .env ─────────────────────────────────────────────────────

run_setup() {
    step "5/7" "Running NovaAI setup..."
    info "This installs dependencies, downloads models, and prepares everything."
    echo ""

    local python_cmd="$1"

    # System libraries the chosen profile needs (ffmpeg, PortAudio, WebKitGTK).
    install_system_deps

    local env_file="$INSTALL_DIR/.env"
    if [[ ! -f "$env_file" && -f "$INSTALL_DIR/.env.example" ]]; then
        cp "$INSTALL_DIR/.env.example" "$env_file"
    fi
    if [[ -f "$env_file" ]]; then
        info "Configuring LLM provider in .env..."
        set_env_value "$env_file" "LLM_PROVIDER" "$LLM_PROVIDER"
        set_env_value "$env_file" "LLM_MODEL" "$LLM_MODEL"

        if [[ "$LLM_PROVIDER" == "ollama" ]]; then
            set_env_value "$env_file" "OLLAMA_MODEL" "$LLM_MODEL"
            set_env_value "$env_file" "LLM_API_URL" "$LLM_API_URL"
            set_env_value "$env_file" "OLLAMA_API_URL" "$LLM_API_URL"
            if [[ "$NEED_OLLAMA" == "true" ]]; then
                set_env_value "$env_file" "OLLAMA_SKIP_LOCAL_SETUP" "false"
            else
                set_env_value "$env_file" "OLLAMA_SKIP_LOCAL_SETUP" "true"
            fi
            set_env_value "$env_file" "LLM_API_KEY" ""
        else
            set_env_value "$env_file" "LLM_API_URL" "$LLM_API_URL"
            set_env_value "$env_file" "LLM_API_KEY" "$LLM_API_KEY"
            set_env_value "$env_file" "OPENAI_MODEL" "$LLM_MODEL"
            set_env_value "$env_file" "OPENAI_API_URL" "$LLM_API_URL"
            set_env_value "$env_file" "OPENAI_API_KEY" "$LLM_API_KEY"
        fi
        ok "LLM provider configured."
    fi

    # Tell setup.py which dependency profile to install (minimal/voice/gui/full).
    (cd "$INSTALL_DIR" && NOVA_INSTALL_PROFILE="${INSTALL_PROFILE:-full}" "$python_cmd" setup.py --setup)
    ok "Setup complete."
}

# ── Ollama start + pull ──────────────────────────────────────────────────────

start_ollama_and_pull() {
    [[ -z "$OLLAMA_EXE" ]] && return

    # Check if already running
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        ok "Ollama is already running."
    else
        info "Starting Ollama..."
        ollama serve &>/dev/null &
        disown

        info "Waiting for Ollama to come online..."
        local online=false
        for i in $(seq 1 60); do
            sleep 1
            if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
                online=true
                break
            fi
        done

        if [[ "$online" != "true" ]]; then
            warn "Ollama didn't start in time. You can start it manually later."
            return
        fi
        ok "Ollama is online."
    fi

    # Pull model
    info "Checking model '$LLM_MODEL'..."
    if ollama show "$LLM_MODEL" &>/dev/null; then
        ok "Model '$LLM_MODEL' is already available."
    else
        info "Pulling model '$LLM_MODEL'... (this may take a while)"
        if ollama pull "$LLM_MODEL"; then
            ok "Model '$LLM_MODEL' is ready."
        else
            warn "Could not pull model '$LLM_MODEL'. You can pull it later: ollama pull $LLM_MODEL"
        fi
    fi
}

# ── Step 6: GPU ──────────────────────────────────────────────────────────────

ask_gpu() {
    step "6/7" "GPU acceleration..."

    # Torch is only installed with the voice/full profiles, so CUDA torch is
    # irrelevant otherwise (and Raspberry Pi has no NVIDIA GPU at all).
    if [[ "$NEED_VOICE" != "true" ]]; then
        ok "Skipped (no voice/ML stack in this profile — nothing to accelerate)."
        return
    fi
    local arch; arch="$(uname -m)"
    if [[ "$arch" == "aarch64" || "$arch" == "arm"* ]]; then
        ok "Skipped (ARM device — no CUDA GPU). Voice runs on CPU."
        return
    fi

    local choice
    choice=$(ask_choice "Do you have an NVIDIA GPU for faster voice synthesis?" \
        "Yes — install CUDA-accelerated PyTorch" \
        "No  — stick with CPU-only (works fine, just slower voice)" \
        "Skip — I'll decide later")

    if [[ "$choice" == "1" ]]; then
        echo ""
        info "Pick the CUDA version that matches your GPU and driver."
        info "Not sure? Choose CUDA 12.8 — it works with most modern GPUs."
        info "Older GPUs (GTX 900/1000 series) or old drivers may need 11.8."
        echo ""

        local cuda_choice
        cuda_choice=$(ask_choice "Which CUDA version?" \
            "CUDA 12.8  — latest, RTX 20/30/40/50 series, newest drivers" \
            "CUDA 12.6  — stable, RTX 20/30/40 series" \
            "CUDA 12.4  — safe bet for most modern GPUs" \
            "CUDA 12.1  — slightly older drivers" \
            "CUDA 11.8  — legacy, GTX 900/1000 series or old drivers")

        local cuda_url cuda_label
        case "$cuda_choice" in
            1) cuda_url="https://download.pytorch.org/whl/cu128"; cuda_label="12.8" ;;
            2) cuda_url="https://download.pytorch.org/whl/cu126"; cuda_label="12.6" ;;
            3) cuda_url="https://download.pytorch.org/whl/cu124"; cuda_label="12.4" ;;
            4) cuda_url="https://download.pytorch.org/whl/cu121"; cuda_label="12.1" ;;
            5) cuda_url="https://download.pytorch.org/whl/cu118"; cuda_label="11.8" ;;
        esac

        info "Installing CUDA $cuda_label PyTorch... (this downloads ~2 GB)"
        local venv_python="$INSTALL_DIR/.venv/bin/python"
        if "$venv_python" -m pip install --upgrade --index-url "$cuda_url" torch torchaudio -q; then
            ok "CUDA $cuda_label PyTorch installed. Voice synthesis will be much faster!"
        else
            warn "CUDA install had issues. CPU mode will still work fine."
        fi

    elif [[ "$choice" == "2" ]]; then
        ok "Using CPU mode. You can add GPU support later."
        info "To add GPU later, run:"
        info "  $INSTALL_DIR/.venv/bin/python -m pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 torch torchaudio"
    else
        ok "Skipped. Default CPU mode works out of the box."
    fi
}

# ── Step 7: Desktop launcher ────────────────────────────────────────────────

ask_launcher() {
    step "7/7" "Desktop launcher..."

    # A .desktop launcher only makes sense for the native GUI on a machine with a display.
    if [[ "$NEED_GUI" != "true" ]] || is_headless; then
        ok "Skipped (headless / no desktop GUI). Start NovaAI with: python3 app.py --web"
        return
    fi

    if ask_yes_no "Create a desktop launcher for NovaAI?"; then
        local desktop_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
        mkdir -p "$desktop_dir"
        local launcher_path="$desktop_dir/novaai.desktop"
        local icon_path="$INSTALL_DIR/data/logo.png"

        cat > "$launcher_path" <<DESKTOP
[Desktop Entry]
Name=NovaAI
Comment=AI Companion Studio
Exec=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/app.py --gui
Icon=$icon_path
Terminal=false
Type=Application
Categories=Utility;
DESKTOP

        chmod +x "$launcher_path"

        # Also try to copy to Desktop if it exists
        local user_desktop="$HOME/Desktop"
        if [[ -d "$user_desktop" ]]; then
            cp "$launcher_path" "$user_desktop/NovaAI.desktop"
            chmod +x "$user_desktop/NovaAI.desktop"
        fi

        ok "Desktop launcher created."
    else
        ok "No launcher created."
    fi
}

# ── Finish ───────────────────────────────────────────────────────────────────

show_finish() {
    echo ""
    echo -e "  ${GREEN}╔══════════════════════════════════════╗${NC}"
    echo -e "  ${GREEN}║                                      ║${NC}"
    echo -e "  ${GREEN}║   ${WHITE}NovaAI is ready to go!${NC}             ${GREEN}║${NC}"
    echo -e "  ${GREEN}║                                      ║${NC}"
    echo -e "  ${GREEN}╚══════════════════════════════════════╝${NC}"
    echo ""
    echo -e "    ${DIM}Installed to:${NC} ${WHITE}$INSTALL_DIR${NC}"

    local provider_label
    if [[ "$LLM_PROVIDER" == "ollama" ]]; then
        provider_label="Ollama ($LLM_MODEL)"
    elif [[ "$LLM_API_URL" == *"openrouter"* ]]; then
        provider_label="OpenRouter ($LLM_MODEL)"
    elif [[ "$LLM_API_URL" == *"openai.com"* ]]; then
        provider_label="OpenAI ($LLM_MODEL)"
    elif [[ "$LLM_API_URL" == *"localhost:1234"* ]]; then
        provider_label="LM Studio ($LLM_MODEL)"
    else
        provider_label="Custom ($LLM_MODEL)"
    fi
    echo -e "    ${DIM}LLM:${NC}          ${WHITE}$provider_label${NC}"
    echo ""
    echo -e "    ${DIM}Profile:${NC}      ${WHITE}${INSTALL_PROFILE:-full}${NC}"
    echo ""
    echo -e "    ${DIM}To launch NovaAI anytime:${NC}"
    echo ""
    echo -e "      ${CYAN}cd $INSTALL_DIR${NC}"
    if is_headless || [[ "$NEED_GUI" != "true" ]]; then
        echo -e "      ${CYAN}python3 app.py --web${NC}   ${DIM}# then open the printed http://...:8800 URL in a browser${NC}"
        echo -e "      ${CYAN}python3 app.py${NC}         ${DIM}# or chat in this terminal${NC}"
    else
        echo -e "      ${CYAN}python3 setup.py${NC}       ${DIM}# desktop GUI${NC}"
        echo -e "      ${CYAN}python3 app.py --web${NC}   ${DIM}# or the browser web UI${NC}"
    fi
    echo ""
    echo -e "    ${DIM}Change LLM provider anytime by editing${NC} ${WHITE}.env${NC} ${DIM}in the install folder.${NC}"
    echo ""
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    show_banner

    # Step 1: Python
    local python_cmd
    python_cmd=$(ensure_python)

    # Step 2: LLM provider
    choose_llm_provider

    # Feature profile (minimal / voice / gui / full) — drives deps + system libs.
    choose_install_profile

    # Step 3: Ollama
    ensure_ollama

    # Step 4: Download
    get_novaai

    # Step 5: Setup + .env
    run_setup "$python_cmd"

    # Start Ollama + pull model if needed
    if [[ "$NEED_OLLAMA" == "true" && -n "$OLLAMA_EXE" ]]; then
        start_ollama_and_pull
    fi

    # Step 6: GPU
    ask_gpu

    # Step 7: Desktop launcher
    ask_launcher

    show_finish

    if ask_yes_no "Launch NovaAI now?"; then
        echo ""
        info "Starting NovaAI..."
        local venv_python="$INSTALL_DIR/.venv/bin/python"
        # Headless / no-GUI profile -> browser web UI; otherwise the native window.
        if is_headless || [[ "$NEED_GUI" != "true" ]]; then
            (cd "$INSTALL_DIR" && "$venv_python" app.py --web)
        else
            (cd "$INSTALL_DIR" && "$venv_python" app.py --gui)
        fi
    fi
}

# ── Run ──────────────────────────────────────────────────────────────────────

main "$@"
