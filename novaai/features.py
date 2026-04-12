"""
features.py — Reminders, alarms, calendar, to-do list, and shopping list.

Natural-language parsing and CRUD helpers.  All feature data lives inside the
active profile under profile["profile_details"], so the existing save_profile /
save_profile_by_id calls persist everything automatically.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

try:
    import dateparser as _dp  # type: ignore[import-untyped]
    _HAS_DATEPARSER = True
except ImportError:
    _HAS_DATEPARSER = False

# ── Weekday constants ─────────────────────────────────────────────────────────

_WEEKDAY_ORDER = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]
_WEEKDAY_ABBR: dict[str, str] = {
    "mon": "monday", "tue": "tuesday", "tues": "tuesday",
    "wed": "wednesday", "thu": "thursday", "thur": "thursday",
    "thurs": "thursday", "fri": "friday", "sat": "saturday", "sun": "sunday",
}

# ── Internal helpers ──────────────────────────────────────────────────────────


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _section(profile: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return (and normalise) a list section from profile['profile_details']."""
    details = profile.setdefault("profile_details", {})
    value = details.get(key)
    if not isinstance(value, list):
        value = []
        details[key] = value
    return value  # type: ignore[return-value]


def _fmt_datetime(dt: datetime) -> str:
    """Cross-platform human-friendly date/time string."""
    h = dt.hour
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{dt.day} {dt.strftime('%B')} {dt.year} at {h12}:{dt.minute:02d} {ampm}"


def _fmt_time(time_str: str) -> str:
    """Convert 'HH:MM' to '10:30 AM' style."""
    try:
        h, m = map(int, time_str.split(":"))
        ampm = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {ampm}"
    except ValueError:
        return time_str


# ── Date / time parsing ───────────────────────────────────────────────────────


def _expand_day(name: str) -> str:
    d = name.strip().lower()
    return _WEEKDAY_ABBR.get(d, d)


def parse_day_range(text: str) -> list[str] | None:
    """
    Convert a day specification into a sorted list of weekday name strings,
    or None meaning 'every day'.

    Examples
    --------
    "monday to friday"  → ["monday", ..., "friday"]
    "weekdays"          → ["monday", ..., "friday"]
    "weekends"          → ["saturday", "sunday"]
    "every day"         → None
    "mon, wed, fri"     → ["monday", "wednesday", "friday"]
    """
    lowered = re.sub(r"\s+", " ", text.strip().lower())

    if lowered in {"every day", "daily", "all week", "everyday", "all days"}:
        return None

    if lowered in {
        "weekdays", "weekday", "monday to friday",
        "mon to fri", "mon-fri", "monday-friday",
    }:
        return _WEEKDAY_ORDER[:5]

    if lowered in {
        "weekends", "weekend", "saturday and sunday",
        "sat and sun", "saturday-sunday",
    }:
        return _WEEKDAY_ORDER[5:]

    # "X to Y" range
    m = re.match(r"^(\w+)\s+to\s+(\w+)$", lowered)
    if m:
        start = _expand_day(m.group(1))
        end = _expand_day(m.group(2))
        if start in _WEEKDAY_ORDER and end in _WEEKDAY_ORDER:
            si = _WEEKDAY_ORDER.index(start)
            ei = _WEEKDAY_ORDER.index(end)
            if si <= ei:
                return _WEEKDAY_ORDER[si : ei + 1]

    # Comma/space-separated list of day names
    parts = re.split(r"[\s,]+(?:and\s*)?", lowered)
    valid = [_expand_day(p) for p in parts if _expand_day(p) in _WEEKDAY_ORDER]
    if valid:
        return valid

    return None  # fallback: unknown → treat as every day


_TIME_AMPM_RE = re.compile(
    r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*(am|pm)(?!\w)",
    re.IGNORECASE,
)
_TIME_24_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")


