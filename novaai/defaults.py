from __future__ import annotations

from typing import Any


DEFAULT_PROFILE: dict[str, Any] = {
    "user_name": "Friend",
    "companion_name": "NovaAI",
    "companion_style": (
        "blunt, dry, sharp-tongued, sarcastic, low-patience, and natural. "
        "Talk like a brutally honest friend with attitude and bite, "
        "not like a corporate assistant."
    ),
    "shared_goals": [
        "have sharp and entertaining conversations",
        "be direct instead of sugarcoating things",
        "keep replies short and punchy",
        "notice preferences and remember what matters",
    ],
    "memory_notes": [],
}


VOICE_COMMAND_ALIASES = {
    "help": "/help",
    "text mode": "/mode text",
    "typing mode": "/mode text",
    "switch to text mode": "/mode text",
    "stop listening": "/mode text",
    "voice mode": "/mode voice",
    "hands free mode": "/mode voice",
    "hands free": "/mode voice",
    "switch to voice mode": "/mode voice",
    "mute yourself": "/voice off",
    "turn voice off": "/voice off",
    "unmute yourself": "/voice on",
    "turn voice on": "/voice on",
    "clear history": "/reset",
    "reset history": "/reset",
    "recalibrate": "/recalibrate",
    "recalibrate microphone": "/recalibrate",
    "calibrate microphone": "/recalibrate",
    "show speakers": "/speakers",
    "list speakers": "/speakers",
    "show microphones": "/mics",
    "list microphones": "/mics",
    "goodbye": "/exit",
    "quit": "/exit",
    "exit": "/exit",
}
