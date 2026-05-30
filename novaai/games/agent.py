"""GameAgent - the game-agnostic LLM control loop.

Each tick it observes the world, asks the LLM (via the shared engine) for a
short first-person thought plus one high-level command as JSON, narrates the
thought (so it appears in chat / TTS / avatar / stream), executes the command
through the driver, and feeds the outcome back in. Runs on a daemon thread and
never crashes the app.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Callable

from ..config import Config
from ..engine import GenerationRequest, detect_emotion, generate_reply
from .base import GameCommand, GameDriver

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_command(reply: str) -> dict[str, Any] | None:
    """Best-effort parse of the model's JSON action."""
    match = _JSON_RE.search(reply or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


class GameAgent:
    def __init__(
        self,
        driver: GameDriver,
        config: Config,
        profile_getter: Callable[[], dict[str, Any]],
        narrate: Callable[[str, str], None],
        on_update: Callable[[dict[str, Any]], None] | None = None,
        remember: Callable[[str], None] | None = None,
        tick_seconds: float = 4.0,
        goal: str = "explore and survive",
    ) -> None:
        self.driver = driver
        self.config = config
        self.profile_getter = profile_getter
        self.narrate = narrate
        self.on_update = on_update or (lambda _state: None)
        self.remember = remember or (lambda _text: None)
        self.tick_seconds = max(1.0, tick_seconds)
        self.goal = goal

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._log: list[dict[str, str]] = []  # short rolling game history

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="NovaAIGameAgent", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Abort any in-flight action immediately (e.g. a long pathfinder move):
        # stopping the driver makes the current observe/act call fail fast so the
        # loop unwinds instead of blocking until the action finishes.
        try:
            self.driver.stop()
        except Exception:
            pass

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def set_goal(self, goal: str) -> None:
        self.goal = goal.strip() or self.goal

    # ── loop ──────────────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            self.driver.start()
        except Exception as exc:
            self.narrate(f"I couldn't start the game: {exc}", "anxious")
            return
        self.narrate(f"Alright, let's play. Goal: {self.goal}.", "happy")

        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:
                self.narrate(f"Something went wrong: {exc}", "anxious")
            self._stop.wait(self.tick_seconds)

        try:
            self.driver.stop()
        except Exception:
            pass
        self.narrate("Okay, I'm done playing for now.", "neutral")

    def _tick(self) -> None:
        if self._stop.is_set():
            return
        obs = self.driver.observe()
        try:
            self.on_update(obs.raw)
        except Exception:
            pass
        if self._stop.is_set():
            return

        verbs = self.driver.available_verbs()
        verbs_help = ""
        if hasattr(self.driver, "verbs_help"):
            try:
                verbs_help = self.driver.verbs_help()
            except Exception:
                verbs_help = ""
        framing = (
            f"You are autonomously playing {self.driver.name}. Think out loud briefly in "
            "first person, then choose ONE action. Respond ONLY with JSON of the form "
            '{"thought": "<one or two in-character sentences>", "verb": "<one verb>", '
            '"args": {<key: value>}}. '
            f"Allowed verbs: {', '.join(verbs)}."
            + (f"\n{verbs_help}" if verbs_help else "")
        )
        user_prompt = (
            f"Goal: {self.goal}\n\nCurrent world state:\n{obs.text}\n\n"
            "Decide your next single action now."
        )

        result = generate_reply(
            GenerationRequest(
                user_text=user_prompt,
                profile=self.profile_getter(),
                config=self.config,
                source="game",
                extra_system=[framing],
                use_shared_history=False,
                history=list(self._log),
            )
        )

        if self._stop.is_set():
            return

        command = _extract_command(result.reply)
        if not command:
            # No parseable action; narrate the raw thought and wait.
            self.narrate(result.reply.strip()[:200] or "Hmm, let me think...", result.emotion)
            return

        thought = str(command.get("thought", "")).strip()
        verb = str(command.get("verb", "")).strip().lower()
        args = command.get("args") if isinstance(command.get("args"), dict) else {}

        if thought:
            self.narrate(thought, detect_emotion(thought))
            self.remember(f"While playing {self.driver.name}: {thought}")

        if not verb or verb not in verbs:
            return

        outcome = self.driver.act(GameCommand(verb=verb, args=args))
        outcome_text = str(outcome.get("message", outcome))

        # Keep a short rolling history so the model has continuity (cap length).
        self._log.append({"role": "assistant", "content": thought or f"{verb} {args}"})
        self._log.append({"role": "user", "content": f"Result: {outcome_text}"})
        if len(self._log) > 12:
            self._log = self._log[-12:]
