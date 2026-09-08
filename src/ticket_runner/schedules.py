"""What comes back on its own: a recipe for a ticket, and how often it is born.

A ticket leaves once. Everything that *recurs* — Monday's dependency review, the
first-of-the-month report, the weekly digest — is retyped by hand, or is not
done at all. The parti pris, and it is what keeps the rest of the runner simple:
no second execution engine beside it, only **one more source of tickets**. A
schedule creates a row in the ready column, and everything after that is the
code that already exists.

Two things live here, and neither of them touches the network — which is what
makes the calendar testable at all:

- `read`, one row of the Schedules database reduced to plain Python, with what
  makes it unreadable spelled out in `problem` rather than raised;
- `next_occurrence`, the whole calendar: four cadences, and the first moment
  *strictly after* the one you hand it.

`scheduled_for` is here too, and that is deliberate. A date written on a ticket
and a date written on a schedule mean the same thing — a moment in this
machine's timezone, a bare date being midnight here and not noon UTC — and two
readings of a Notion date that drift apart is the sort of bug nobody finds.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import notion
from .config import Notion

# What a cadence may say. A select rather than free text, for the same reason as
# the model column: the point is to pick without remembering the spelling.
CADENCES = ("Hourly", "Daily", "Weekly", "Monthly")

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# "09:00", "9h30", "9". Anything else is a value nobody can act on, and saying so
# is better than guessing at an hour a ticket would then be born at.
_CLOCK = re.compile(r"^(\d{1,2})\s*(?:[:hH]\s*(\d{1,2})?)?$")


@dataclass
class Schedule:
    """One row of the Schedules database, as the runner reads it.

    `problem` is what stops it being acted on — an unknown cadence, an hour
    nobody can parse, a day that is neither a weekday nor a number. A schedule
    carrying one is skipped rather than failed: `doctor` names it, and the
    others go on being born.
    """

    page: notion.Page
    name: str
    cadence: str            # "" when absent or unknown
    at: str                 # "09:00"
    day: str                # "Monday" | "1".."31" | ""
    active: bool
    next: datetime | None   # None = never yet computed
    last: datetime | None
    last_ticket: str        # page id, "" when there is none
    project: str
    model: str
    priority: str
    problem: str = ""


def scheduled_for(value: object) -> datetime | None:
    """A Notion date, read in this machine's timezone.

    A bare date means the start of that day here: a ticket due "30 August"
    becomes eligible at midnight, not at noon UTC. A date with a time is taken
    as written, offset included. Anything unparseable is treated as no date at
    all — nothing is ever held back by a value the runner failed to read.
    """
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment.astimezone() if moment.tzinfo is None else moment


def read(page: notion.Page, settings: Notion) -> Schedule:
    """One schedule, and what — if anything — makes it unreadable.

    Never raises. A row somebody half filled in is a row the pass steps over,
    not a pass that stops: one broken schedule must not take the others with it.
    """
    def value(key: str) -> object:
        return notion.read(page, settings.prop(key))

    def first(key: str) -> str:
        related = value(key) or []
        return str(related[0]) if isinstance(related, list) and related else ""

    cadence = str(value("cadence") or "").strip()
    known = next((name for name in CADENCES if name.lower() == cadence.lower()), "")
    at = str(value("at") or "").strip()
    day = str(value("day") or "").strip()

    schedule = Schedule(
        page=page,
        name=page.title.strip() or "(untitled schedule)",
        cadence=known,
        at=at,
        day=day,
        active=bool(value("active")),
        next=scheduled_for(value("next_run")),
        last=scheduled_for(value("last_run")),
        last_ticket=first("last_ticket"),
        project=first("project"),
        model=str(value("model") or "").strip(),
        priority=str(value("priority") or "").strip(),
    )
    schedule.problem = _problem(schedule)
    return schedule


def _problem(schedule: Schedule) -> str:
    """Why this schedule cannot be acted on, in the words `doctor` prints."""
    if not schedule.cadence:
        return f"no cadence the runner knows — one of: {', '.join(CADENCES)}"
    if _clock(schedule.at) is None:
        return f"“{schedule.at}” is not an hour — write it as 09:00"
    if schedule.cadence == "Weekly" and schedule.day.strip() and _weekday(schedule.day) is None:
        return f"“{schedule.day}” is not a day of the week"
    if schedule.cadence == "Monthly" and _day_of_month(schedule.day) is None:
        return f"“{schedule.day}” is not a day of the month — 1 to 31"
    return ""


def next_occurrence(
    cadence: str, at: str = "", day: str = "", *, after: datetime
) -> datetime | None:
    """The first moment this cadence falls on, strictly after `after`.

    - **Hourly** — on the minute of `at`, so 09:35 means every hour at :35;
      an empty `at` means :00.
    - **Daily** — at `at`, tomorrow when the hour is already behind us.
    - **Weekly** — the next `day` at `at`. No day named means the weekday
      `after` itself falls on.
    - **Monthly** — the `day` of the month at `at`, clipped to the last day
      there is: the 31st in February is the 28th, or the 29th.

    `None` — never an exception — for a cadence nobody declared, an hour nobody
    can read, a day that means nothing. A schedule the runner cannot understand
    is one it leaves alone, and `doctor` is where that is said out loud.

    Aware in, aware out: the moment comes back in this machine's timezone, which
    is the one `scheduled_for` reads dates in.
    """
    clock = _clock(at)
    if clock is None:
        return None
    hour, minute = clock
    name = cadence.strip().lower()
    base = after.replace(tzinfo=None) if after.tzinfo else after

    if name == "hourly":
        moment = base.replace(minute=minute, second=0, microsecond=0)
        if moment <= base:
            moment += timedelta(hours=1)
    elif name == "daily":
        moment = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if moment <= base:
            moment += timedelta(days=1)
    elif name == "weekly":
        # No day named is not a mistake: it means "whichever day this is", which
        # is what a schedule written on a Tuesday with nothing else said meant.
        wanted = base.weekday() if not day.strip() else _weekday(day)
        if wanted is None:
            return None
        moment = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        moment += timedelta(days=(wanted - moment.weekday()) % 7)
        if moment <= base:
            moment += timedelta(days=7)
    elif name == "monthly":
        wanted = _day_of_month(day)
        if wanted is None:
            return None
        moment = _in_month(base.year, base.month, wanted, hour, minute)
        if moment <= base:
            year, month = (base.year + 1, 1) if base.month == 12 else (base.year, base.month + 1)
            moment = _in_month(year, month, wanted, hour, minute)
    else:
        return None

    return moment.astimezone() if after.tzinfo else moment


def _in_month(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """That day of that month, or the last one the month has.

    The 31st exists in seven months out of twelve. A monthly schedule set on it
    is not a schedule that skips February — it is one that lands on the 28th.
    """
    return datetime(year, month, min(day, calendar.monthrange(year, month)[1]), hour, minute)


def _clock(at: str) -> tuple[int, int] | None:
    """"09:35" → (9, 35). Empty is midnight; anything unreadable is None."""
    text = at.strip()
    if not text:
        return (0, 0)
    match = _CLOCK.match(text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    return (hour, minute) if hour < 24 and minute < 60 else None


def _weekday(day: str) -> int | None:
    """Monday → 0, and a shortened “Mon” too. None when it names no day at all.

    An empty day is read by the caller, which is the only place that knows what
    “whichever day it is” means.
    """
    text = day.strip().lower()
    if not text:
        return None
    for index, name in enumerate(_WEEKDAYS):
        if name.lower().startswith(text):
            return index
    return None


def _day_of_month(day: str) -> int | None:
    """"1".."31", and nothing said means the first of the month."""
    text = day.strip()
    if not text:
        return 1
    return int(text) if text.isdigit() and 1 <= int(text) <= 31 else None
