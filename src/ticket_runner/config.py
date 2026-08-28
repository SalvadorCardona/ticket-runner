"""Reading and validating ~/.config/ticket-runner/config.toml.

The file is the single source of truth: nothing is inferred from the
environment, and a missing value is reported at install time rather than in the
middle of a ticket.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PLACEHOLDER = "ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "ticket-runner"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "ticket-runner"


def config_path() -> Path:
    override = os.environ.get("TICKET_RUNNER_CONFIG")
    return Path(override) if override else config_dir() / "config.toml"


class ConfigError(Exception):
    """Configuration missing, unreadable or incomplete."""


@dataclass
class Notion:
    token: str = ""
    workspace: str = ""
    tickets_database: str = ""
    pages: dict[str, str] = field(default_factory=dict)
    properties: dict[str, str] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)

    def prop(self, key: str) -> str:
        return self.properties.get(key, _DEFAULT_PROPERTIES[key])

    def page(self, key: str) -> str:
        """The title of the workspace row holding that database or page."""
        return self.pages.get(key, _DEFAULT_PAGES[key])

    def page_aliases(self, key: str) -> tuple[str, ...]:
        """Every title that row may carry: the configured one, then the old ones.

        Only when the configuration does not name it: someone who wrote the
        title down meant that title, and guessing past it would find the wrong
        row on a board that has both.
        """
        if key in self.pages:
            return (self.pages[key],)
        return (_DEFAULT_PAGES[key], *_LEGACY_PAGES.get(key, ()))

    def state(self, key: str) -> str:
        # "blocked" is optional, and only *against a named `failed`*: a file that
        # says where failures go but not where questions go meant one column for
        # both. A file that names neither gets the defaults, which are two —
        # telling "the agent asked you something" from "something broke" is the
        # whole reason the runner distinguishes them.
        if key == "blocked" and "blocked" not in self.status and "failed" in self.status:
            return self.state("failed")
        # "review" reads the same way, against a named `done`: a file that says
        # where a finished ticket goes but not where it waits for its pull
        # request has one column for both, and nothing to watch for a merge. A
        # file that names neither gets the defaults, which are two — the pull
        # request being open and it being merged are not the same day.
        if key == "review" and "review" not in self.status and "done" in self.status:
            return self.state("done")
        return self.status.get(key, _DEFAULT_STATUS[key])


@dataclass
class Runner:
    workspace_root: Path = Path.home() / "workspace"
    interval_seconds: int = 1800
    max_concurrent: int = 2
    timeout_minutes: int = 30
    model: str = ""
    permission_mode: str = "bypassPermissions"
    branch_prefix: str = "ticket/"
    base_branch: str = ""
    fetch: bool = True
    push: bool = True
    open_pull_request: bool = True
    keep_worktree_on_failure: bool = True
    attach_sessions: bool = True
    session_host: str = ""
    notify: bool = True
    auto_update: bool = True
    update_interval_seconds: int = 3600
    log_retention_days: int = 14
    dry_run: bool = False
    prompt_file: str = ""
    document_prompt_file: str = ""


@dataclass
class Config:
    notion: Notion
    runner: Runner
    projects: dict[str, str]
    path: Path

    def require_usable(self) -> None:
        """Raise ConfigError if the file is not complete enough to run."""
        missing = []
        if not self.notion.token or self.notion.token == PLACEHOLDER:
            missing.append("notion.token")
        # Either way of naming the tickets database will do: the workspace page
        # that holds it, or the database itself.
        if not self.notion.workspace and not self.notion.tickets_database:
            missing.append("notion.workspace (or notion.tickets_database)")
        if missing:
            raise ConfigError(
                f"{', '.join(missing)} must be set in {self.path}\n"
                "  ticket-runner init <page-url>   builds the databases and fills this in\n"
                "  ticket-runner config            opens the file in your editor"
            )


_DEFAULT_PROPERTIES = {
    "status": "Status",
    "project": "Project",
    # Which machine took the ticket, as ticket-runner@host. Not to be confused
    # with `role` below: this one is a runner, that one is a craft.
    "agent": "Runner",
    "pull_request": "Pull Request",
    "session": "Session",
    # Optional. A database without them behaves exactly as before: the runner
    # skips a property the schema does not declare.
    "model": "Model",          # per-ticket model, overrides runner.model
    "priority": "Priority",    # which ready ticket goes first
    "cost": "Cost",            # written back, in dollars
    "duration": "Duration",    # written back, in minutes
    # A date here holds the ticket until that moment. It is a start gate, not a
    # deadline — "Due Date" said the opposite of what the runner does with it.
    "due": "Scheduled",
    # Relation to the Agents database. It carries the same word as the database
    # it points at, because it is the same thing.
    "role": "Agent",
}

# The rows the runner looks for in the workspace database, by their title.
# Only `tickets` is required; the others change nothing by their absence.
_DEFAULT_PAGES = {
    "tickets": "Tickets",
    "projects": "Projects",
    "agents": "Agents",
    "context": "Context",
}

# What those rows used to be called. A board built before the names were settled
# keeps working: the row is looked up under its current name first, then under
# the one it was created with. Nothing to rename, nothing to re-provision.
_LEGACY_PAGES = {
    "tickets": ("Master Tickets",),
    "projects": ("Master project", "Master Projects"),
    "agents": ("Master Agents",),
    "context": ("Soul",),
}

# Highest first. Anything else — including an empty cell — sorts as normal.
PRIORITIES = ("Urgent", "High", "Normal", "Low")

# The five columns of the board, and they are meant to be read in that order.
#
# "In review" rather than "Done": nothing is done when the runner lets go of a
# ticket — a pull request is waiting for a human, and calling that Done is how a
# board stops being believed. And `failed` and `blocked` are two columns, not
# one: the agent asking a question is waiting for *you*, a session that crashed
# is waiting for someone to read a log. The runner tells them apart; the board
# used to put both in "Draft" and throw that away.
_DEFAULT_STATUS = {
    "ready": "Ready",
    "running": "In progress",
    "review": "In review",
    "done": "Done",
    "failed": "Failed",
    "blocked": "Blocked",
}


def _database_id(raw: str) -> str:
    """Normalise whatever the user pasted into something resolvable.

    A bare ID, a dashed ID and a full Notion URL all reduce to the 32-character
    identifier. Anything else is handed back untouched — it is most likely the
    database's name, which the client can look up by search.
    """
    raw = raw.strip()
    if not raw:
        return ""
    candidate = raw
    if "://" in candidate:
        candidate = candidate.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        candidate = candidate.rsplit("-", 1)[-1]
    candidate = candidate.replace("-", "")
    return candidate if is_identifier(candidate) else raw


def identifier(raw: str) -> str:
    """The 32-character ID inside whatever was pasted — a URL, or an ID.

    Named for what the caller has in hand rather than for what it points at:
    `init` is given the link of a page, not of a database.
    """
    return _database_id(raw)


def write_notion_value(path: Path, key: str, value: str) -> bool:
    """Set one key of the [notion] table, in place, keeping the comments.

    A TOML writer is not in the standard library and this file is one the user
    reads and edits by hand — rewriting it from a parsed tree would cost every
    comment in it, which is most of its value. So the line is edited, or added
    under the table header if it is not there.
    """
    text = path.read_text(encoding="utf-8")
    line = f'{key} = "{value}"'
    section = re.search(r"^\[notion\]\s*$", text, flags=re.M)
    if not section:
        path.write_text(f"{text.rstrip()}\n\n[notion]\n{line}\n", encoding="utf-8")
        return True

    start = section.end()
    following = re.search(r"^\[", text[start:], flags=re.M)
    end = start + (following.start() if following else len(text) - start)
    body = text[start:end]

    existing = re.search(rf'^{re.escape(key)}\s*=.*$', body, flags=re.M)
    if existing:
        if existing.group(0).strip() == line:
            return False
        body = body[: existing.start()] + line + body[existing.end():]
    else:
        body = "\n" + line + body

    path.write_text(text[:start] + body + text[end:], encoding="utf-8")
    return True


def is_identifier(value: str) -> bool:
    """A Notion ID is 32 hexadecimal characters, once the dashes are gone."""
    stripped = value.replace("-", "")
    return len(stripped) == 32 and all(char in "0123456789abcdefABCDEF" for char in stripped)


def load(path: Path | None = None) -> Config:
    target = path or config_path()
    if not target.exists():
        raise ConfigError(
            f"configuration not found: {target}\n"
            "  reinstall with install.sh, or copy config.example.toml"
        )
    try:
        with target.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{target} is not valid TOML: {error}") from error

    notion_raw = raw.get("notion", {})
    notion = Notion(
        token=str(notion_raw.get("token", "")).strip(),
        workspace=_database_id(str(notion_raw.get("workspace", ""))),
        tickets_database=_database_id(str(notion_raw.get("tickets_database", ""))),
        # Not merged with the defaults, for the same reason as `status` below:
        # `page_aliases()` needs to know which titles the file actually names, to
        # tell "the user calls it this" from "nobody said, so try the old names".
        pages=dict(notion_raw.get("pages", {})),
        properties={**_DEFAULT_PROPERTIES, **notion_raw.get("properties", {})},
        # Not merged with the defaults: `state()` needs to know which keys the
        # file actually sets, to let "blocked" fall back on "failed".
        status=dict(notion_raw.get("status", {})),
    )

    runner_raw = raw.get("runner", {})
    defaults = Runner()
    runner = Runner(
        workspace_root=Path(
            os.path.expanduser(
                str(runner_raw.get("workspace_root", defaults.workspace_root))
            )
        ),
        # systemd refuses a zero interval, and anything below a second would
        # only spin: one second is the floor that means anything here.
        interval_seconds=max(1, int(runner_raw.get("interval_seconds", defaults.interval_seconds))),
        max_concurrent=max(1, int(runner_raw.get("max_concurrent", defaults.max_concurrent))),
        timeout_minutes=max(1, int(runner_raw.get("timeout_minutes", defaults.timeout_minutes))),
        model=str(runner_raw.get("model", defaults.model)).strip(),
        permission_mode=str(runner_raw.get("permission_mode", defaults.permission_mode)).strip(),
        branch_prefix=str(runner_raw.get("branch_prefix", defaults.branch_prefix)),
        base_branch=str(runner_raw.get("base_branch", defaults.base_branch)).strip(),
        fetch=bool(runner_raw.get("fetch", defaults.fetch)),
        push=bool(runner_raw.get("push", defaults.push)),
        open_pull_request=bool(
            runner_raw.get("open_pull_request", defaults.open_pull_request)
        ),
        keep_worktree_on_failure=bool(
            runner_raw.get("keep_worktree_on_failure", defaults.keep_worktree_on_failure)
        ),
        attach_sessions=bool(runner_raw.get("attach_sessions", defaults.attach_sessions)),
        session_host=str(runner_raw.get("session_host", defaults.session_host)).strip(),
        notify=bool(runner_raw.get("notify", defaults.notify)),
        auto_update=bool(runner_raw.get("auto_update", defaults.auto_update)),
        # A run asks the remote at most once per this interval. The floor is a
        # minute: at a ten-second cadence, an unbounded value would turn into a
        # `git fetch` six times a minute, forever.
        update_interval_seconds=max(
            60, int(runner_raw.get("update_interval_seconds", defaults.update_interval_seconds))
        ),
        log_retention_days=max(
            0, int(runner_raw.get("log_retention_days", defaults.log_retention_days))
        ),
        dry_run=bool(runner_raw.get("dry_run", defaults.dry_run)),
        prompt_file=str(runner_raw.get("prompt_file", defaults.prompt_file)).strip(),
        document_prompt_file=str(
            runner_raw.get("document_prompt_file", defaults.document_prompt_file)
        ).strip(),
    )

    projects = {
        str(name): os.path.expanduser(str(value))
        for name, value in raw.get("projects", {}).items()
    }

    return Config(notion=notion, runner=runner, projects=projects, path=target)
