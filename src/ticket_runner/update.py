"""Keeping the installation on the latest version, with nobody asking for it.

The runner already wakes up on a timer, so it does not need a second one: a run
looks at the clock before it looks at the tickets, and once an hour it asks the
remote whether the installed code is still the newest. One `git fetch` in the
install directory answers that — which is why `install.sh` *clones* the
repository there rather than unpacking a tarball. "Am I up to date" is a
question git already knows how to answer; a version number in a file would only
be a second, less truthful copy of it.

An update lands **between** two runs, never inside one. The check happens under
the run lock and before a single ticket is claimed, so no session is ever
swapped out from under itself; the code that just landed takes over on the next
pass, which is at most one interval away.

An installation made from a local copy (`TR_SRC=.`) has no remote to compare
itself against. That is not an error and never fails a run — it is said once,
and the runner carries on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import git
from .config import state_dir


def app_dir() -> Path:
    """Where the sources live — the directory `install.sh` filled."""
    return Path(__file__).resolve().parents[2]


@dataclass
class Status:
    current: str = ""
    latest: str = ""
    reason: str = ""

    @property
    def stale(self) -> bool:
        """True only when both sides are known and they differ.

        A check that could not reach the remote is not an update: the runner
        must never reinstall itself on the strength of a missing answer.
        """
        return bool(self.current and self.latest and self.current != self.latest)


def _stamp() -> Path:
    state_dir().mkdir(parents=True, exist_ok=True)
    return state_dir() / "update.json"


def remember(status: Status) -> None:
    """Record that a check happened, and what it found.

    The timestamp is what rate-limits the whole thing: it is written whether the
    check succeeded or not, so an unreachable remote is asked once an hour like
    everything else, not once per run.
    """
    payload = {
        "checked_at": time.time(),
        "current": status.current,
        "latest": status.latest,
        "reason": status.reason,
    }
    try:
        _stamp().write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def remembered() -> Status:
    """What the last check found, without asking the remote again.

    The console draws its header on every reconnection, and a `git fetch`
    behind that would be one per laptop lid. The stamp a run already writes
    answers the same question for free — and answers "nothing known yet" as an
    empty Status, which reads as "up to date" rather than as a warning.
    """
    try:
        payload = json.loads(_stamp().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Status()
    return Status(
        current=str(payload.get("current") or ""),
        latest=str(payload.get("latest") or ""),
        reason=str(payload.get("reason") or ""),
    )


def last_check() -> float:
    try:
        return float(json.loads(_stamp().read_text(encoding="utf-8"))["checked_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def due(interval_seconds: int) -> bool:
    """Has the interval elapsed? An installation never checked is due at once."""
    return time.time() - last_check() >= interval_seconds


def _look(app: Path) -> Status:
    if not (app / ".git").exists():
        return Status(
            reason=f"{app} is a copy, not a clone — run install.sh again to follow the repository"
        )
    ref = git.git(["rev-parse", "--abbrev-ref", "HEAD"], app).out
    if not ref or ref == "HEAD":
        # Installed on a tag (TR_REF=v1.2): a fixed revision is a choice, and
        # following the default branch instead would quietly undo it.
        return Status(reason=f"{app} is pinned to a fixed revision — nothing to follow")
    fetched = git.git(["fetch", "--quiet", "origin", ref], app, timeout=120)
    if not fetched.ok:
        return Status(reason=f"git fetch: {fetched.err or fetched.out}")
    current = git.git(["rev-parse", "HEAD"], app).out
    latest = git.git(["rev-parse", "FETCH_HEAD"], app).out
    if not current or not latest:
        return Status(reason=f"nothing to compare in {app}")
    return Status(current=current, latest=latest)


def check(app: Path | None = None) -> Status:
    """What is installed, against what the remote has.

    Never raises: a remote that hangs until the timeout, or a directory that has
    become unreadable, are answers like any other. Checking a version is not
    worth failing a run over.
    """
    try:
        status = _look(app or app_dir())
    except (OSError, subprocess.SubprocessError) as error:
        status = Status(reason=f"version not checked: {error}")
    remember(status)
    return status


# -- what install.sh generates outside the app directory ----------------------


def _binary() -> Path:
    return Path(shutil.which("ticket-runner") or Path.home() / ".local/bin/ticket-runner")


def write_launcher(app: Path | None = None) -> Path:
    """Rewrite ~/.local/bin/ticket-runner from the template in the app directory.

    Safe to do from the runner itself: the launcher `exec`s Python, so by the
    time this runs the shell that read it is long gone.
    """
    app = app or app_dir()
    binary = _binary()
    text = (app / "bin" / "ticket-runner.in").read_text()
    text = text.replace("@APP_DIR@", str(app)).replace("@PYTHON@", sys.executable)
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(text)
    binary.chmod(0o755)
    return binary


def write_units(interval_seconds: int, app: Path | None = None) -> Path:
    """Regenerate the systemd units from the templates shipped with the app.

    The interval lives in the configuration, not in the unit: changing a number
    and running `ticket-runner enable` is a better story than reinstalling.
    """
    app = app or app_dir()
    units = Path.home() / ".config" / "systemd" / "user"
    units.mkdir(parents=True, exist_ok=True)

    service = (app / "systemd" / "ticket-runner.service.in").read_text()
    service = service.replace("@BIN@", str(_binary())).replace("@PATH@", os.environ.get("PATH", ""))
    (units / "ticket-runner.service").write_text(service)

    timer = (app / "systemd" / "ticket-runner.timer.in").read_text()
    timer = timer.replace("@INTERVAL@", str(interval_seconds))
    timer = timer.replace("@ACCURACY@", "1s" if interval_seconds < 60 else "30s")
    (units / "ticket-runner.timer").write_text(timer)

    # The console's unit is written whether or not it is enabled: writing it
    # costs nothing, and an update that refreshed the timer but left the console
    # on last month's ExecStart would be the kind of half-update this module
    # exists to prevent. Enabling it stays a decision — it opens a port.
    console = app / "systemd" / "ticket-runner-web.service.in"
    if console.exists():
        text = console.read_text()
        text = text.replace("@BIN@", str(_binary())).replace("@PATH@", os.environ.get("PATH", ""))
        (units / "ticket-runner-web.service").write_text(text)
    return units


def apply(status: Status, interval_seconds: int, app: Path | None = None) -> str:
    """Move the installation to `status.latest`. Returns "" or what went wrong.

    What `install.sh` writes outside the app directory is written again from the
    sources that just landed — otherwise a version changing the launcher or the
    systemd units would be installed everywhere except where it counts.
    """
    app = app or app_dir()
    try:
        reset = git.git(["reset", "--hard", "--quiet", status.latest], app)
    except (OSError, subprocess.SubprocessError) as error:
        return f"git reset: {error}"
    if not reset.ok:
        return f"git reset: {reset.err or reset.out}"
    try:
        write_launcher(app)
        if shutil.which("systemctl"):
            write_units(interval_seconds, app)
            git.run(["systemctl", "--user", "daemon-reload"])
    except (OSError, subprocess.SubprocessError) as error:
        return f"code updated, but the installed files could not be regenerated: {error}"
    return ""
