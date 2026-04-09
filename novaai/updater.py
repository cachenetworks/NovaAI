from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from .paths import ROOT_DIR, UPDATE_STATE_PATH, VERSION_PATH

DEFAULT_GITHUB_REPO = "cachenetworks/NovaAI"
DEFAULT_GITHUB_BRANCH = "main"
DEFAULT_UPDATE_CACHE_SECONDS = 21600
DEFAULT_AUTO_UPDATE_CHECK = True
DEFAULT_AUTO_UPDATE_INSTALL = True
GITHUB_REQUEST_HEADERS = {"User-Agent": "NovaAI-Updater"}

UPDATE_EXCLUDED_TOP_LEVEL = {
    ".env",
    ".git",
    ".setup-complete",
    ".venv",
    ".venv-xtts",
    "audio",
    "vendor",
}
UPDATE_EXCLUDED_RELATIVE = {
    Path("data/history.jsonl"),
    Path("data/profile.json"),
    Path("data/update_state.json"),
}


@dataclass(frozen=True)
class UpdateStatus:
    local_version: str
    remote_version: str | None
    update_available: bool
    repo_slug: str
    branch: str
    checked_at: str | None = None
    error: str | None = None


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_version_tuple(value: str) -> tuple[int, ...]:
    normalized = value.strip().lower().lstrip("v")
    if not normalized:
        return (0,)

    parts: list[int] = []
    for piece in normalized.split("."):
        digits = "".join(character for character in piece if character.isdigit())
        parts.append(int(digits or "0"))
    return tuple(parts)


def read_local_version() -> str:
    try:
        return VERSION_PATH.read_text(encoding="utf-8").strip() or "0.0.0"
    except FileNotFoundError:
        return "0.0.0"


def resolve_git_executable() -> str | None:
    git_executable = shutil.which("git")
    if git_executable:
        return git_executable

    if os.name != "nt":
        return None

    candidate_paths = (
        Path(r"C:\Program Files\Git\cmd\git.exe"),
        Path(r"C:\Program Files\Git\bin\git.exe"),
        Path(os.path.expandvars(r"%LocalAppData%\Programs\Git\cmd\git.exe")),
        Path(os.path.expandvars(r"%LocalAppData%\Programs\Git\bin\git.exe")),
    )
    for candidate_path in candidate_paths:
        if candidate_path.exists():
            return str(candidate_path)
    return None


