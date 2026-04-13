"""
NovaAI Setup — one-script installer for Windows.

Replaces setup.bat, launch_gui.bat, and update.bat with a single entry point:

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

ROOT_DIR = Path(__file__).resolve().parent
VENV_DIR = ROOT_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
SETUP_MARKER = ROOT_DIR / ".setup-complete"
ENV_FILE = ROOT_DIR / ".env"
ENV_EXAMPLE = ROOT_DIR / ".env.example"
DATA_DIR = ROOT_DIR / "data"
AUDIO_DIR = ROOT_DIR / "audio"
REQUIREMENTS = ROOT_DIR / "requirements.txt"
DEFAULT_OLLAMA_MODEL = "dolphin3"

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
    return shutil.which("winget") is not None


def read_ollama_model() -> str:
    """Read OLLAMA_MODEL from .env, fall back to default."""
    if not ENV_FILE.exists():
        return DEFAULT_OLLAMA_MODEL
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("OLLAMA_MODEL=") and not line.startswith("#"):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if val:
                return val
    return DEFAULT_OLLAMA_MODEL


# ── Python / venv ────────────────────────────────────────────────────────────

def ensure_venv() -> None:
    """Create the .venv if it doesn't already exist."""
    if VENV_PYTHON.exists():
        return
    print("    Creating virtual environment...")
    run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if not VENV_PYTHON.exists():
        raise RuntimeError("Failed to create virtual environment.")


def install_requirements() -> None:
    """Upgrade pip and install requirements.txt into the venv."""
    print("    Upgrading pip...")
    run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    print("    Installing packages...")
    run([str(VENV_PYTHON), "-m", "pip", "install", "-r", str(REQUIREMENTS), "-q"])


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
    # Common Windows install location
    local_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if local_path.exists():
        return str(local_path)
    found = shutil.which("ollama")
    return found


def install_ollama() -> None:
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

    # Try the GUI app first, fall back to serve
    app_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
    if app_path.exists():
        subprocess.Popen([str(app_path)], creationflags=subprocess.DETACHED_PROCESS)
    else:
        subprocess.Popen(
            [ollama_exe, "serve"],
            creationflags=subprocess.CREATE_NO_WINDOW,
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
    total = 8

    step(1, total, "Checking Python virtual environment...")
    ensure_venv()
    print("    Virtual environment ready.")

    step(2, total, "Installing Python packages...")
    install_requirements()
    print("    Dependencies installed.")

    step(3, total, "Preparing project files...")
    ensure_project_files()
    print("    Runtime files ready.")

    ollama_model = read_ollama_model()

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
        print("    Ollama not found — skipping Ollama steps.")
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
        step(6, total, f"Pulling chat model ({ollama_model})...")
        try:
            ensure_ollama_model(ollama_exe, ollama_model)
            print("    Model ready.")
        except Exception as exc:
            print(f"    Warning: Could not pull model — {exc}")
    else:
        step(5, total, "Skipping Ollama start (not installed).")
        step(6, total, "Skipping model pull (Ollama not available).")

    step(7, total, "Preloading speech and voice models...")
    try:
        preload_models()
        print("    Models cached.")
    except Exception as exc:
        print(f"    Warning: Model preload failed — {exc}")
        print("    Models will be downloaded on first use instead.")

    step(8, total, "Writing setup marker...")
    SETUP_MARKER.write_text(
        f"setup_completed=1\nollama_model={ollama_model}\n",
        encoding="utf-8",
    )
    print("    Done.")

    banner("NovaAI Setup Complete")
    print("  Launch the GUI:        python setup.py --launch")
    print("  Launch terminal mode:  python setup.py --terminal")
    print("  Run full setup again:  python setup.py --setup")
    print()


# ── Launch ───────────────────────────────────────────────────────────────────

def launch_gui() -> None:
    """Launch the desktop GUI."""
    if not VENV_PYTHON.exists() or not SETUP_MARKER.exists():
        full_setup()
    run([str(VENV_PYTHON), str(ROOT_DIR / "app.py"), "--gui"])


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
    elif args.terminal:
        launch_terminal()
    elif args.update:
        run_update()
    else:
        # Default: setup if needed, then launch GUI
        if not VENV_PYTHON.exists() or not SETUP_MARKER.exists():
            full_setup()
        launch_gui()


if __name__ == "__main__":
    main()
