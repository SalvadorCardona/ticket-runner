"""What the user's systemd says about the timer — read for its next run.

`is-enabled` answers whether the timer is installed, not whether it will ever
fire again. A timer that counts from the boot (OnBootSec) or from the service's
last activation (OnUnitActiveSec) can be enabled, active, and have no next run
at all: that is how the runner went quiet for two hours on 7 September 2026,
behind a green tick. The next run is the thing worth reading, and the timer's
own state is what tells "no next run" apart from "the run is happening now".
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

UNIT = "ticket-runner.timer"


@dataclass(frozen=True)
class Timer:
    enabled: str
    """What `is-enabled` says — or `no systemd`, `not installed`, `unknown`."""
    substate: str = ""
    """`waiting`, `running` while the service is, `elapsed` once nothing is left."""
    armed: bool = False
    """Whether systemd holds a next run at all."""
    row: str = ""
    """The timer's line in `list-timers`: next, left, last, passed."""

    @property
    def running(self) -> bool:
        return self.substate == "running"

    @property
    def stalled(self) -> bool:
        """Enabled, and never going to fire: the one state a tick must not cover.

        A timer whose service is running has no next run either — it is
        computed when the service ends — and that is a run, not a fault.
        """
        return self.enabled == "enabled" and not self.running and not self.armed

    @property
    def label(self) -> str:
        return "stalled" if self.stalled else self.enabled


def read() -> Timer:
    if not shutil.which("systemctl"):
        return Timer(enabled="no systemd")
    try:
        enabled = _systemctl("is-enabled", UNIT).strip() or "not installed"
        shown = _systemctl(
            "show", UNIT,
            "-p", "SubState,NextElapseUSecRealtime,NextElapseUSecMonotonic",
        )
        listed = _systemctl("list-timers", UNIT, "--no-pager")
    except (OSError, subprocess.SubprocessError):
        return Timer(enabled="unknown")
    return describe(enabled, shown, listed)


def describe(enabled: str, shown: str, listed: str = "") -> Timer:
    """`read`, without systemd: what `is-enabled`, `show` and `list-timers` said.

    A monotonic timer reports its next run on the monotonic clock only —
    `NextElapseUSecRealtime` stays empty even while it is armed — and one with
    nothing left says `infinity` there. Either clock holding a value is a run.
    """
    fields: dict[str, str] = {}
    for line in shown.splitlines():
        key, _, value = line.partition("=")
        fields[key.strip()] = value.strip()
    realtime = fields.get("NextElapseUSecRealtime", "")
    monotonic = fields.get("NextElapseUSecMonotonic", "")
    rows = listed.strip().splitlines()
    return Timer(
        enabled=enabled,
        substate=fields.get("SubState", ""),
        armed=bool(realtime) or monotonic not in ("", "infinity"),
        row=rows[1].strip() if len(rows) > 1 else "",
    )


def _systemctl(*arguments: str) -> str:
    return subprocess.run(
        ["systemctl", "--user", *arguments], capture_output=True, text=True, timeout=5
    ).stdout