def discover_repo_slug() -> str:
    configured = os.getenv("NOVA_GITHUB_REPO", "").strip()
    if configured:
        return configured

    if not (ROOT_DIR / ".git").exists():
        return DEFAULT_GITHUB_REPO

    git_executable = resolve_git_executable()
    if not git_executable:
        return DEFAULT_GITHUB_REPO

    try:
        result = subprocess.run(
            [git_executable, "remote", "get-url", "origin"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except Exception:
        return DEFAULT_GITHUB_REPO

    if result.returncode != 0:
        return DEFAULT_GITHUB_REPO

    slug = parse_repo_slug_from_remote(result.stdout.strip())
    return slug or DEFAULT_GITHUB_REPO


def parse_repo_slug_from_remote(remote_url: str) -> str | None:
    trimmed = remote_url.strip()
    if not trimmed:
        return None

    if trimmed.endswith(".git"):
        trimmed = trimmed[:-4]

    if "github.com/" in trimmed:
        return trimmed.split("github.com/", 1)[1].strip("/")

    if trimmed.startswith("git@github.com:"):
        return trimmed.split("git@github.com:", 1)[1].strip("/")

    return None


def get_branch_name() -> str:
    configured = os.getenv("NOVA_GITHUB_BRANCH", "").strip()
    return configured or DEFAULT_GITHUB_BRANCH


def load_update_cache() -> dict[str, Any]:
    try:
        return json.loads(UPDATE_STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_update_cache(payload: dict[str, Any]) -> None:
    UPDATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_STATE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_cache_window_seconds() -> int:
    raw_value = os.getenv("AUTO_UPDATE_CACHE_SECONDS", "").strip()
    if not raw_value:
        return DEFAULT_UPDATE_CACHE_SECONDS

    try:
        return max(0, int(raw_value))
    except ValueError:
        return DEFAULT_UPDATE_CACHE_SECONDS


def get_auto_update_check_enabled() -> bool:
    return parse_bool(
        os.getenv("AUTO_UPDATE_CHECK"),
        DEFAULT_AUTO_UPDATE_CHECK,
    )


def get_auto_update_install_enabled() -> bool:
    return parse_bool(
        os.getenv("AUTO_UPDATE_INSTALL"),
        DEFAULT_AUTO_UPDATE_INSTALL,
    )


def get_remote_version_url(repo_slug: str, branch: str) -> str:
    return f"https://raw.githubusercontent.com/{repo_slug}/{branch}/VERSION"


def get_remote_zip_url(repo_slug: str, branch: str) -> str:
    return f"https://github.com/{repo_slug}/archive/refs/heads/{branch}.zip"


def format_timestamp(unix_seconds: float) -> str:
    return datetime.fromtimestamp(unix_seconds).astimezone().isoformat(timespec="seconds")


def build_cached_status(
    cache: dict[str, Any],
    local_version: str,
    repo_slug: str,
    branch: str,
) -> UpdateStatus | None:
    cache_matches = (
        cache.get("repo_slug") == repo_slug
        and cache.get("branch") == branch
        and cache.get("local_version") == local_version
    )
    if not cache_matches:
        return None

    checked_at_unix = cache.get("checked_at_unix")
    remote_version = cache.get("remote_version")
    if not isinstance(checked_at_unix, (int, float)):
        return None
    if not isinstance(remote_version, str) or not remote_version:
        return None

    cache_window_seconds = get_cache_window_seconds()
    if cache_window_seconds <= 0:
        return None
    if time.time() - float(checked_at_unix) > cache_window_seconds:
        return None

    checked_at = cache.get("checked_at")
    return UpdateStatus(
        local_version=local_version,
        remote_version=remote_version,
        update_available=parse_version_tuple(remote_version)
        > parse_version_tuple(local_version),
        repo_slug=repo_slug,
        branch=branch,
        checked_at=checked_at if isinstance(checked_at, str) else None,
    )


def write_update_cache(
    local_version: str,
    remote_version: str,
    repo_slug: str,
    branch: str,
) -> str:
    checked_at_unix = time.time()
    checked_at = format_timestamp(checked_at_unix)
    save_update_cache(
        {
            "repo_slug": repo_slug,
            "branch": branch,
            "local_version": local_version,
            "remote_version": remote_version,
            "checked_at": checked_at,
            "checked_at_unix": checked_at_unix,
        }
    )
    return checked_at


def fetch_remote_version(
    repo_slug: str,
    branch: str,
    timeout: float = 5.0,
) -> str:
    response = requests.get(
        get_remote_version_url(repo_slug, branch),
        headers=GITHUB_REQUEST_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    remote_version = response.text.strip()
    if not remote_version:
        raise RuntimeError("GitHub did not return a usable VERSION file.")
    return remote_version


def check_for_updates(force: bool = False) -> UpdateStatus:
    load_dotenv()
    repo_slug = discover_repo_slug()
    branch = get_branch_name()
    local_version = read_local_version()

    if not force:
        cached_status = build_cached_status(
            load_update_cache(),
            local_version=local_version,
            repo_slug=repo_slug,
            branch=branch,
        )
        if cached_status is not None:
            return cached_status

    try:
        remote_version = fetch_remote_version(repo_slug, branch)
    except Exception as exc:
        return UpdateStatus(
            local_version=local_version,
            remote_version=None,
            update_available=False,
            repo_slug=repo_slug,
            branch=branch,
            error=str(exc),
        )

    checked_at = write_update_cache(
        local_version=local_version,
        remote_version=remote_version,
        repo_slug=repo_slug,
        branch=branch,
    )
    return UpdateStatus(
        local_version=local_version,
        remote_version=remote_version,
        update_available=parse_version_tuple(remote_version)
        > parse_version_tuple(local_version),
        repo_slug=repo_slug,
        branch=branch,
        checked_at=checked_at,
    )


def is_git_worktree_dirty() -> bool:
    if not (ROOT_DIR / ".git").exists():
        return False

    git_executable = resolve_git_executable()
    if not git_executable:
        return True

    try:
        result = subprocess.run(
            [git_executable, "status", "--porcelain"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except Exception:
        return True

    if result.returncode != 0:
        return True

    return bool(result.stdout.strip())


def should_skip_update_path(relative_path: Path) -> bool:
    if not relative_path.parts:
        return False
    if relative_path.parts[0] in UPDATE_EXCLUDED_TOP_LEVEL:
        return True
    return relative_path in UPDATE_EXCLUDED_RELATIVE


def download_update_archive(repo_slug: str, branch: str, destination: Path) -> None:
    response = requests.get(
        get_remote_zip_url(repo_slug, branch),
        headers=GITHUB_REQUEST_HEADERS,
        timeout=30,
        stream=True,
    )
    response.raise_for_status()
    with destination.open("wb") as zip_file:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                zip_file.write(chunk)


def extract_archive_root(zip_path: Path, extract_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(extract_dir)

    children = [child for child in extract_dir.iterdir() if child.is_dir()]
    if len(children) != 1:
        raise RuntimeError("Downloaded update archive had an unexpected layout.")
    return children[0]


def copy_update_tree(source_root: Path, destination_root: Path) -> None:
    for source_path in source_root.rglob("*"):
        relative_path = source_path.relative_to(source_root)
        if should_skip_update_path(relative_path):
            continue

        destination_path = destination_root / relative_path
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)


def rerun_setup() -> None:
    setup_script = ROOT_DIR / "setup.bat"
    if os.name != "nt" or not setup_script.exists():
        return

    result = subprocess.run(
        ["cmd", "/c", str(setup_script)],
        cwd=str(ROOT_DIR),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("setup.bat failed after updating NovaAI.")


def apply_update() -> UpdateStatus:
    status = check_for_updates(force=True)
    if status.error:
        raise RuntimeError(f"Could not check GitHub for updates. {status.error}")

    if not status.update_available:
        return status

    if is_git_worktree_dirty():
        raise RuntimeError(
            "This copy looks like a git checkout with local changes, so auto-update was skipped to avoid overwriting work."
        )

    with tempfile.TemporaryDirectory(prefix="novaai-update-") as temp_dir:
        temp_path = Path(temp_dir)
        zip_path = temp_path / "update.zip"
        download_update_archive(status.repo_slug, status.branch, zip_path)
        extracted_root = extract_archive_root(zip_path, temp_path / "archive")
        copy_update_tree(extracted_root, ROOT_DIR)

    rerun_setup()
    if status.remote_version:
        write_update_cache(
            local_version=status.remote_version,
            remote_version=status.remote_version,
            repo_slug=status.repo_slug,
            branch=status.branch,
        )
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check for or apply NovaAI updates.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Download and install the latest version from GitHub if an update is available.",
    )
    parser.add_argument(
        "--force-check",
        action="store_true",
        help="Ignore the cached update status and query GitHub right now.",
    )
    return parser


def print_status(status: UpdateStatus) -> None:
    print(f"Local version: {status.local_version}")
    print(f"GitHub repo: {status.repo_slug} ({status.branch})")
    if status.checked_at:
        print(f"Checked: {status.checked_at}")
    if status.error:
        print(f"Update check failed: {status.error}")
        return
    print(f"Remote version: {status.remote_version}")
    print(f"Update available: {'yes' if status.update_available else 'no'}")


def main() -> None:
    args = build_parser().parse_args()
    load_dotenv()

    if args.apply:
        try:
            status = apply_update()
        except Exception as exc:
            print(f"Update failed: {exc}")
            raise SystemExit(1) from exc

        if status.update_available:
            print(f"NovaAI updated from {status.local_version} to {status.remote_version}.")
        else:
            print(f"NovaAI is already up to date at {status.local_version}.")
        return

    print_status(check_for_updates(force=args.force_check))


if __name__ == "__main__":
    main()
