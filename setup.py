"""
NovaAI Setup — cross-platform installer (Windows + Linux).

    python setup.py              # full setup + launch GUI
    python setup.py --setup      # setup only, don't launch
    python setup.py --launch     # skip setup, launch GUI
    python setup.py --terminal   # skip setup, launch terminal mode
    python setup.py --update     # check for updates and apply
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import argparse
from pathlib import Path
from urllib.parse import urlparse

IS_WINDOWS = sys.platform == "win32"

ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe" if IS_WINDOWS else VENV_DIR / "bin" / "python"
SETUP_MARKER = ROOT_DIR / ".setup-complete"
ENV_FILE = ROOT_DIR / ".env"
ENV_EXAMPLE = ROOT_DIR / ".env.example"
DATA_DIR = ROOT_DIR / "data"
AUDIO_DIR = ROOT_DIR / "audio"
REQUIREMENTS = ROOT_DIR / "requirements.txt"
VOICE_REQUIREMENTS = ROOT_DIR / "requirements-voice.txt"
GUI_REQUIREMENTS = ROOT_DIR / "requirements-gui.txt"
DEFAULT_OLLAMA_MODEL = "dolphin3"
DEFAULT_OLLAMA_API_URL = "http://127.0.0.1:11434/api/chat"
OPENAI_COMPATIBLE_PROVIDERS = {
    "openai",
    "chatgpt",
    "openai-compatible",
    "openai_compatible",
    "custom",
    "custom-openai",
    "openrouter",
    "open-router",
    "lmstudio",
    "lm-studio",
    "lm studio",
    "litellm",
}

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


# ── Helpers ──────────────────────────────────────────────────────────────────

def banner(text: str) -> None:
    print(f"\n{'=' * 50}")
    print(f"  {text}")
    print(f"{'=' * 50}\n")


def step(num: int, total: int, msg: str) -> None:
    print(f"  [{num}/{total}] {msg}")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kwargs)


def has_winget() -> bool:
    return IS_WINDOWS and shutil.which("winget") is not None


def read_env_values() -> dict[str, str]:
    """Read simple KEY=VALUE pairs from .env."""
    if not ENV_FILE.exists():
        return {}
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def normalize_llm_provider(value: str) -> str:
    """Map OpenAI-compatible provider aliases to the runtime provider name."""
    normalized = value.strip().lower()
    if normalized in OPENAI_COMPATIBLE_PROVIDERS:
        return "openai"
    return "ollama"


def parse_bool_value(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def read_llm_setup_config() -> tuple[str, str, str]:
    """Read the provider and model needed for setup-time decisions."""
    env_values = read_env_values()
    provider = normalize_llm_provider(
        env_values.get("LLM_PROVIDER") or env_values.get("CHAT_PROVIDER") or "ollama"
    )
    if provider == "ollama":
        model = (
            env_values.get("OLLAMA_MODEL")
            or env_values.get("OLLAMA_MODEL")
            or DEFAULT_OLLAMA_MODEL
        )
    else:
        model = env_values.get("LLM_MODEL") or env_values.get("OPENAI_MODEL") or ""
    api_url = (
        env_values.get("LLM_API_URL")
        or env_values.get("OLLAMA_API_URL")
        or DEFAULT_OLLAMA_API_URL
    )
    return provider, model, api_url


def is_local_ollama_url(api_url: str) -> bool:
    """Return True when the Ollama endpoint points at this machine."""
    parsed = urlparse(api_url)
    host = (parsed.hostname or "").lower()
    return host in {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}


# ── Python / venv ────────────────────────────────────────────────────────────

def ensure_venv() -> None:
    """Create the .venv if it doesn't already exist."""
    if VENV_PYTHON.exists():
        return
    print("    Creating virtual environment...")
    run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if not VENV_PYTHON.exists():
        raise RuntimeError("Failed to create virtual environment.")


