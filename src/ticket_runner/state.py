"""Lock, logs and history, under ~/.local/state/ticket-runner.

The lock is the only thing stopping the systemd timer from picking up a ticket
already in flight: a run lasting longer than the interval is normal, two
simultaneous runs are not.
"""

from __future__ import annotations

import fcntl
import json
import os
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
