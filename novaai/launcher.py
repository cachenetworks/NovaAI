from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from .cli import main as cli_main
from .updater import (
    apply_update,
    check_for_updates,
    get_auto_update_check_enabled,
    get_auto_update_install_enabled,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
SETUP_MARKER = ROOT_DIR / ".setup-complete"
SETUP_PY = ROOT_DIR / "setup.py"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run NovaAI.")
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the desktop GUI instead of the terminal chat loop.",
    )
    return parser


def ensure_windows_setup() -> None:
    if os.name != "nt":
        return
    if SETUP_MARKER.exists():
        return
    if not SETUP_PY.exists():
        return

    print("First-time NovaAI setup is incomplete. Running setup...")
    result = subprocess.run(
        [sys.executable, str(SETUP_PY), "--setup"],
        cwd=str(ROOT_DIR),
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def restart_current_process() -> None:
    environment = os.environ.copy()
    environment["NOVA_SKIP_AUTO_UPDATE"] = "1"
    command = [sys.executable, str(ROOT_DIR / "app.py"), *sys.argv[1:]]
    subprocess.Popen(command, cwd=str(ROOT_DIR), env=environment)
    raise SystemExit(0)


def maybe_apply_startup_update() -> None:
    if os.getenv("NOVA_SKIP_AUTO_UPDATE") == "1":
        return

    load_dotenv()
    if not get_auto_update_check_enabled():
        return

    status = check_for_updates()
    if status.error:
        print(f"GitHub update check skipped: {status.error}")
        return

    if not status.update_available:
        return

    if not get_auto_update_install_enabled():
        print(
            f"NovaAI {status.remote_version} is available on GitHub. "
            "Run `python setup.py --update` when you want to install it."
        )
        return

    print(
        f"NovaAI {status.remote_version} is available on GitHub. "
        f"Updating from {status.local_version} now..."
    )
    try:
        apply_update()
    except Exception as exc:
        print(f"Auto-update skipped: {exc}")
        return

    print("NovaAI finished updating. Restarting with the latest files...")
    restart_current_process()


def main() -> None:
    args = build_parser().parse_args()
    ensure_windows_setup()
    maybe_apply_startup_update()
    if args.gui:
        from .webgui import main as gui_main

        gui_main()
        return

    cli_main()