def resolve_install_profile() -> str:
    """Which dependency set to install.

    Controlled by NOVA_INSTALL_PROFILE (set by install.sh's profile prompt):
        minimal -> base only (text chat + headless web UI)
        voice   -> base + voice/ML extras
        gui     -> base + native desktop GUI extra
        full    -> base + voice + gui  (default; preserves Windows behavior)
    """
    profile = os.getenv("NOVA_INSTALL_PROFILE", "full").strip().lower()
    if profile in {"minimal", "voice", "gui", "full"}:
        return profile
    return "full"


def install_requirements() -> None:
    """Upgrade pip and install the requested dependency profile into the venv."""
    profile = resolve_install_profile()
    print("    Upgrading pip...")
    run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip", "-q"])

    req_files = [REQUIREMENTS]
    if profile in {"voice", "full"} and VOICE_REQUIREMENTS.exists():
        req_files.append(VOICE_REQUIREMENTS)
    if profile in {"gui", "full"} and GUI_REQUIREMENTS.exists():
        req_files.append(GUI_REQUIREMENTS)

    labels = {
        "minimal": "base (text + web UI)",
        "voice": "base + voice/ML extras",
        "gui": "base + desktop GUI",
        "full": "everything (voice + desktop GUI)",
    }
    print(f"    Installing packages [{labels[profile]}]...")
    cmd = [str(VENV_PYTHON), "-m", "pip", "install"]
    for req in req_files:
        cmd += ["-r", str(req)]
    cmd.append("-q")
    run(cmd)


# ── Game bridge (optional) ─────────────────────────────────────────────────────

def setup_minecraft_bridge() -> None:
    """Install Node deps for the Minecraft bridge if Node is available.

    Non-fatal: prints guidance and returns if Node is missing so users who
    don't want the game feature aren't forced to install Node.js.
    """
    bridge_dir = ROOT_DIR / "node" / "minecraft-bridge"
    if not (bridge_dir / "package.json").exists():
        print("    Minecraft bridge files not found - skipping.")
        return
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        print("    Node.js / npm not found - skipping game bridge install.")
        print("    Install Node 18+ from https://nodejs.org to enable game playing,")
        print(f"    then run: npm install (inside {bridge_dir})")
        return
    print(f"    Found Node: {node}")
    try:
        run([npm, "install"], cwd=str(bridge_dir))
        print("    Minecraft bridge dependencies installed.")
    except Exception as exc:
        print(f"    Warning: npm install failed - {exc}")
        print(f"    You can retry later with: npm install (inside {bridge_dir})")


# ── Project files ────────────────────────────────────────────────────────────

def ensure_project_files() -> None:
    """Create data/audio dirs and seed .env and profile if missing."""
    DATA_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)
        print("    Created .env from .env.example")
    profile_example = DATA_DIR / "profile.example.json"
    profile_target = DATA_DIR / "profile.json"
    if not profile_target.exists() and profile_example.exists():
        shutil.copy2(profile_example, profile_target)


# ── Ollama ───────────────────────────────────────────────────────────────────

def find_ollama() -> str | None:
    """Return the path to the ollama executable, or None."""
    found = shutil.which("ollama")
    if found:
        return found
    if IS_WINDOWS:
        local_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if local_path.exists():
            return str(local_path)
    return None


