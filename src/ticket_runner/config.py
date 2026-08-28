"""Lecture et validation de ~/.config/ticket-runner/config.toml.

Le fichier est la seule source de vérité : rien n'est deviné à partir de
l'environnement, et une valeur absente est signalée à l'installation plutôt
qu'au milieu d'un ticket.
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
    """Configuration absente, illisible ou incomplète."""


@dataclass
class Notion:
    token: str = ""
    tickets_database: str = ""
    properties: dict[str, str] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)

    def prop(self, key: str) -> str:
        return self.properties.get(key, _DEFAULT_PROPERTIES[key])

    def state(self, key: str) -> str:
        return self.status.get(key, _DEFAULT_STATUS[key])


@dataclass
class Runner:
    workspace_root: Path = Path.home() / "workspace"
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
    dry_run: bool = False
    prompt_file: str = ""


@dataclass
class Config:
    notion: Notion
    runner: Runner
    projects: dict[str, str]
    path: Path

    def require_usable(self) -> None:
        """Lève ConfigError si le fichier ne permet pas de tourner."""
        missing = []
        if not self.notion.token or self.notion.token == PLACEHOLDER:
            missing.append("notion.token")
        if not self.notion.tickets_database:
            missing.append("notion.tickets_database")
        if missing:
            raise ConfigError(
                f"{', '.join(missing)} à renseigner dans {self.path}\n"
                "  ticket-runner config   ouvre le fichier dans votre éditeur"
            )


_DEFAULT_PROPERTIES = {
    "status": "Status",
    "project": "Project",
    "agent": "Agent",
    "pull_request": "Pull Request",
    "session": "Session",
}

_DEFAULT_STATUS = {
    "ready": "Not started",
    "running": "In progress",
    "done": "Done",
    "failed": "Draft",
}


def _database_id(raw: str) -> str:
    """Accepte un ID nu, avec tirets, ou une URL Notion complète."""
    raw = raw.strip()
    if not raw:
        return ""
    if "://" in raw:
        raw = raw.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        raw = raw.rsplit("-", 1)[-1]
    raw = raw.replace("-", "")
    return raw


def load(path: Path | None = None) -> Config:
    target = path or config_path()
    if not target.exists():
        raise ConfigError(
            f"configuration introuvable : {target}\n"
            "  réinstallez avec install.sh, ou copiez config.example.toml"
        )
    try:
        with target.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{target} n'est pas un TOML valide : {error}") from error

    notion_raw = raw.get("notion", {})
    notion = Notion(
        token=str(notion_raw.get("token", "")).strip(),
        tickets_database=_database_id(str(notion_raw.get("tickets_database", ""))),
        properties={**_DEFAULT_PROPERTIES, **notion_raw.get("properties", {})},
        status={**_DEFAULT_STATUS, **notion_raw.get("status", {})},
    )

    runner_raw = raw.get("runner", {})
    defaults = Runner()
    runner = Runner(
        workspace_root=Path(
            os.path.expanduser(
                str(runner_raw.get("workspace_root", defaults.workspace_root))
            )
        ),
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
        dry_run=bool(runner_raw.get("dry_run", defaults.dry_run)),
        prompt_file=str(runner_raw.get("prompt_file", defaults.prompt_file)).strip(),
    )

    projects = {
        str(name): os.path.expanduser(str(value))
        for name, value in raw.get("projects", {}).items()
    }

    return Config(notion=notion, runner=runner, projects=projects, path=target)
