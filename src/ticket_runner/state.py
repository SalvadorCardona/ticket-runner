"""Lock, claims, logs and history, under ~/.local/state/ticket-runner.

The lock is the only thing stopping the systemd timer from picking up a ticket
already in flight: a run lasting longer than the interval is normal, two
simultaneous runs are not.

The claims are the other half of that: the column each in-flight ticket was
taken from, so that a run which dies mid-ticket is recovered as what it was
rather than as work to redo.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import state_dir


def logs_dir() -> Path:
    path = state_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def history_path() -> Path:
    state_dir().mkdir(parents=True, exist_ok=True)
    return state_dir() / "history.jsonl"


class Busy(Exception):
    """Another run is already in progress."""


@contextmanager
def lock():
    state_dir().mkdir(parents=True, exist_ok=True)
    path = state_dir() / "run.lock"
    handle = path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        handle.close()
        raise Busy(f"a run is already in progress (lock {path})") from error
    handle.write(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n")
    handle.flush()
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()
        path.unlink(missing_ok=True)


# Two publications of one pass run side by side, and both write this file at
# either end of their session. One lock, because a lost entry is a ticket that
# comes back as ready — which is the whole thing the file exists to prevent.
_claims_lock = threading.Lock()


def claims_path() -> Path:
    state_dir().mkdir(parents=True, exist_ok=True)
    return state_dir() / "claims.json"


def claim(ticket_id: str, status: str) -> None:
    """Remember which column a ticket was taken from.

    Claiming is done by moving a ticket to "in progress", which is what stops a
    second run from taking it — and which also erases where it came from. For a
    ticket taken from the ready column that costs nothing: `sweep` puts it back
    there, and being worked twice is what "ready" means. For one taken from the
    validated column it costs everything: re-doing the work of a ticket somebody
    had already accepted is not recovery, it is a second ticket.

    Local, and that is enough: `sweep` only ever recovers tickets this host
    claimed itself, so the note only has to survive on the machine that wrote
    it. Anything unreadable is no note at all, and the old behaviour resumes.
    """
    with _claims_lock:
        held = claims()
        held[ticket_id] = status
        _write_claims(held)


def release(ticket_id: str) -> None:
    """Forget a claim: the ticket has left "in progress" under its own steam."""
    with _claims_lock:
        held = claims()
        if held.pop(ticket_id, None) is not None:
            _write_claims(held)


def claims() -> dict[str, str]:
    try:
        loaded = json.loads(claims_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): str(value) for key, value in loaded.items()}


def _write_claims(held: dict[str, str]) -> None:
    try:
        claims_path().write_text(json.dumps(held, ensure_ascii=False), encoding="utf-8")
    except OSError:
        # A note nobody could write is a note nobody reads: the ticket goes back
        # to ready on a crash, exactly as it did before this existed.
        pass


def record(entry: dict) -> None:
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    with history_path().open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def history(limit: int = 20) -> list[dict]:
    path = history_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def prune_logs(days: int) -> int:
    """Drop session logs older than `days`. Zero keeps everything.

    A session log is a few hundred kilobytes and one is written per ticket; at
    a ten-second cadence that adds up quietly. The Notion comment keeps the
    summary either way, and the transcript lives in ~/.claude/projects.
    """
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for path in logs_dir().glob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def log_file(short: str) -> Path:
    """One log per session, named by the ticket's short id (see `short_id`)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return logs_dir() / f"{stamp}-{short}.jsonl"
