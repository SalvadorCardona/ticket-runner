"""What the console can ask for, and what it is allowed to change.

The board stays Notion's. Nothing here is a second database: a ticket read is a
ticket read from Notion, a ticket moved is a `PATCH` on the same page you would
have dragged with your thumb. The console adds what Notion cannot do — the live
steps of a running session, the CLI, and a conversation about the whole
workspace — and duplicates nothing it already does well.

Three reads are cached, because a page left open in a tab must not turn into a
full-time reader of your workspace: the configuration (reloaded when its file
changes), the project index, and the tickets database ID.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .. import config as config_module
from .. import notion, session, state
from .. import update as update_module
from ..config import Config
from ..runner import Runner, scheduled_for, short_id
from . import console, live
from . import settings as settings_module

# The project index is read from one database query, not one page fetch per
# project — and kept, because projects are renamed about as often as they are
# created. Ten minutes is short enough that a new project appears on its own.
PROJECT_TTL = 600

# And the board's own shape on the same cadence, for the same reason: the Notion
# client caches a database for its lifetime, which for the console is days. A
# column added in Notion — the validated one, most of all — has to appear
# without anyone restarting anything.
SCHEMA_TTL = 600

# The columns, in the order they are meant to be read. Anything the board
# carries that is none of them lands in "other" rather than being hidden.
COLUMNS = ("ready", "running", "review", "validated", "blocked", "failed", "done")


class Api:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._stamp = _mtime(config.path)
        self._runner: Runner | None = None
        self._projects: dict[str, dict] = {}
        self._projects_at = 0.0
        self._schema_at = 0.0
        self.hub = live.Hub()
        self.commands = console.Commands(self.hub.publish, _subcommands())
        self.chat = console.Chat(config, self.hub.publish, self.brief)
        self.watch = live.Watch(self.hub, self.board, interval=config.web.poll_seconds)

    # -- the pieces underneath ------------------------------------------------

    @property
    def config(self) -> Config:
        """The configuration, reread when the file on disk has changed.

        `ticket-runner config` edits the same file the console is running on,
        and a console that had to be restarted to notice would be a console
        people restart all day.
        """
        stamp = _mtime(self._config.path)
        if stamp != self._stamp:
            try:
                fresh = config_module.load(self._config.path)
            except config_module.ConfigError:
                return self._config  # a half-saved file: keep what works
            self._stamp = stamp
            self._config = fresh
            self._runner = None
            self._projects = {}
            self.chat.config = fresh
        return self._config

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            self._runner = Runner(self.config, quiet=True)
        return self._runner

    def forget(self) -> None:
        """Drop the caches. What a failed Notion call earns, so the next retries."""
        self._runner = None
        self._projects = {}
        self._projects_at = 0.0
        self._schema_at = 0.0

    # -- reading --------------------------------------------------------------

    def board(self) -> dict:
        """Every ticket, grouped the way the board groups them."""
        settings = self.config.notion
        try:
            if time.time() - self._schema_at > SCHEMA_TTL:
                self.runner.client.forget_database(self.runner.database)
                self._schema_at = time.time()
            pages = self.runner.client.query(self.runner.database)
        except notion.NotionError:
            self.forget()
            raise
        names = {settings.state(key): key for key in COLUMNS}
        projects = self.projects()
        host = self.config.runner.session_host

        tickets = []
        for page in pages:
            status = str(notion.read(page, settings.prop("status")) or "")
            relation = notion.read(page, settings.prop("project")) or []
            project = projects.get(relation[0]) if relation else None
            session_id = str(notion.read(page, settings.prop("session")) or "")
            moment = scheduled_for(notion.read(page, settings.prop("due")))
            tickets.append(
                {
                    "id": page.id.replace("-", ""),
                    "short": short_id(page.id),
                    "title": page.title or "(untitled ticket)",
                    "url": page.url,
                    "status": status,
                    "column": names.get(status, "other"),
                    "project": (project or {}).get("name", ""),
                    "kind": (project or {}).get("kind", ""),
                    "priority": str(notion.read(page, settings.prop("priority")) or ""),
                    "model": str(notion.read(page, settings.prop("model")) or ""),
                    "progress": str(notion.read(page, settings.prop("progress")) or ""),
                    "runner": str(notion.read(page, settings.prop("agent")) or ""),
                    "pull_request": str(notion.read(page, settings.prop("pull_request")) or ""),
                    "session": _session_id(session_id),
                    "session_link": session.deep_link(_session_id(session_id), host=host)
                    if _session_id(session_id)
                    else "",
                    "cost": notion.read(page, settings.prop("cost")),
                    "duration": notion.read(page, settings.prop("duration")),
                    "scheduled": moment.isoformat(timespec="minutes") if moment else "",
                    "created": page.raw.get("created_time", ""),
                }
            )

        # Whether this board has a validated column at all. The console offers
        # the gesture only where the runner would honour it: a button that
        # writes a status Notion does not know is a button that fails.
        validated = settings.state("validated")
        try:
            offers = validated not in (
                settings.state("review"),
                settings.state("done"),
            ) and validated in self.runner.client.options(
                self.runner.database, settings.prop("status")
            )
        except notion.NotionError:
            offers = False

        order = {key: index for index, key in enumerate(COLUMNS)}
        tickets.sort(key=lambda item: (order.get(item["column"], len(COLUMNS)), item["title"].lower()))
        return {
            "tickets": tickets,
            "validate": offers,
            "columns": [
                {"key": key, "name": settings.state(key)}
                for key in COLUMNS
                # A board whose `blocked` and `failed` are one column must not
                # be drawn twice under two headings.
                if settings.state(key) not in [settings.state(other) for other in COLUMNS[: COLUMNS.index(key)]]
            ],
        }

    def projects(self) -> dict[str, dict]:
        """{page id: {name, kind}} — one query, kept for a few minutes.

        Read from the projects database in one go rather than resolved ticket by
        ticket: resolving costs two API calls per project, and the board asks
        this question every time it refreshes.
        """
        if self._projects and time.time() - self._projects_at < PROJECT_TTL:
            return self._projects
        index: dict[str, dict] = {}
        try:
            database = self.runner.workspace.projects
            if database:
                for page in self.runner.client.query(database):
                    declared = any(
                        notion.read(page, name)
                        for name in ("Repository", "repository", "github", "Path", "path")
                    )
                    index[page.id] = {
                        "id": page.id.replace("-", ""),
                        "name": page.title or "(untitled project)",
                        "kind": "code" if declared else "document",
                        "url": page.url,
                    }
        except notion.NotionError:
            # A projects database that cannot be read costs the board its
            # project names, and nothing else. The tickets still show.
            return self._projects
        self._projects = index
        self._projects_at = time.time()
        return index

    def state(self) -> dict:
        """Everything the header shows: the timer, the lock, the version, the spend."""
        configuration = self.config
        lock = config_module.state_dir() / "run.lock"
        entries = state.history(10_000)
        return {
            "timer": _timer_state(),
            "running": lock.exists(),
            "lock": lock.read_text(encoding="utf-8").strip() if lock.exists() else "",
            "workspace_root": str(configuration.runner.workspace_root),
            "interval_seconds": configuration.runner.interval_seconds,
            "model": configuration.runner.model or "default",
            "permission_mode": configuration.runner.permission_mode,
            "claude": bool(session.available()),
            "version": _version(),
            "update": _update_available(),
            "spend": round(sum(float(entry.get("cost_usd") or 0) for entry in entries), 2),
            "handled": len(entries),
            "chat": self.chat.state(),
            "commands": sorted(self.commands.allowed),
            "busy": self.commands.busy,
        }

    def history(self, limit: int = 30) -> dict:
        return {"entries": list(reversed(state.history(limit)))}

    def logs(self) -> dict:
        paths = sorted(state.logs_dir().glob("*.jsonl"), reverse=True)[:40]
        return {
            "logs": [
                {
                    "name": path.name,
                    "ticket": path.name.removesuffix(".jsonl").rsplit("-", 1)[-1],
                    "at": path.stat().st_mtime,
                    "size": path.stat().st_size,
                }
                for path in paths
                if path.exists()
            ]
        }

    def log(self, name: str) -> dict:
        """One session, as the steps it was made of. Never as a path from outside."""
        target = state.logs_dir() / Path(name).name
        if not target.exists() or target.suffix != ".jsonl":
            raise LookupError(f"no such log: {name}")
        steps = []
        with target.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                for step in live.steps(line):
                    steps.append({"label": step.label, "detail": step.detail})
        return {"name": target.name, "steps": steps[-1000:]}

    # -- writing --------------------------------------------------------------

    def create_ticket(self, title: str, body: str = "", project: str = "", ready: bool = True) -> dict:
        title = title.strip()
        if not title:
            raise ValueError("a ticket needs a title")
        settings = self.config.notion
        values: dict[str, Any] = {}
        # Ready means "start it now"; anything else means the ticket is being
        # written. A draft is left with no status rather than parked in a column
        # nobody named: the runner claims what it was told to claim, and a
        # console that invented a sixth column would be inventing a workflow.
        if ready:
            values[settings.prop("status")] = settings.state("ready")
        if project:
            values[settings.prop("project")] = [project]
        page_id = self.runner.client.create_row(self.runner.database, title, values)
        if body.strip():
            self.runner.client.append_markdown(page_id, body)
        self.watch.nudge()
        return {"id": page_id, "title": title}

    def set_status(self, page_id: str, key: str) -> dict:
        if key not in COLUMNS:
            raise ValueError(f"unknown column “{key}”")
        settings = self.config.notion
        self.runner.client.update(
            self.runner.database, page_id, {settings.prop("status"): settings.state(key)}
        )
        self.watch.nudge()
        return {"id": page_id, "status": settings.state(key)}

    # -- the configuration ----------------------------------------------------

    def settings(self) -> dict:
        """Every setting the file holds, as the console draws it — secrets aside."""
        return settings_module.describe(self.config)

    def save_settings(self, payload: dict) -> dict:
        """Write what the console changed, and pick the new file up at once.

        The caches go first because a saved token, workspace or property name is
        a different board: keeping the old client would have the console explain
        that the setting did not work.
        """
        result = settings_module.save(self.config, payload)
        if result["saved"]:
            self.forget()
            self.hub.publish("settings", saved=result["saved"])
            self.watch.nudge()
        return result

    # -- the chat's opening frame ---------------------------------------------

    def brief(self) -> str:
        """What the workspace conversation is told before your first sentence.

        Written once per conversation, not once per message: it costs two Notion
        reads, and repeating it every turn would spend them for a session that
        already remembers. What it carries is the frame — who you are, what the
        projects are, where they live — and one instruction that matters more
        than the rest: the board is changed through `ticket-runner`, not by
        guessing at the Notion API.
        """
        configuration = self.config
        lines = [
            "You are the assistant of a ticket-runner workspace, reached from its web console.",
            "Somebody is in front of you: answer them, ask when something is ambiguous.",
            "",
            "# Your workspace",
            "",
            f"- Repositories live under `{configuration.runner.workspace_root}`.",
            "- `ticket-runner` is on your PATH. `ticket-runner list`, `status`, `history`,",
            "  `projects`, `logs <id>` and `doctor` are how you look at the board;",
            "  `run` handles the ready tickets now.",
            "- The Notion board is the source of truth for tickets. Read it through the",
            "  `ticket-runner` command rather than through the Notion API directly.",
            "- You are not inside a ticket: nothing here has a worktree, a branch or a",
            "  pull request waiting. Work that deserves those is work that deserves a",
            "  ticket — say so, and offer to create one.",
        ]
        try:
            context = self.runner.workspace.context.strip()
        except notion.NotionError:
            context = ""
        projects = self.projects()
        if projects:
            lines += ["", "# Projects", ""]
            for project in sorted(projects.values(), key=lambda item: item["name"].lower()):
                lines.append(f"- **{project['name']}** — {project['kind']} work")
        if context:
            lines += ["", "# Who you are working for", "", context[:6000]]
        return "\n".join(lines)


def _session_id(value: str) -> str:
    """The identifier inside a Session cell, whichever shape the column has.

    A URL column holds `ticket-runner://session/<id>?cwd=…`, a text column holds
    the bare ID. Both are the same session, and the console shows the same link.
    """
    value = value.strip()
    if not value:
        return ""
    if "://" in value:
        return value.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    return value


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _version() -> str:
    """The number this console is running — nothing else.

    Kept bare so the header can print it where a version belongs, next to the
    name, rather than as one more sentence in a row of pills. What is *newer*
    than it is `_update_available`, which is a different question.
    """
    from .. import __version__

    return __version__


def _update_available() -> str:
    """The commit waiting to be installed, or an empty string for "none".

    Read from the stamp a run already writes — never by asking the remote: the
    console redraws its header on every reconnection, and a `git fetch` behind
    that would be a fetch every time a laptop wakes up.
    """
    status = update_module.remembered()
    return status.latest[:8] if status.stale else ""


def _timer_state() -> str:
    if not shutil.which("systemctl"):
        return "no systemd"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", "ticket-runner.timer"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "not installed"


def _subcommands() -> tuple[str, ...]:
    from ..__main__ import subcommands

    return subcommands()