def _extract_time_str(text: str) -> str | None:
    """Pull the first recognisable time from *text* and return 'HH:MM'."""
    m = _TIME_AMPM_RE.search(text)
    if m:
        h = int(m.group(1))
        mins = int(m.group(2) or 0)
        ampm = m.group(3).lower()
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:{mins:02d}"
    m = _TIME_24_RE.search(text)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    return None


def _parse_any_datetime(text: str) -> datetime | None:
    """Parse a free-form date/time expression into a datetime object."""
    if _HAS_DATEPARSER:
        result = _dp.parse(
            text,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        )
        return result

    # Minimal fallback for simple 'HH[:MM][am/pm]' strings
    time_str = _extract_time_str(text)
    if not time_str:
        return None
    h, mins = map(int, time_str.split(":"))
    now = datetime.now()
    dt = now.replace(hour=h, minute=mins, second=0, microsecond=0)
    if dt <= now:
        dt += timedelta(days=1)
    return dt


# ── NLP regex patterns ────────────────────────────────────────────────────────

# Reminders
_REMIND_RE = re.compile(
    r"remind\s+me\s+(?:to\s+|about\s+)?(.+?)\s+(?:on|at|by|for)\s+(.+)",
    re.IGNORECASE,
)
_REMIND_SET_RE = re.compile(
    r"set\s+(?:a\s+|an\s+)?reminder\s+(?:to\s+|for\s+|about\s+)?(.+?)\s+(?:on|at|by)\s+(.+)",
    re.IGNORECASE,
)

# Alarm cancel
_ALARM_CANCEL_RE = re.compile(
    r"(?:turn\s+off|cancel|disable|stop|delete|remove)\s+"
    r"(?:the\s+|my\s+|all\s+)?alarm(?:s|\s+clock)?",
    re.IGNORECASE,
)
# Alarm set
_ALARM_SET_RE = re.compile(
    r"(?:set\s+(?:an?\s+)?alarm(?:\s+clock)?|wake\s+me\s+up|alarm\s+clock)\s*(.+)?",
    re.IGNORECASE,
)
# Bare "alarm 10am …"
_ALARM_BARE_RE = re.compile(
    r"^alarm\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?.*)",
    re.IGNORECASE,
)

# Todo
_TODO_ADD_RE = re.compile(
    r"add\s+(.+?)\s+to\s+(?:my\s+)?(?:to-?do|task)\s*(?:list)?",
    re.IGNORECASE,
)

# Shopping
_SHOP_ADD_RE = re.compile(
    r"add\s+(.+?)\s+to\s+(?:my\s+)?(?:shopping|grocery|groceries)\s*(?:list)?",
    re.IGNORECASE,
)

# Calendar
_CAL_ADD_RE = re.compile(
    r"add\s+(.+?)\s+to\s+(?:my\s+)?(?:calendar|schedule|diary)"
    r"(?:\s+(?:on|for|at)\s+(.+))?",
    re.IGNORECASE,
)
_CAL_SCHED_RE = re.compile(
    r"schedule\s+(.+?)\s+(?:for|on|at)\s+(.+)",
    re.IGNORECASE,
)

# Day-word detector (used to distinguish explicit day specs from garbage)
_DAY_WORDS_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"weekday|weekend|daily|every\s+day|mon|tue|wed|thu|fri|sat|sun)\b",
    re.IGNORECASE,
)

# ── Public parsing return type ────────────────────────────────────────────────


class FeatureResult:
    """Returned by all try_parse_* functions and handle_feature_request."""

    __slots__ = ("handled", "response", "save_needed")

    def __init__(
        self,
        handled: bool = False,
        response: str = "",
        save_needed: bool = False,
    ) -> None:
        self.handled = handled
        self.response = response
        self.save_needed = save_needed


# ── Parser functions ──────────────────────────────────────────────────────────


