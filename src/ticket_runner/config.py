"""Reading and validating ~/.config/ticket-runner/config.toml.

The file is the single source of truth: nothing is inferred from the
environment, and a missing value is reported at install time rather than in the
middle of a ticket.
"""

from __future__ import annotations

import os
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

    def state(self, key: str) -> str:
        # "blocked" is optional: without it, a ticket the agent could not settle
        # lands wherever a technical failure lands. Naming it separately is what
        # lets "the agent asked a question" and "something broke" be told apart
        # at a glance on the board.
        if key == "blocked" and "blocked" not in self.status:
            return self.state("failed")
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
                "  ticket-runner config   opens the file in your editor"
            )


_DEFAULT_PROPERTIES = {
    "status": "Status",
    "project": "Project",
    "agent": "Agent",
    "pull_request": "Pull Request",
    "session": "Session",
    # Optional. A database without them behaves exactly as before: the runner
    # skips a property the schema does not declare.
    "model": "Model",          # per-ticket model, overrides runner.model
    "priority": "Priority",    # which ready ticket goes first
    "cost": "Cost",            # written back, in dollars
    "duration": "Duration",    # written back, in minutes
    "due": "Due Date",         # hold the ticket until that moment, then run it
    "role": "Role",            # relation: which agent handles this ticket
}

# The rows the runner looks for in the workspace database, by their title.
# Only `tickets` is required; the other two change nothing by their absence.
_DEFAULT_PAGES = {
    "tickets": "Master Tickets",
    "projects": "Master project",
    "agents": "Master Agents",
    "context": "Soul",
}

# Highest first. Anything else — including an empty cell — sorts as normal.
PRIORITIES = ("Urgent", "High", "Normal", "Low")

_DEFAULT_STATUS = {
    "ready": "Not started",
    "running": "In progress",
    "done": "Done",
    "failed": "Draft",
    "blocked": "Draft",
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
        pages={**_DEFAULT_PAGES, **notion_raw.get("pages", {})},
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
