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
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Outcome:
    ok: bool
    blocked: bool
    session_id: str
    summary: str
    log: Path
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
        error=error,
        cost_usd=float(final.get("total_cost_usd") or 0.0),
        turns=int(final.get("num_turns") or 0),
        seconds=seconds,
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
