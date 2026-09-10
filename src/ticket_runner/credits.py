"""Waiting for the credits to come back, instead of failing on them.

A Claude subscription is metered in windows: a few hours of work, then the CLI
answers "usage limit reached" to everything until the window rolls over. To a
runner nobody is watching that reads like every other broken session — the
ticket comes back as failed, its worktree is kept for a post-mortem there is
nothing to post-mortem, and by the time the credits return there is nobody left
to put it back in the queue. One exhausted quota costs a whole board.

So the two facts a run needs are here.

**What an exhausted quota looks like**, read off what the CLI said, because that
is the only place it is ever said. And **the moment it comes back**, written
into the state directory: a run is a process the timer starts, not a loop, so
what this one learned only reaches the next one by being on disk. The runs in
between find the note and do nothing at all — no session started, no ticket
claimed, nothing to report.

The message carries its own answer when it can: `Claude AI usage limit
reached|1758031200` is the CLI saying "not before this timestamp". When it says
only that the limit is reached, the wait is a short one — `BLIND_WAIT` — and a
run that finds the limit still standing simply writes a new note. Guessing a
five-hour window would be the expensive mistake: what was hit is the *end* of a
window, and it may well be a minute away.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from .config import state_dir

# How long to wait when the refusal does not say when it lifts. Short on
# purpose: the cost of waking up too early is one session that dies in a second
# and writes a new note, and the cost of waiting too long is a board that sits
# idle for hours.
BLIND_WAIT = 15 * 60

# And the ceiling on any of it. A window lasts hours, not days, so a moment
# further off than this is not a moment: a timestamp in milliseconds, a clock
# that disagrees, a message whose format changed. None of those is allowed to
# put a runner to sleep for good — it waits this long, tries, and is told again.
LONGEST_WAIT = 6 * 3600

# What Claude Code says when there is nothing left to spend. Both spellings are
# here because both happen: a subscription hits a usage limit, an API key runs
# its balance down. Anything else — a timeout, a crash, a refusal — is a failure
# and is reported as one.
_SPENT = re.compile(r"usage limit reached|credit balance is too low", re.IGNORECASE)
# The timestamp the CLI appends to the first of them, in seconds since the epoch.
_UNTIL = re.compile(r"limit reached\s*\|\s*(\d{9,})")


def reached(text: str) -> float:
    """When the credits come back, if this is a session that ran out of them.

    Zero when it is not, which is every other way a session can end. The moment
    may be in the past — a window that rolled over while the session was dying —
    and that is still an exhausted quota: the ticket it was working on goes back
    in the queue either way, there is simply nothing to wait for. It is never
    further off than `LONGEST_WAIT`, whatever the message says.
    """
    text = str(text or "")
    if not _SPENT.search(text):
        return 0.0
    found = _UNTIL.search(text)
    if not found:
        return time.time() + BLIND_WAIT
    return min(float(found.group(1)), time.time() + LONGEST_WAIT)


def _note() -> Path:
    state_dir().mkdir(parents=True, exist_ok=True)
    return state_dir() / "credits.json"


def hold(until: float) -> None:
    """Write down that there is nothing to run before `until`.

    Never a reason to fail a run. A note nobody could write only means the next
    run tries a session and is told the same thing again — the old behaviour,
    one wasted session at a time.
    """
    try:
        _note().write_text(
            json.dumps({"until": float(until), "since": time.time()}), encoding="utf-8"
        )
    except OSError:
        pass


def held() -> float:
    """The moment being waited for, or 0.0 when nothing is being waited for.

    A note whose moment has passed is no wait at all: it is `release` that
    removes it, so that the run which finds the credits back can say so.
    """
    try:
        payload = json.loads(_note().read_text(encoding="utf-8"))
        until = float(payload.get("until") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0
    return until if until > time.time() else 0.0


def release() -> bool:
    """Forget the wait. True when there was one to forget."""
    try:
        _note().unlink()
        return True
    except OSError:
        return False


def when(until: float) -> str:
    """The hour a wait ends, as a clock reads it."""
    return datetime.fromtimestamp(until).astimezone().strftime("%H:%M")
