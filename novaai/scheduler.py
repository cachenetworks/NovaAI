"""
scheduler.py — Background daemon thread for reminder and alarm checks.

Designed for CLI use.  Every 30 seconds it checks the live profile dict for
due reminders and alarms, enqueues any that fired, and persists the updated
profile.

Usage
-----
    scheduler = FeatureScheduler(profile, save_profile)
    scheduler.start()

    # Inside the main event loop:
    for kind, item in scheduler.drain():
        # kind is "reminder" or "alarm"
        print(f"[{kind.capitalize()}] {item['title']}")

    scheduler.stop()   # call on clean shutdown
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Callable

from .features import check_due_alarms, check_due_reminders


class FeatureScheduler:
    """
    Daemon thread that polls reminders and alarms every INTERVAL seconds.

    Thread-safe: fires are delivered via an internal queue.
    Call drain() from the main thread to collect them without blocking.
    """

    INTERVAL: int = 30  # seconds between checks

    def __init__(
        self,
        profile: dict[str, Any],
        save_fn: Callable[[dict[str, Any]], None],
    ) -> None:
        self._profile = profile
        self._save_fn = save_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background check thread (idempotent)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="feature-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the background thread to stop."""
        self._stop.set()

    def drain(self) -> list[tuple[str, dict[str, Any]]]:
        """
        Return all pending (kind, item) events accumulated since the last
        call.  Non-blocking — safe to call from the main thread on every loop
        iteration.
        """
        events: list[tuple[str, dict[str, Any]]] = []
        try:
            while True:
                events.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        return events

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._check()
            except Exception:
                pass  # never crash the daemon thread
            self._stop.wait(self.INTERVAL)

    def _check(self) -> None:
        changed = False

        for r in check_due_reminders(self._profile):
            self._queue.put(("reminder", r))
            changed = True

        for a in check_due_alarms(self._profile):
            self._queue.put(("alarm", a))
            changed = True

        if changed:
            try:
                self._save_fn(self._profile)
            except Exception:
                pass
