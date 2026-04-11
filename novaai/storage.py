from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

from .defaults import DEFAULT_PROFILE
from .paths import AUDIO_DIR, DATA_DIR, HISTORY_PATH, PROFILE_PATH, PROFILES_PATH

PROFILE_STORE_SCHEMA_VERSION = 2


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_json_with_fallback_encodings(path: Any) -> Any:
    last_error: UnicodeDecodeError | json.JSONDecodeError | None = None
    for encoding in ("utf-8", "cp1252"):
        try:
            with path.open("r", encoding=encoding) as source_file:
                return json.load(source_file)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to load JSON from {path}.")


def _safe_profile_id(value: str) -> str:
    lowered = value.strip().lower()
    cleaned = "".join(
        character if character.isalnum() else "-"
        for character in lowered
    )
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    return cleaned or "profile"


def _dedupe_profile_id(profile_id: str, existing_ids: set[str]) -> str:
    if profile_id not in existing_ids:
        return profile_id
    counter = 2
    while f"{profile_id}-{counter}" in existing_ids:
        counter += 1
    return f"{profile_id}-{counter}"


def _deep_merge_dicts(defaults: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = copy.deepcopy(defaults)
    for key, value in incoming.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _normalize_profile_lists(profile: dict[str, Any]) -> None:
    for key in ("shared_goals", "memory_notes", "tags"):
        value = profile.get(key)
        if isinstance(value, list):
            profile[key] = [str(item).strip() for item in value if str(item).strip()]
        else:
            profile[key] = []


def _normalize_profile(
    raw_profile: dict[str, Any] | None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    base_profile = copy.deepcopy(DEFAULT_PROFILE)
    if isinstance(raw_profile, dict):
        merged_profile = _deep_merge_dicts(base_profile, raw_profile)
    else:
        merged_profile = base_profile

    _normalize_profile_lists(merged_profile)

    resolved_id = _safe_profile_id(
        profile_id
        or str(
            merged_profile.get("profile_id")
            or merged_profile.get("profile_name")
            or merged_profile.get("companion_name")
            or "profile"
        )
    )
    merged_profile["profile_id"] = resolved_id

    if not str(merged_profile.get("profile_name", "")).strip():
        merged_profile["profile_name"] = (
            str(merged_profile.get("companion_name", "")).strip()
            or "Custom Profile"
        )

    created_at = str(merged_profile.get("created_at", "")).strip()
    updated_at = str(merged_profile.get("updated_at", "")).strip()
    if not created_at:
        created_at = _now_iso()
    if not updated_at:
        updated_at = created_at
    merged_profile["created_at"] = created_at
    merged_profile["updated_at"] = updated_at
    return merged_profile


def _touch_profile(profile: dict[str, Any]) -> dict[str, Any]:
    touched = copy.deepcopy(profile)
    created_at = str(touched.get("created_at", "")).strip() or _now_iso()
    touched["created_at"] = created_at
    touched["updated_at"] = _now_iso()
    return touched


def _build_default_store() -> dict[str, Any]:
    default_profile = _normalize_profile(copy.deepcopy(DEFAULT_PROFILE), "default")
    profile_id = default_profile["profile_id"]
    return {
        "schema_version": PROFILE_STORE_SCHEMA_VERSION,
        "active_profile_id": profile_id,
        "profiles": {
            profile_id: default_profile,
        },
    }


def _save_legacy_active_profile(profile: dict[str, Any]) -> None:
    PROFILE_PATH.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def clone_default_profile() -> dict[str, Any]:
    return _normalize_profile(copy.deepcopy(DEFAULT_PROFILE), "default")


def ensure_runtime_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)


def load_profile_store() -> dict[str, Any]:
    ensure_runtime_dirs()

    if not PROFILES_PATH.exists():
        if PROFILE_PATH.exists():
            legacy_profile = _load_json_with_fallback_encodings(PROFILE_PATH)
            normalized_legacy = _normalize_profile(legacy_profile)
            store = {
                "schema_version": PROFILE_STORE_SCHEMA_VERSION,
                "active_profile_id": normalized_legacy["profile_id"],
                "profiles": {
                    normalized_legacy["profile_id"]: normalized_legacy,
                },
            }
        else:
            store = _build_default_store()

        save_profile_store(store)
        _save_legacy_active_profile(store["profiles"][store["active_profile_id"]])
        return store

    try:
        with PROFILES_PATH.open("r", encoding="utf-8") as store_file:
            raw_store = json.load(store_file)
    except (json.JSONDecodeError, OSError):
        raw_store = _build_default_store()
        save_profile_store(raw_store)

    store_changed = False
    normalized_profiles: dict[str, dict[str, Any]] = {}
    existing_ids: set[str] = set()
    raw_profiles = raw_store.get("profiles")
    if not isinstance(raw_profiles, dict):
        raw_profiles = {}
        store_changed = True

    for raw_profile_id, raw_profile in raw_profiles.items():
        normalized_profile = _normalize_profile(raw_profile, str(raw_profile_id))
        deduped_id = _dedupe_profile_id(normalized_profile["profile_id"], existing_ids)
        if deduped_id != normalized_profile["profile_id"]:
            normalized_profile["profile_id"] = deduped_id
            store_changed = True
        existing_ids.add(deduped_id)
        normalized_profiles[deduped_id] = normalized_profile

    if not normalized_profiles:
        fallback_store = _build_default_store()
        normalized_profiles = fallback_store["profiles"]
        store_changed = True

    active_profile_id = str(raw_store.get("active_profile_id", "")).strip()
    if active_profile_id not in normalized_profiles:
        active_profile_id = sorted(normalized_profiles.keys())[0]
        store_changed = True

    normalized_store = {
        "schema_version": PROFILE_STORE_SCHEMA_VERSION,
        "active_profile_id": active_profile_id,
        "profiles": normalized_profiles,
    }

    if int(raw_store.get("schema_version", 0)) != PROFILE_STORE_SCHEMA_VERSION:
        store_changed = True
    if raw_store.get("active_profile_id") != active_profile_id:
        store_changed = True
    if raw_store.get("profiles") != normalized_profiles:
        store_changed = True

    if store_changed:
        save_profile_store(normalized_store)

    _save_legacy_active_profile(normalized_profiles[active_profile_id])
    return normalized_store


def save_profile_store(store: dict[str, Any]) -> None:
    ensure_runtime_dirs()
    PROFILES_PATH.write_text(
        json.dumps(store, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_profiles() -> list[dict[str, Any]]:
    store = load_profile_store()
    active_profile_id = store["active_profile_id"]
    summaries: list[dict[str, Any]] = []
    for profile_id, profile in store["profiles"].items():
        summaries.append(
            {
                "profile_id": profile_id,
                "profile_name": str(profile.get("profile_name", profile_id)),
                "description": str(profile.get("description", "")).strip(),
                "companion_name": str(profile.get("companion_name", "NovaAI")),
                "user_name": str(profile.get("user_name", "Friend")),
                "tags": list(profile.get("tags") or []),
                "updated_at": str(profile.get("updated_at", "")),
                "is_active": profile_id == active_profile_id,
            }
        )

    summaries.sort(
        key=lambda item: (
            0 if item["is_active"] else 1,
            item["profile_name"].lower(),
        )
    )
    return summaries


def get_active_profile_id() -> str:
    return load_profile_store()["active_profile_id"]


def load_profile(profile_id: str | None = None) -> dict[str, Any]:
    store = load_profile_store()
    resolved_profile_id = profile_id or store["active_profile_id"]
    profile = store["profiles"].get(resolved_profile_id)
    if profile is None:
        resolved_profile_id = store["active_profile_id"]
        profile = store["profiles"][resolved_profile_id]
    return copy.deepcopy(profile)


def load_profile_by_id(profile_id: str) -> dict[str, Any]:
    store = load_profile_store()
    profile = store["profiles"].get(profile_id)
    if profile is None:
        raise RuntimeError(f"Profile '{profile_id}' was not found.")
    return copy.deepcopy(profile)


def save_profile(profile: dict[str, Any]) -> None:
    store = load_profile_store()
    active_profile_id = store["active_profile_id"]
    existing_profile = store["profiles"].get(active_profile_id, {})
    normalized_profile = _normalize_profile(
        profile,
        profile_id=active_profile_id,
    )
    normalized_profile["created_at"] = str(
        existing_profile.get("created_at", normalized_profile["created_at"])
    )
    store["profiles"][active_profile_id] = _touch_profile(normalized_profile)
    save_profile_store(store)
    _save_legacy_active_profile(store["profiles"][active_profile_id])


def save_profile_by_id(profile_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    store = load_profile_store()
    if profile_id not in store["profiles"]:
        raise RuntimeError(f"Profile '{profile_id}' was not found.")

    existing_profile = store["profiles"][profile_id]
    normalized_profile = _normalize_profile(profile, profile_id=profile_id)
    normalized_profile["created_at"] = str(
        existing_profile.get("created_at", normalized_profile["created_at"])
    )
    touched_profile = _touch_profile(normalized_profile)
    store["profiles"][profile_id] = touched_profile
    save_profile_store(store)

    if store["active_profile_id"] == profile_id:
        _save_legacy_active_profile(touched_profile)
    return copy.deepcopy(touched_profile)


def set_active_profile(profile_id: str) -> dict[str, Any]:
    store = load_profile_store()
    if profile_id not in store["profiles"]:
        raise RuntimeError(f"Profile '{profile_id}' was not found.")
    store["active_profile_id"] = profile_id
    active_profile = _touch_profile(store["profiles"][profile_id])
    store["profiles"][profile_id] = active_profile
    save_profile_store(store)
    _save_legacy_active_profile(active_profile)
    return copy.deepcopy(active_profile)


def create_profile(
    profile_name: str,
    base_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store = load_profile_store()
    existing_ids = set(store["profiles"].keys())
    base_id = _safe_profile_id(profile_name)
    profile_id = _dedupe_profile_id(base_id, existing_ids)

    source_profile = copy.deepcopy(base_profile) if base_profile is not None else clone_default_profile()
    source_profile["profile_name"] = profile_name.strip() or f"Profile {len(existing_ids) + 1}"
    if base_profile is None:
        source_profile["companion_name"] = source_profile["profile_name"]
        source_profile["description"] = "New custom profile."
        source_profile["memory_notes"] = []

    normalized_profile = _normalize_profile(source_profile, profile_id=profile_id)
    now = _now_iso()
    normalized_profile["created_at"] = now
    normalized_profile["updated_at"] = now

    store["profiles"][profile_id] = normalized_profile
    save_profile_store(store)
    return copy.deepcopy(normalized_profile)


def delete_profile(profile_id: str) -> str:
    store = load_profile_store()
    profiles = store["profiles"]
    if profile_id not in profiles:
        raise RuntimeError(f"Profile '{profile_id}' was not found.")
    if len(profiles) <= 1:
        raise RuntimeError("You need at least one profile.")

    del profiles[profile_id]
    if store["active_profile_id"] == profile_id:
        new_active_profile_id = sorted(profiles.keys())[0]
        store["active_profile_id"] = new_active_profile_id
    else:
        new_active_profile_id = store["active_profile_id"]

    active_profile = _touch_profile(profiles[new_active_profile_id])
    profiles[new_active_profile_id] = active_profile
    save_profile_store(store)
    _save_legacy_active_profile(active_profile)
    return new_active_profile_id


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
