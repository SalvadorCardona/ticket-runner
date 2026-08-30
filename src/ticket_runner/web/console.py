"""The two things you can type into the console: a command, or a sentence.

They are not the same gesture and they are not made to look the same.

- A line starting with `>` is a **`ticket-runner` subcommand**. The CLI is
  already the safe, considered surface of this tool; the console does not invent
  a second one. It is run as a subprocess with no shell — there is nothing to
  quote wrong, and nothing to inject into.
- Anything else is a **message to the workspace**: one long Claude Code session,
  started in `workspace_root`, that carries on from turn to turn. It has the
  `ticket-runner` command in its PATH and your repositories under its feet, so
  "create a ticket for X on Trader Ia and make it ready" is a thing it does
  rather than a thing it explains how to do.

The conversation survives the browser, the server and the machine: it is a real
Claude Code session, resumed by its identifier, and `claude --resume <id>` in a
terminal opens the very same one.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .. import progress, session
from ..config import Config, state_dir

# Commands the console will not run, and why. Neither is dangerous — both are
# useless from a browser, and both would hang the request forever waiting for
# something that is happening on the server's own screen.
REFUSED = {
    "config": "opens an editor on the server — use the file, or ask the chat to edit it",
    "open": "opens a terminal on the server's desktop, which is not where you are",
    "serve": "is what you are already talking to",
}

# A command is not a session: nothing in the CLI legitimately takes minutes.
COMMAND_TIMEOUT = 180


def web_dir() -> Path:
    path = state_dir() / "web"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Message:
    role: str
    text: str
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def as_dict(self) -> dict:
        return {"role": self.role, "text": self.text, "at": self.at}


class Chat:
    """One conversation with the whole workspace, kept across restarts."""

    def __init__(
        self,
        config: Config,
        publish: Callable[..., None],
        brief: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.publish = publish
        self.brief = brief or (lambda: "")
        self.path = web_dir() / "chat.json"
        self._lock = threading.Lock()
        self._busy = False
        self.session_id = ""
        self.turns = 0
        self.messages: list[Message] = []
        self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self.session_id = str(raw.get("session_id") or "")
        self.turns = int(raw.get("turns") or 0)
        self.messages = [
            Message(str(item.get("role", "")), str(item.get("text", "")), str(item.get("at", "")))
            for item in raw.get("messages", [])
            if item.get("role") and item.get("text")
        ]

    def _save(self) -> None:
        payload = {
            "session_id": self.session_id,
            "turns": self.turns,
            # The transcript on disk is the console's scrollback, not the
            # session's memory: Claude Code keeps that itself. A hundred turns
            # is more than anybody scrolls back through.
            "messages": [message.as_dict() for message in self.messages[-200:]],
        }
        try:
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.path.chmod(0o600)
        except OSError:
            pass

    # -- state ---------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._busy

    def state(self) -> dict:
        return {
            "session_id": self.session_id,
            "turns": self.turns,
            "busy": self._busy,
            "resume_command": f"claude --resume {self.session_id}" if self.session_id else "",
        }

    def history(self) -> list[dict]:
        return [message.as_dict() for message in self.messages]

    def reset(self) -> dict:
        """Start a new conversation. The old one stays resumable by its ID."""
        with self._lock:
            if self._busy:
                raise RuntimeError("a turn is in flight — let it finish first")
            self.session_id = ""
            self.turns = 0
            self.messages = []
            self._save()
        self.publish("chat", stage="reset")
        return self.state()

    # -- one turn ------------------------------------------------------------

    def send(self, text: str) -> dict:
        text = text.strip()
        if not text:
            raise ValueError("nothing to send")
        if not session.available():
            raise FileNotFoundError("claude not found in PATH")
        with self._lock:
            if self._busy:
                raise RuntimeError("the workspace is still answering the previous message")
            self._busy = True
            first = not self.session_id
            if first:
                self.session_id = session.new_id()
            self.messages.append(Message("you", text))
            self._save()
        self.publish("chat", stage="sent", text=text, session_id=self.session_id)
        thread = threading.Thread(
            target=self._turn, args=(text, first), name="tr-chat", daemon=True
        )
        thread.start()
        return self.state()

    def _turn(self, text: str, first: bool) -> None:
        started = time.monotonic()
        log = web_dir() / f"chat-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        prompt = f"{self.brief()}\n\n{text}" if first else text
        try:
            outcome = session.run(
                prompt,
                cwd=self._cwd(),
                log=log,
                model=self.config.runner.model,
                permission_mode=self.config.runner.permission_mode,
                timeout_minutes=self.config.web.chat_timeout_minutes,
                session_id=self.session_id,
                resume=not first,
                on_event=self._on_event,
            )
        except Exception as error:  # noqa: BLE001
            with self._lock:
                self._busy = False
                self.messages.append(Message("error", str(error)))
                self._save()
            self.publish("chat", stage="failed", text=str(error))
            return

        answer = outcome.answer or outcome.error or "(no answer)"
        with self._lock:
            self._busy = False
            self.turns += 1
            self.messages.append(Message("workspace" if outcome.ok else "error", answer))
            self._save()
        self.publish(
            "chat",
            stage="answer",
            text=answer,
            ok=outcome.ok,
            cost_usd=round(outcome.cost_usd, 4),
            seconds=round(time.monotonic() - started, 1),
            session_id=self.session_id,
        )

    def _on_event(self, event: dict) -> None:
        for step in progress.describe(event):
            self.publish("chat", stage="step", label=step.label, detail=step.detail)

    def _cwd(self) -> Path:
        root = self.config.runner.workspace_root
        if root.is_dir():
            return root
        # A workspace_root that does not exist would fail the session before it
        # said a word. Home is a poor workspace and a fine fallback.
        return Path.home()


class Commands:
    """`ticket-runner <verb>`, run for the browser and streamed back."""

    def __init__(self, publish: Callable[..., None], allowed: tuple[str, ...]) -> None:
        self.publish = publish
        # What the CLI offers, less what makes no sense from a browser. Offering
        # a verb in the error message and then refusing it would be a small lie
        # told to somebody who is already lost.
        self.allowed = tuple(verb for verb in allowed if verb not in REFUSED)
        self._lock = threading.Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def parse(self, line: str) -> list[str]:
        """The argument list a typed command means, or an explanation of why not.

        `shlex` and no shell: the words that come out of here are handed to
        `execve` as they are, so a quote in a ticket title is a quote in a ticket
        title, and there is no interpreter left for a `;` to speak to.
        """
        try:
            argv = shlex.split(line.strip())
        except ValueError as error:
            raise ValueError(f"unbalanced quotes: {error}") from error
        if not argv:
            raise ValueError("no command")
        verb = argv[0].lstrip(">").strip()
        if not verb:
            raise ValueError("no command")
        argv[0] = verb
        if verb in REFUSED:
            raise ValueError(f"{verb} {REFUSED[verb]}")
        if verb not in self.allowed:
            offered = ", ".join(sorted(self.allowed))
            raise ValueError(f"unknown command “{verb}” — try one of: {offered}")
        # `logs -f` never returns, and the live panel already is that feed.
        if verb == "logs":
            return [word for word in argv if word not in ("-f", "--follow")]
        return argv

    def start(self, line: str) -> dict:
        argv = self.parse(line)
        with self._lock:
            if self._busy:
                raise RuntimeError("a command is already running")
            self._busy = True
        self.publish("command", stage="started", argv=argv)
        threading.Thread(
            target=self._run, args=(argv,), name="tr-command", daemon=True
        ).start()
        return {"argv": argv}

    def _run(self, argv: list[str]) -> None:
        command = [sys.executable, "-m", "ticket_runner", *argv]
        source = str(Path(__file__).resolve().parents[2])
        environment = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([source, os.environ.get("PYTHONPATH", "")]).rstrip(
                os.pathsep
            ),
            "PYTHONUNBUFFERED": "1",
            # No colour: the console renders the text, and escape codes would
            # reach it as mojibake. The CLI already drops them off a tty, but
            # `logs` writes its header to stderr either way.
            "NO_COLOR": "1",
        }
        code = -1
        try:
            process = subprocess.Popen(
                command,
                cwd=str(Path.home()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=environment,
                start_new_session=True,
            )
        except OSError as error:
            self.publish("command", stage="line", text=f"could not start: {error}")
            with self._lock:
                self._busy = False
            self.publish("command", stage="ended", code=code)
            return

        watchdog = threading.Timer(COMMAND_TIMEOUT, process.kill)
        watchdog.start()
        try:
            for line in process.stdout:  # type: ignore[union-attr]
                self.publish("command", stage="line", text=line.rstrip("\n"))
            code = process.wait()
        finally:
            watchdog.cancel()
            with self._lock:
                self._busy = False
        self.publish("command", stage="ended", code=code)
