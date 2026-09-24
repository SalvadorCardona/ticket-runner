"""Writing what the runner keeps, so that neither a crash nor the umask shows.

Two ways a small file goes wrong, and both had happened here.

**Half a file.** `write_text` truncates first and writes after, and a process
killed in between — the timer's own SIGTERM, a laptop lid, a full disk — leaves
a file that reads as empty. Empty is not "unknown" for the files kept under the
state directory, it is an answer: no claims means every in-flight ticket comes
back as work to redo, no reconciliation stamps means what was deleted on one
board is created again on the other, no cursor means a channel reads a day of
messages twice. So the new content is written beside the file and renamed over
it: a rename within one directory is atomic, and a reader sees either the old
file or the new one, never the moment between them.

**A secret readable for a moment.** Writing with the umask and tightening with
`chmod` afterwards leaves a window in which a token, a password in a
configuration or a session transcript is readable by whoever the umask allows.
Created with `0o600` from its first byte, it never is.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import IO

PRIVATE = 0o600


def opener(mode: int = PRIVATE):
    """An `opener` for `open()`: created with `mode`, not with the umask's.

    A file that already existed is tightened to it too, before a byte is
    written — `os.open` alone only applies a mode to a file it creates.
    """

    def _open(path: str, flags: int) -> int:
        descriptor = os.open(path, flags, mode)
        try:
            os.fchmod(descriptor, mode)
        except OSError:
            pass  # not ours to change: a file somebody else owns stays theirs
        return descriptor

    return _open


def open_private(path: Path, mode: str = "w") -> IO[str]:
    """A text file opened for writing or appending, private from its creation."""
    return open(path, mode, encoding="utf-8", opener=opener())  # noqa: SIM115


def write_private(path: Path, text: str, mode: int = PRIVATE) -> None:
    """Write `text` in place, into a file nobody else could read at any point."""
    with open(path, "w", encoding="utf-8", opener=opener(mode)) as handle:
        handle.write(text)


def write_atomic(path: Path, text: str, mode: int = PRIVATE) -> None:
    """Replace `path` with `text` in one step: the old file, or the new one.

    The copy is named per process and per thread, so two writers never share
    one — the last rename wins, whole, which is what the in-memory locks around
    these files already assume. Raises OSError like `write_text` would, and
    leaves no copy behind when it does.
    """
    scratch = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        descriptor = os.open(scratch, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(scratch, path)
    finally:
        try:
            scratch.unlink()
        except FileNotFoundError:
            pass
