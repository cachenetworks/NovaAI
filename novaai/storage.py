from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

from .defaults import DEFAULT_PROFILE
from .paths import AUDIO_DIR, DATA_DIR, HISTORY_PATH, PROFILE_PATH


def clone_default_profile() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_PROFILE)


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)


def load_profile() -> dict[str, Any]:
    if not PROFILE_PATH.exists():
        save_profile(clone_default_profile())
        return clone_default_profile()

    with PROFILE_PATH.open("r", encoding="utf-8") as profile_file:
        profile = json.load(profile_file)

    updated_profile = clone_default_profile()
    updated_profile.update(profile)
    if updated_profile != profile:
        save_profile(updated_profile)
    return updated_profile


def save_profile(profile: dict[str, Any]) -> None:
    PROFILE_PATH.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_recent_history(max_turns: int) -> list[dict[str, str]]:
    if not HISTORY_PATH.exists() or max_turns <= 0:
        return []

    with HISTORY_PATH.open("r", encoding="utf-8") as history_file:
        lines = history_file.readlines()

    recent_lines = lines[-(max_turns * 2) :]
    messages: list[dict[str, str]] = []
    for line in recent_lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        role = entry.get("role")
        content = entry.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            messages.append({"role": role, "content": content})
    return messages


def append_history(role: str, content: str) -> None:
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "content": content,
    }
    with HISTORY_PATH.open("a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def reset_history() -> None:
    if HISTORY_PATH.exists():
        HISTORY_PATH.unlink()
