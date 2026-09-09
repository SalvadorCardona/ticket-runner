"""Desktop notifications, for work that happens while you look elsewhere.

The whole point of the runner is that you are not watching it. A ticket that
finishes in the background is worth one line on screen — otherwise you discover
your pull request tomorrow.

And a line naming a ticket is worth clicking: the click opens that ticket's
Notion page, rather than leaving you to find the title again on the board.
`notify-send` cannot do that — it posts and forgets, never handing back the
identifier the desktop answers a click with, and more than one machine refuses
its `--action` outright while the desktop behind it supports actions perfectly
well. So a notification with somewhere to go is posted over D-Bus and followed
by a process of our own, detached: a run must not wait for somebody to look at
their screen. Everything else is still `notify-send`.

Everything here fails quietly: a machine with no notification daemon, a service
without a session bus, a missing `notify-send` — none of that is a reason for a
ticket to fail. A click that leads nowhere is not either, so every step of the
clickable path falls back to the plain notification.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

APP = "ticket-runner"
BUS = "org.freedesktop.Notifications"
OBJECT = "/org/freedesktop/Notifications"

# `default` is the action a click on the body of a notification triggers, by the
# freedesktop specification; the label is for a desktop that draws actions as
# buttons too. Written as a GVariant array, which is what `gdbus` reads.
ACTIONS = '["default", "Open the ticket"]'

# How long the child follows its notification. A desktop that keeps notifications
# in a tray only says one was closed when you clear it, which can be days — and a
# process per ticket, kept for days, is a worse bargain than a click nobody made
# within the hour.
LIFETIME = 3600


def send(title: str, body: str, *, urgent: bool = False, link: str = "") -> bool:
    """One line on screen — and, with `link`, one that takes you to the ticket."""
    if link and _hand_over(title, body, urgent=urgent, link=link):
        return True
    return _plain(title, body, urgent=urgent)


def _plain(title: str, body: str, *, urgent: bool) -> bool:
    binary = shutil.which("notify-send")
    if not binary:
        return False
    try:
        subprocess.run(
            [
                binary,
                "--app-name", APP,
                "--urgency", "critical" if urgent else "normal",
                "--icon", _icon(urgent),
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


def _icon(urgent: bool) -> str:
    return "dialog-warning" if urgent else "dialog-information"


def _hand_over(title: str, body: str, *, urgent: bool, link: str) -> bool:
    """Give the notification to a child that outlives this run.

    The child is this very module, run as one: it posts the notification, waits
    for the click, and opens the link. `PYTHONPATH` carries our own `src` to it
    so that it can import us however the parent was started — from the installed
    copy, from a checkout, or from a test.
    """
    if not all(shutil.which(tool) for tool in ("gdbus", "dbus-monitor", "xdg-open")):
        return False
    environment = dict(os.environ)
    root = str(Path(__file__).resolve().parents[1])
    carried = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = f"{root}{os.pathsep}{carried}" if carried else root
    try:
        subprocess.Popen(
            [
                sys.executable, "-m", "ticket_runner.notify",
                link, title, body, "urgent" if urgent else "normal",
            ],
            env=environment,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# -- the child ----------------------------------------------------------------


def follow(link: str, title: str, body: str, *, urgent: bool) -> None:
    """Post the notification, then open `link` if somebody clicks it.

    The watcher is started before the notification, because the identifier is
    only known once the notification is posted and a signal missed is a click
    lost. Anything that goes wrong on the way falls back to the plain
    notification: being told late is the point, being told never is not.
    """
    watcher = _watch()
    identifier = _post(title, body, urgent=urgent) if watcher else ""
    if not identifier:
        if watcher:
            watcher.terminate()
        _plain(title, body, urgent=urgent)
        return
    # A daemon timer, so that the click that comes first ends the child rather
    # than leaving it to sit out the hour it was given.
    deadline = threading.Timer(LIFETIME, watcher.terminate)
    deadline.daemon = True
    deadline.start()
    try:
        if _clicked(watcher, identifier):
            subprocess.Popen(
                ["xdg-open", link],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        deadline.cancel()
        watcher.terminate()


def _watch() -> subprocess.Popen | None:
    """`dbus-monitor` on the notification signals, reading as they arrive."""
    try:
        return subprocess.Popen(
            ["dbus-monitor", "--session", f"type='signal',interface='{BUS}'"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _post(title: str, body: str, *, urgent: bool) -> str:
    """Show the notification, and return the identifier the desktop gave it.

    `--` before the arguments because the expiry is `-1`, "for as long as the
    desktop likes", and `gdbus` would otherwise read it as an option of its own.
    """
    try:
        answer = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", BUS,
                "--object-path", OBJECT,
                "--method", f"{BUS}.Notify",
                "--",
                _text(APP), "0", _text(_icon(urgent)), _text(title), _text(body),
                ACTIONS, f"{{'urgency': <byte {2 if urgent else 1}>}}", "-1",
            ],
            check=False,
            timeout=10,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    found = re.search(r"uint32 (\d+)", answer.stdout)
    return found.group(1) if found else ""


def _text(value: str) -> str:
    """A title or a body, spelled as the string literal `gdbus` expects.

    Every argument is read as GVariant, so a body of “42” would arrive as a
    number and the whole call would be refused — and the notification with it.
    """
    for character, escape in (("\\", "\\\\"), ('"', '\\"'), ("\n", "\\n"), ("\t", "\\t")):
        value = value.replace(character, escape)
    return f'"{value}"'


def _clicked(watcher: subprocess.Popen, identifier: str) -> bool:
    """Whether that notification was clicked, rather than merely dismissed.

    `dbus-monitor` writes a signal over several lines — its name on the first,
    its arguments underneath — so the name is held until an identifier turns up
    under it. Identifiers are handed out by the desktop and never shared, so one
    that matches is ours and no other application's.
    """
    signal = ""
    for line in watcher.stdout:
        if "member=" in line:
            signal = line.rsplit("member=", 1)[-1].strip()
        elif line.strip() == f"uint32 {identifier}":
            if signal == "ActionInvoked":
                return True
            if signal == "NotificationClosed":
                return False
    return False


if __name__ == "__main__":  # the detached child, started by `send`
    follow(sys.argv[1], sys.argv[2], sys.argv[3], urgent=sys.argv[4] == "urgent")