def install_ollama() -> None:
    if IS_WINDOWS:
        if not has_winget():
            print("    winget is not available. Please install Ollama manually:")
            print("    https://ollama.com/download")
            raise RuntimeError("Cannot auto-install Ollama without winget.")
        print("    Installing Ollama via winget...")
        run([
            "winget", "install", "-e", "--id", "Ollama.Ollama",
            "--source", "winget",
            "--accept-package-agreements", "--accept-source-agreements",
            "--disable-interactivity", "--silent",
        ])
    else:
        if not shutil.which("curl"):
            print("    curl is not available. Please install Ollama manually:")
            print("    https://ollama.com/download")
            raise RuntimeError("Cannot auto-install Ollama without curl.")
        print("    Installing Ollama via install script...")
        run(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"])


def ollama_is_running() -> bool:
    """Check if the Ollama API is reachable."""
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


def start_ollama(ollama_exe: str) -> None:
    """Start Ollama in the background and wait for it to come online."""
    if ollama_is_running():
        return

    if IS_WINDOWS:
        # Try the GUI app first, fall back to serve
        app_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
        if app_path.exists():
            subprocess.Popen([str(app_path)], creationflags=subprocess.DETACHED_PROCESS)
        else:
            subprocess.Popen(
                [ollama_exe, "serve"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    else:
        subprocess.Popen(
            [ollama_exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    print("    Waiting for Ollama to come online...", end="", flush=True)
    for _ in range(60):
        time.sleep(1)
        if ollama_is_running():
            print(" OK")
            return
        print(".", end="", flush=True)
    print()
    raise RuntimeError("Ollama did not come online within 60 seconds.")


def ensure_ollama_model(ollama_exe: str, model: str) -> None:
    """Pull the model if it's not already available."""
    result = subprocess.run(
        [ollama_exe, "show", model],
        capture_output=True,
    )
    if result.returncode == 0:
        print(f"    Model '{model}' is already available.")
        return
    print(f"    Pulling model '{model}'... (this may take a while)")
    run([ollama_exe, "pull", model])


# ── Model preloading ────────────────────────────────────────────────────────

def preload_models() -> None:
    """Preload faster-whisper and XTTS models via the bootstrap module."""
    print("    Preloading speech and voice models...")
    run([str(VENV_PYTHON), "-m", "novaai.bootstrap"])


# ── Full setup ───────────────────────────────────────────────────────────────

def full_setup() -> None:
    """Run the complete setup pipeline."""
    banner("NovaAI Setup")
    total = 9

    step(1, total, "Checking Python virtual environment...")
    ensure_venv()
    print("    Virtual environment ready.")

    step(2, total, "Installing Python packages...")
    install_requirements()
    print("    Dependencies installed.")

    step(3, total, "Preparing project files...")
    ensure_project_files()
    print("    Runtime files ready.")

    llm_provider, llm_model, llm_api_url = read_llm_setup_config()
    env_values = read_env_values()
    skip_local_ollama = parse_bool_value(
        env_values.get("OLLAMA_SKIP_LOCAL_SETUP")
        or env_values.get("SKIP_LOCAL_OLLAMA")
        or "false"
    )
    needs_ollama = (
        llm_provider == "ollama"
        and is_local_ollama_url(llm_api_url)
        and not skip_local_ollama
    )

    ollama_exe = None
    if needs_ollama:
        step(4, total, "Checking Ollama...")
        ollama_exe = find_ollama()
        if not ollama_exe:
            try:
                install_ollama()
                # Re-check after install
                ollama_exe = find_ollama()
            except RuntimeError as exc:
                print(f"    Warning: {exc}")
        if ollama_exe:
            print(f"    Found Ollama: {ollama_exe}")
        else:
            print("    Ollama not found - skipping Ollama steps.")
            print("    Install it later from https://ollama.com/download")

        if ollama_exe:
            step(5, total, "Starting Ollama...")
            try:
                start_ollama(ollama_exe)
                print("    Ollama is online.")
            except RuntimeError as exc:
                print(f"    Warning: {exc}")
                ollama_exe = None  # skip model pull

        if ollama_exe:
            step(6, total, f"Pulling chat model ({llm_model})...")
            try:
                ensure_ollama_model(ollama_exe, llm_model)
                print("    Model ready.")
            except Exception as exc:
                print(f"    Warning: Could not pull model - {exc}")
        else:
            step(5, total, "Skipping Ollama start (not installed).")
            step(6, total, "Skipping model pull (Ollama not available).")
    else:
        if llm_provider == "ollama":
            provider_label = f"remote Ollama endpoint: {llm_api_url}"
        else:
            provider_label = f"{llm_provider} ({llm_model})" if llm_model else llm_provider
        step(4, total, f"Skipping local Ollama for: {provider_label}")
        step(5, total, "Skipping Ollama start (not needed).")
        step(6, total, "Skipping Ollama model pull (not needed).")

    if resolve_install_profile() in {"voice", "full"}:
        step(7, total, "Preloading speech and voice models...")
        try:
            preload_models()
            print("    Models cached.")
        except Exception as exc:
            print(f"    Warning: Model preload failed — {exc}")
            print("    Models will be downloaded on first use instead.")
    else:
        step(7, total, "Skipping voice model preload (text/web-only install).")

    step(8, total, "Checking game bridge (Minecraft)...")
    game_enabled = parse_bool_value(env_values.get("GAME_ENABLED") or "false")
    if game_enabled:
        try:
            setup_minecraft_bridge()
        except Exception as exc:
            print(f"    Warning: game bridge setup failed — {exc}")
    else:
        print("    GAME_ENABLED is false - skipping (enable later in .env).")

    step(9, total, "Writing setup marker...")
    SETUP_MARKER.write_text(
        (
            f"setup_completed=1\n"
            f"llm_provider={llm_provider}\n"
            f"llm_model={llm_model}\n"
            f"llm_api_url={llm_api_url}\n"
        ),
        encoding="utf-8",
    )
    print("    Done.")

    banner("NovaAI Setup Complete")
    if is_headless():
        print("  Launch the web UI:     python setup.py --web   (open it in a browser)")
    else:
        print("  Launch the GUI:        python setup.py --launch")
        print("  Launch the web UI:     python setup.py --web   (browser / remote access)")
    print("  Launch terminal mode:  python setup.py --terminal")
    print("  Run full setup again:  python setup.py --setup")
    print()


# ── Launch ───────────────────────────────────────────────────────────────────

def is_headless() -> bool:
    """True when there's no graphical display to host the native GUI."""
    if IS_WINDOWS:
        return False
    if sys.platform == "darwin":
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def launch_gui() -> None:
    """Launch the desktop GUI."""
    if not VENV_PYTHON.exists() or not SETUP_MARKER.exists():
        full_setup()
    run([str(VENV_PYTHON), str(ROOT_DIR / "app.py"), "--gui"])


def launch_web() -> None:
    """Launch the headless browser web UI."""
    if not VENV_PYTHON.exists() or not SETUP_MARKER.exists():
        full_setup()
    run([str(VENV_PYTHON), str(ROOT_DIR / "app.py"), "--web"])


def launch_terminal() -> None:
    """Launch the terminal chat loop."""
    if not VENV_PYTHON.exists() or not SETUP_MARKER.exists():
        full_setup()
    run([str(VENV_PYTHON), str(ROOT_DIR / "app.py")])


def run_update() -> None:
    """Check for and apply updates."""
    if not VENV_PYTHON.exists():
        print("Run setup first: python setup.py --setup")
        raise SystemExit(1)
    run([str(VENV_PYTHON), "-m", "novaai.updater", "--apply"])


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="NovaAI — setup, launch, and update.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--setup",
        action="store_true",
        help="Run full setup only (don't launch).",
    )
    group.add_argument(
        "--launch",
        action="store_true",
        help="Launch the desktop GUI (runs setup first if needed).",
    )
    group.add_argument(
        "--web",
        action="store_true",
        help="Launch the headless browser web UI (runs setup first if needed).",
    )
    group.add_argument(
        "--terminal",
        action="store_true",
        help="Launch in terminal mode (runs setup first if needed).",
    )
    group.add_argument(
        "--update",
        action="store_true",
        help="Check for and apply updates from GitHub.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.setup:
        full_setup()
    elif args.launch:
        launch_gui()
    elif args.web:
        launch_web()
    elif args.terminal:
        launch_terminal()
    elif args.update:
        run_update()
    else:
        # Default: setup if needed, then launch. On a headless box (no display)
        # there's no window to show, so fall back to the browser web UI.
        if not VENV_PYTHON.exists() or not SETUP_MARKER.exists():
            full_setup()
        if is_headless():
            launch_web()
        else:
            launch_gui()


if __name__ == "__main__":
    main()
