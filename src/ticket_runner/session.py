"""Running a Claude Code session on a ticket, and knowing what it did.

The session runs in `--print` mode with `stream-json` output: the raw stream is
written to a log as-is, which lets you follow a ticket live
(`ticket-runner logs -f`) and read back afterwards why it failed.

The session ID is **drawn before** launching and passed as `--session-id`. So we
know it even if the session dies halfway, and `claude --resume <id>` reopens the
conversation exactly where it stopped — which is what makes a failure something
to repair by hand rather than something to redo.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse


@dataclass
class Outcome:
    ok: bool
    blocked: bool
    session_id: str
    summary: str
    log: Path
    answer: str = ""
    error: str = ""
    cost_usd: float = 0.0
    turns: int = 0
    seconds: float = 0.0

    @property
    def resume_command(self) -> str:
        return f"claude --resume {self.session_id}"


def available() -> str:
    return shutil.which("claude") or ""


def new_id() -> str:
    """A session identifier, drawn before the session exists.

    The runner draws it at claim time so the Notion ticket can point at the work
    from the moment it starts, not only once it is finished.
    """
    return str(uuid.uuid4())


def run(
    prompt: str,
    *,
    cwd: Path,
    log: Path,
    model: str = "",
    permission_mode: str = "bypassPermissions",
    timeout_minutes: int = 30,
    session_id: str = "",
) -> Outcome:
    binary = available()
    if not binary:
        raise FileNotFoundError("claude not found in PATH")

    session_id = session_id or new_id()
    command = [
        binary,
        "--print",
        "--session-id", session_id,
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", permission_mode,
    ]
    if model:
        command += ["--model", model]
    command.append(prompt)

    environment = {**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    started = time.monotonic()
    log.parent.mkdir(parents=True, exist_ok=True)
    stderr_path = log.with_suffix(".err")

    with log.open("w", encoding="utf-8") as journal, stderr_path.open("w") as errors:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            bufsize=1,
            env=environment,
            start_new_session=True,  # its own process group, so we can kill it all
        )

        timed_out = threading.Event()

        def stop() -> None:
            timed_out.set()
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                time.sleep(5)
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        watchdog = threading.Timer(timeout_minutes * 60, stop)
        watchdog.start()

        final: dict = {}
        texts: list[str] = []
        try:
            for line in process.stdout:  # type: ignore[union-attr]
                journal.write(line)
                journal.flush()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "result":
                    final = event
                elif event.get("type") == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            texts.append(block.get("text", ""))
            process.wait()
        finally:
            watchdog.cancel()

    seconds = time.monotonic() - started
    if timed_out.is_set():
        return Outcome(
            ok=False,
            blocked=False,
            session_id=session_id,
            summary="",
            log=log,
            answer="",
            error=f"session killed after {timeout_minutes} min",
            seconds=seconds,
        )

    answer = str(final.get("result") or "\n".join(texts)).strip()
    failed = bool(final.get("is_error")) or process.returncode != 0
    blocked = _verdict(answer) == "blocked"
    error = ""
    if failed:
        error = answer[-800:] or _tail(stderr_path) or f"claude exited with code {process.returncode}"

    return Outcome(
        ok=not failed and not blocked,
        blocked=blocked,
        session_id=str(final.get("session_id") or session_id),
        summary=_summary(answer),
        log=log,
        answer=answer,
        error=error,
        cost_usd=float(final.get("total_cost_usd") or 0.0),
        turns=int(final.get("num_turns") or 0),
        seconds=seconds,
    )


PROJECTS = Path.home() / ".claude" / "projects"


def project_key(path: Path) -> str:
    """The folder Claude Code files a session under, for a given directory.

    It slugifies the working directory: every `/` and `.` becomes `-`. So
    /home/me/work/app is `-home-me-work-app`, and a session started inside a
    disposable worktree is filed under the worktree, not the repository — which
    is why `/resume` in the repository never shows it.
    """
    return re.sub(r"[/.]", "-", str(path))


def relocate(session_id: str, destination: Path) -> Path | None:
    """Move a finished session's transcript under `destination`'s project folder.

    A ticket runs in a worktree that is deleted afterwards, so its session ends
    up filed under a directory that no longer exists — resumable by ID, but
    invisible in the repository's session picker. Moving the transcript puts it
    where you would look for it: `claude --resume` inside the repository lists
    it beside your own sessions.

    This reaches into Claude Code's own storage, so it is written to fail
    quietly: the transcript is located by globbing rather than by guessing where
    it was, and anything unexpected leaves the session exactly where it is,
    still resumable by its identifier.
    """
    try:
        matches = list(PROJECTS.glob(f"*/{session_id}.jsonl"))
        if not matches:
            return None
        source = matches[0]
        target_dir = PROJECTS / project_key(destination)
        if source.parent == target_dir:
            return source
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        shutil.move(str(source), str(target))
        try:
            source.parent.rmdir()  # only if the ticket left nothing else behind
        except OSError:
            pass
        return target
    except (OSError, ValueError):
        return None


SCHEME = "ticket-runner"
TERMINALS = (
    ("gnome-terminal", lambda cwd, args: ["gnome-terminal", f"--working-directory={cwd}", "--", *args]),
    ("konsole", lambda cwd, args: ["konsole", "--workdir", str(cwd), "-e", *args]),
    ("xfce4-terminal", lambda cwd, args: ["xfce4-terminal", f"--working-directory={cwd}", "-e", " ".join(args)]),
    ("kitty", lambda cwd, args: ["kitty", "--directory", str(cwd), *args]),
    ("alacritty", lambda cwd, args: ["alacritty", "--working-directory", str(cwd), "-e", *args]),
    ("foot", lambda cwd, args: ["foot", "--working-directory", str(cwd), *args]),
    ("x-terminal-emulator", lambda cwd, args: ["x-terminal-emulator", "-e", *args]),
)


def deep_link(session_id: str, cwd: Path | str | None = None, host: str = "") -> str:
    """A clickable link that reopens this session, wherever it ran.

    Notion accepts any scheme in a URL property, and `install.sh` registers
    `ticket-runner://` with the desktop. Clicking the Session cell of a ticket
    therefore opens a terminal already inside the conversation — which beats
    copying a UUID into a command by some distance.

    When the runner is on a server, the session's transcript is on that server
    too, and a link that opened a local terminal would find nothing. `host` puts
    the ssh destination in the link, so the click opens the session **over ssh**
    from whichever machine you clicked on. That is what keeps the Session column
    useful once the runner moves off your laptop.

    Claude Code registers a `claude-cli://` scheme of its own, but its query
    parameters are undocumented and a wrong guess would produce a link that
    silently does nothing; ours does exactly what this file says it does.
    """
    query = []
    if cwd:
        query.append(f"cwd={quote(str(cwd), safe='/')}")
    if host:
        query.append(f"host={quote(host, safe='@.:-')}")
    link = f"{SCHEME}://session/{session_id}"
    return f"{link}?{'&'.join(query)}" if query else link


def open_link(uri: str) -> int:
    """Handle a ticket-runner:// URI by opening a terminal on that session."""
    parsed = urlparse(uri)
    if parsed.scheme != SCHEME:
        raise ValueError(f"not a {SCHEME}:// link: {uri}")
    action = parsed.netloc or parsed.path.lstrip("/").split("/")[0]
    if action != "session":
        raise ValueError(f"unknown action “{action}” — expected {SCHEME}://session/<id>")
    session_id = parsed.path.strip("/").split("/")[-1]
    if not session_id:
        raise ValueError("no session identifier in the link")
    query = parse_qs(parsed.query)
    cwd = (query.get("cwd") or [str(Path.home())])[0]
    host = (query.get("host") or [""])[0]

    if host:
        # The session lives on another machine, so resuming means going there.
        # No local claude is needed — only ssh, and an account that has one.
        if not shutil.which("ssh"):
            raise FileNotFoundError(f"ssh not found — cannot reach {host}")
        remote = f"cd {shlex.quote(cwd)} 2>/dev/null; claude --resume {shlex.quote(session_id)}"
        command = ["ssh", "-t", host, remote]
        cwd = str(Path.home())
    else:
        if not Path(cwd).is_dir():
            cwd = str(Path.home())
        binary = available()
        if not binary:
            raise FileNotFoundError("claude not found in PATH")
        command = [binary, "--resume", session_id]

    preferred = os.environ.get("TICKET_RUNNER_TERMINAL", "")
    candidates = list(TERMINALS)
    if preferred:
        candidates.insert(0, (preferred, lambda cwd, args, p=preferred: [p, "-e", *args]))
    for name, build in candidates:
        if shutil.which(name):
            # Detached: the click must not keep the desktop handler alive.
            subprocess.Popen(build(cwd, command), start_new_session=True)
            return 0
    raise FileNotFoundError(
        "no terminal emulator found — set TICKET_RUNNER_TERMINAL to the one you use"
    )


def _verdict(answer: str) -> str:
    for line in reversed(answer.splitlines()):
        stripped = line.strip().lstrip("*# ").rstrip("*")
        if stripped.upper().startswith("RESULT:"):
            value = stripped[len("RESULT:") :].strip().lower()
            if value.startswith("blocked"):
                return "blocked"
            if value.startswith("ok"):
                return "ok"
    return ""


def _summary(answer: str) -> str:
    """The RESULT line without its verdict, else the tail of the answer.

    "RESULT: ok — removed the header" becomes "removed the header": the verdict
    is already carried by the Notion status, repeating it teaches nothing.
    """
    for line in reversed(answer.splitlines()):
        stripped = line.strip().lstrip("*# ").rstrip("*")
        if stripped.upper().startswith("RESULT:"):
            rest = stripped[len("RESULT:") :].strip()
            for verdict in ("blocked", "ok"):
                if rest.lower().startswith(verdict):
                    rest = rest[len(verdict) :]
                    break
            return rest.strip(" —-:") or stripped
    return answer[-500:].strip()


def _tail(path: Path, limit: int = 500) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
    except OSError:
        return ""
