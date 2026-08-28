"""Verrou, journaux et historique, sous ~/.local/state/ticket-runner.

Le verrou est la seule chose qui empêche le minuteur systemd de relancer un
ticket déjà en cours : un tour qui dure plus longtemps que l'intervalle est
normal, deux tours simultanés ne le sont pas.
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
    """Un autre tour est déjà en cours."""


@contextmanager
def lock():
    state_dir().mkdir(parents=True, exist_ok=True)
    path = state_dir() / "run.lock"
    handle = path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        handle.close()
        raise Busy(f"un tour est déjà en cours (verrou {path})") from error
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


def log_file(ticket_id: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return logs_dir() / f"{stamp}-{ticket_id[:8]}.jsonl"