def try_parse_reminder(text: str, profile: dict[str, Any]) -> FeatureResult:
    """Detect 'remind me … on DATE' style sentences."""
    m = _REMIND_RE.search(text) or _REMIND_SET_RE.search(text)
    if not m:
        return FeatureResult()
    title = m.group(1).strip()
    time_expr = m.group(2).strip()
    due_dt = _parse_any_datetime(time_expr)
    if due_dt is None:
        return FeatureResult()
    add_reminder(profile, title, due_dt)
    return FeatureResult(
        handled=True,
        response=f"Got it. I'll remind you to {title} on {_fmt_datetime(due_dt)}.",
        save_needed=True,
    )


def try_parse_alarm(text: str, profile: dict[str, Any]) -> FeatureResult:
    """Detect set/cancel alarm sentences."""
    # Cancel first
    if _ALARM_CANCEL_RE.search(text):
        count = cancel_all_alarms(profile)
        msg = "All alarms turned off." if count else "No active alarms to turn off."
        return FeatureResult(handled=True, response=msg, save_needed=True)

    # Set alarm?
    m = _ALARM_SET_RE.search(text) or _ALARM_BARE_RE.search(text)
    if not m:
        return FeatureResult()
    remaining = (m.group(1) or "").strip()
    if not remaining:
        return FeatureResult()

    time_str = _extract_time_str(remaining)
    if not time_str:
        return FeatureResult()

    # "in N days" → one-shot specific date
    specific_date: str | None = None
    day_m = re.search(r"in\s+(\d+)\s+days?", remaining, re.IGNORECASE)
    if day_m:
        n = int(day_m.group(1))
        specific_date = (datetime.now() + timedelta(days=n)).strftime("%Y-%m-%d")

    # Remaining text after stripping time + "in N days" → look for day pattern
    days: list[str] | None = None
    day_spec = re.sub(
        r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?", "", remaining, flags=re.IGNORECASE
    )
    day_spec = re.sub(
        r"in\s+\d+\s+days?", "", day_spec, flags=re.IGNORECASE
    ).strip()
    if day_spec and _DAY_WORDS_RE.search(day_spec) and not specific_date:
        days = parse_day_range(day_spec)

    add_alarm(profile, time_str, days=days, specific_date=specific_date)
    time_display = _fmt_time(time_str)

    if specific_date:
        dt = datetime.strptime(specific_date, "%Y-%m-%d")
        date_display = dt.strftime("%A, %d %B")
        response = f"Alarm set for {time_display} on {date_display}."
    elif days:
        day_list = ", ".join(d.capitalize() for d in days)
        response = f"Alarm set for {time_display} on {day_list}."
    else:
        response = f"Alarm set for {time_display} daily."

    return FeatureResult(handled=True, response=response, save_needed=True)


def try_parse_todo(text: str, profile: dict[str, Any]) -> FeatureResult:
    """Detect 'add X to (my) todo/task list'."""
    m = _TODO_ADD_RE.search(text)
    if not m:
        return FeatureResult()
    item_text = m.group(1).strip()
    if not item_text:
        return FeatureResult()
    add_todo(profile, item_text)
    return FeatureResult(
        handled=True,
        response=f"Added '{item_text}' to your to-do list.",
        save_needed=True,
    )


def try_parse_shopping(text: str, profile: dict[str, Any]) -> FeatureResult:
    """Detect 'add X to (my) shopping/grocery list'."""
    m = _SHOP_ADD_RE.search(text)
    if not m:
        return FeatureResult()
    item_text = m.group(1).strip()
    if not item_text:
        return FeatureResult()
    add_shopping_item(profile, item_text)
    return FeatureResult(
        handled=True,
        response=f"Added '{item_text}' to your shopping list.",
        save_needed=True,
    )


