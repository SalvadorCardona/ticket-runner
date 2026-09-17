"""Waiting for the credits to come back, instead of failing on them.

A Claude subscription is metered in windows: a few hours of work, then the CLI
answers "usage limit reached" to everything until the window rolls over. To a
runner nobody is watching that reads like every other broken session — the
ticket comes back as failed, its worktree is kept for a post-mortem there is
nothing to post-mortem, and by the time the credits return there is nobody left
to put it back in the queue. One exhausted quota costs a whole board.

So the three facts a run needs are here.

**What an exhausted quota looks like**, read off what the CLI said, because that
is the only place it is ever said. **How much of the window is already spent**,
read off the very cache `/usage` draws — which is what lets a runner stop
*before* the wall rather than against it, and leave you enough of your own
subscription to open a terminal with. And **the moment it comes back**, written
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
import os
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


# The two waits, and they are not the same wait. `spent` is the wall: the CLI
# has refused, nothing at all can run, and a pass does not even read the board.
# `reserve` is the line drawn short of it — there is credit left, we are simply
# not spending the last of it — so a pass still merges what you validated and
# only declines to *start* anything. Two notes rather than one field, because a
# run reads each of them to answer a different question.
_NOTES = {"spent": "credits.json", "reserve": "reserve.json"}


def _note(what: str) -> Path:
    state_dir().mkdir(parents=True, exist_ok=True)
    return state_dir() / _NOTES[what]


def hold(until: float, *, what: str = "spent") -> None:
    """Write down that there is nothing to run before `until`.

    Never a reason to fail a run. A note nobody could write only means the next
    run tries a session and is told the same thing again — the old behaviour,
    one wasted session at a time.
    """
    try:
        _note(what).write_text(
            json.dumps({"until": float(until), "since": time.time()}), encoding="utf-8"
        )
    except OSError:
        pass


def held(*, what: str = "spent") -> float:
    """The moment being waited for, or 0.0 when nothing is being waited for.

    A note whose moment has passed is no wait at all: it is `release` that
    removes it, so that the run which finds the credits back can say so.
    """
    try:
        payload = json.loads(_note(what).read_text(encoding="utf-8"))
        until = float(payload.get("until") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0.0
    return until if until > time.time() else 0.0


def release(*, what: str = "spent") -> bool:
    """Forget the wait. True when there was one to forget."""
    try:
        _note(what).unlink()
        return True
    except OSError:
        return False


def when(until: float) -> str:
    """The hour a wait ends, as a clock reads it."""
    return datetime.fromtimestamp(until).astimezone().strftime("%H:%M")


def _store() -> Path:
    """Where Claude Code leaves what `/usage` shows.

    The CLI's own store, not ours — read, never written, and never a reason to
    fail: a shape that changed under us has to read as "nobody knows", not as a
    runner that stops working. `CLAUDE_CONFIG_DIR` moves the whole of it, so it
    is looked for there before the home directory.
    """
    directory = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if directory:
        return Path(directory).expanduser() / ".claude.json"
    return Path.home() / ".claude.json"


# The two windows a subscription is actually metered in, and the two `/usage`
# puts on screen: the session, which lasts hours, and the week. The others in
# that payload are scoped to a model or a surface and would stop a runner over
# a quota its sessions are not even spending.
_WINDOWS = ("five_hour", "seven_day")


def _window(raw: object) -> tuple[float, float] | None:
    """One window of the cache, as a percentage and the moment it rolls over.

    Nothing spent when its moment has *passed*, which is the whole reason a
    stale cache is safe to read. Claude Code wrote it during some earlier
    session; a window that has rolled over since is empty now, whatever the
    figure beside it says, and one that has not can only have filled further. A
    reading is therefore never an overestimate, which is the only direction that
    would matter: it delays a stop, it never invents one.

    `None` is the other answer entirely — this window says nothing usable — and
    it is what lets a payload whose shape changed read as "nobody knows" rather
    than as a subscription nobody has touched.
    """
    if not isinstance(raw, dict):
        return None
    percent = raw.get("utilization")
    if not isinstance(percent, (int, float)) or isinstance(percent, bool):
        return None
    moment = 0.0
    stated = raw.get("resets_at")
    if isinstance(stated, str) and stated.strip():
        try:
            moment = datetime.fromisoformat(stated.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
        if moment <= time.time():
            return 0.0, 0.0
    return float(percent), moment


def used() -> tuple[float, float] | None:
    """How much of the subscription is spent, and when that lets up.

    A percentage between 0 and 100, and a moment in seconds since the epoch —
    the **most constraining** of the two windows, because being at 20 % of the
    week and 97 % of the session means there is nothing to start either way. The
    moment is the one belonging to that window, so the wait it justifies ends
    exactly when the thing that caused it does; 0.0 when the cache names none.

    `None` is "nobody knows": no store, no cache in it, a shape that changed, a
    file being written as we read it. Every caller treats that as permission to
    carry on — a runner that stopped working because it could not find a JSON
    key would be a far worse failure than the one this guards against.
    """
    try:
        payload = json.loads(_store().read_text(encoding="utf-8"))
        windows = payload["cachedUsageUtilization"]["utilization"]
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if not isinstance(windows, dict):
        return None
    readings = [
        reading
        for reading in (_window(windows.get(name)) for name in _WINDOWS)
        if reading is not None
    ]
    # Not one window said anything a percentage could be read off. That is the
    # shape having changed, not a subscription nobody has touched.
    return max(readings) if readings else None
