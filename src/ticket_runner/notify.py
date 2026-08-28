"""Desktop notifications, for work that happens while you look elsewhere.

The whole point of the runner is that you are not watching it. A ticket that
finishes in the background is worth one line on screen — otherwise you discover
your pull request tomorrow.

Everything here fails quietly: a machine with no notification daemon, a service
without a session bus, a missing `notify-send` — none of that is a reason for a
ticket to fail.
"""

from __future__ import annotations

import shutil
import subprocess

APP = "ticket-runner"


def send(title: str, body: str, *, urgent: bool = False) -> bool:
    binary = shutil.which("notify-send")
    if not binary:
        return False
    try:
        subprocess.run(
            [
                binary,
                "--app-name", APP,
                "--urgency", "critical" if urgent else "normal",
                "--icon", "dialog-warning" if urgent else "dialog-information",
                title,
                body,
            ],
            check=False,
            timeout=10,
            capture_output=True,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