def try_parse_calendar(text: str, profile: dict[str, Any]) -> FeatureResult:
    """Detect 'add X to calendar [on DATE]' or 'schedule X for DATE'."""
    m = _CAL_ADD_RE.search(text) or _CAL_SCHED_RE.search(text)
    if not m:
        return FeatureResult()
    title = m.group(1).strip()
    time_expr = (m.group(2) or "").strip()

    event_date: str | None = None
    event_time: str | None = None
    if time_expr:
        dt = _parse_any_datetime(time_expr)
        if dt:
            event_date = dt.strftime("%Y-%m-%d")
            event_time = dt.strftime("%H:%M")

    add_calendar_event(profile, title, event_date=event_date, event_time=event_time)

    if event_date and event_time:
        dt_obj = datetime.strptime(f"{event_date} {event_time}", "%Y-%m-%d %H:%M")
        formatted = _fmt_datetime(dt_obj)
        response = f"Added '{title}' to your calendar for {formatted}."
    elif event_date:
        dt_obj = datetime.strptime(event_date, "%Y-%m-%d")
        formatted = f"{dt_obj.day} {dt_obj.strftime('%B')} {dt_obj.year}"
        response = f"Added '{title}' to your calendar for {formatted}."
    else:
        response = f"Added '{title}' to your calendar."

    return FeatureResult(handled=True, response=response, save_needed=True)


def handle_feature_request(text: str, profile: dict[str, Any]) -> FeatureResult:
    """
    Try to match *text* against any feature intent (reminder, alarm, todo,
    shopping, calendar).  Returns the first match or an unhandled FeatureResult.
    """
    for parser in (
        try_parse_reminder,
        try_parse_alarm,
        try_parse_todo,
        try_parse_shopping,
        try_parse_calendar,
    ):
        result = parser(text, profile)
        if result.handled:
            return result
    return FeatureResult()


# ── Reminders CRUD ────────────────────────────────────────────────────────────


def add_reminder(
    profile: dict[str, Any],
    title: str,
    due_dt: datetime,
) -> dict[str, Any]:
    """Add a one-time reminder that fires at *due_dt*."""
    r: dict[str, Any] = {
        "id": _new_id("reminder"),
        "title": title,
        "due": due_dt.isoformat(sep=" ", timespec="minutes"),
        "created_at": _now_iso(),
        "completed": False,
    }
    _section(profile, "reminders").append(r)
    return r


def list_reminders(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_section(profile, "reminders"))


def delete_reminder_by_id(profile: dict[str, Any], reminder_id: str) -> bool:
    items = _section(profile, "reminders")
    before = len(items)
    items[:] = [r for r in items if r.get("id") != reminder_id]
    return len(items) < before


def check_due_reminders(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return reminders now due and mark them as completed in-place."""
    reminders = _section(profile, "reminders")
    now = datetime.now()
    fired: list[dict[str, Any]] = []
    for r in reminders:
        if r.get("completed"):
            continue
        try:
            due = datetime.fromisoformat(str(r.get("due", "")))
        except ValueError:
            continue
        if due <= now:
            r["completed"] = True
            fired.append(r)
    return fired


# ── Alarms CRUD ───────────────────────────────────────────────────────────────


def add_alarm(
    profile: dict[str, Any],
    time_str: str,
    days: list[str] | None = None,
    specific_date: str | None = None,
    label: str = "",
) -> dict[str, Any]:
    """
    Add an alarm.

    Parameters
    ----------
    time_str      : "HH:MM" 24-hour format.
    days          : None = every day; list of weekday names = those days only.
    specific_date : "YYYY-MM-DD" for a one-shot alarm on a specific date.
    label         : Human-readable label; auto-generated if empty.
    """
    alarm: dict[str, Any] = {
        "id": _new_id("alarm"),
        "label": label or f"Alarm at {_fmt_time(time_str)}",
        "time": time_str,
        "days": days,
        "specific_date": specific_date,
        "active": True,
        "last_fired": None,
        "created_at": _now_iso(),
    }
    _section(profile, "alarms").append(alarm)
    return alarm


def list_alarms(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_section(profile, "alarms"))


def cancel_all_alarms(profile: dict[str, Any]) -> int:
    """Deactivate all alarms. Returns count of alarms that were active."""
    alarms = _section(profile, "alarms")
    count = sum(1 for a in alarms if a.get("active"))
    for a in alarms:
        a["active"] = False
    return count


def cancel_alarm_by_id(profile: dict[str, Any], alarm_id: str) -> bool:
    for a in _section(profile, "alarms"):
        if a.get("id") == alarm_id:
            a["active"] = False
            return True
    return False


def _should_fire_alarm(alarm: dict[str, Any], now: datetime) -> bool:
    if not alarm.get("active"):
        return False
    try:
        a_h, a_m = map(int, str(alarm.get("time", "")).split(":"))
    except ValueError:
        return False
    if now.hour != a_h or now.minute != a_m:
        return False
    today_str = now.strftime("%Y-%m-%d")
    if alarm.get("last_fired") == today_str:
        return False
    specific_date = alarm.get("specific_date")
    if specific_date:
        return today_str == specific_date
    days = alarm.get("days")
    if days is not None:
        return now.strftime("%A").lower() in days
    return True  # every day


def check_due_alarms(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return alarms that should fire now. Updates last_fired in-place."""
    alarms = _section(profile, "alarms")
    now = datetime.now()
    fired: list[dict[str, Any]] = []
    for a in alarms:
        if _should_fire_alarm(a, now):
            a["last_fired"] = now.strftime("%Y-%m-%d")
            if a.get("specific_date"):  # one-shot → disable after firing
                a["active"] = False
            fired.append(a)
    return fired


# ── To-do CRUD ────────────────────────────────────────────────────────────────


def add_todo(profile: dict[str, Any], text: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": _new_id("todo"),
        "text": text,
        "done": False,
        "created_at": _now_iso(),
    }
    _section(profile, "todo_list").append(item)
    return item


def list_todos(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_section(profile, "todo_list"))


def toggle_todo(profile: dict[str, Any], todo_id: str) -> bool:
    for item in _section(profile, "todo_list"):
        if item.get("id") == todo_id:
            item["done"] = not item.get("done", False)
            return True
    return False


def delete_todo(profile: dict[str, Any], todo_id: str) -> bool:
    items = _section(profile, "todo_list")
    before = len(items)
    items[:] = [i for i in items if i.get("id") != todo_id]
    return len(items) < before


# ── Shopping list CRUD ────────────────────────────────────────────────────────


def add_shopping_item(profile: dict[str, Any], text: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": _new_id("shop"),
        "text": text,
        "done": False,
        "created_at": _now_iso(),
    }
    _section(profile, "shopping_list").append(item)
    return item


def list_shopping(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return list(_section(profile, "shopping_list"))


def toggle_shopping_item(profile: dict[str, Any], item_id: str) -> bool:
    for item in _section(profile, "shopping_list"):
        if item.get("id") == item_id:
            item["done"] = not item.get("done", False)
            return True
    return False


def clear_shopping_done(profile: dict[str, Any]) -> None:
    items = _section(profile, "shopping_list")
    items[:] = [i for i in items if not i.get("done")]


def clear_shopping_all(profile: dict[str, Any]) -> None:
    _section(profile, "shopping_list").clear()


# ── Calendar CRUD ─────────────────────────────────────────────────────────────


def add_calendar_event(
    profile: dict[str, Any],
    title: str,
    event_date: str | None = None,
    event_time: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": _new_id("event"),
        "title": title,
        "date": event_date or "",
        "time": event_time or "",
        "notes": notes,
        "created_at": _now_iso(),
    }
    _section(profile, "calendar").append(event)
    return event


def list_calendar_events(profile: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        _section(profile, "calendar"),
        key=lambda e: (e.get("date", ""), e.get("time", "")),
    )


def delete_calendar_event(profile: dict[str, Any], event_id: str) -> bool:
    events = _section(profile, "calendar")
    before = len(events)
    events[:] = [e for e in events if e.get("id") != event_id]
    return len(events) < before
