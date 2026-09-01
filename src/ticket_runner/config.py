"""Reading and validating ~/.config/ticket-runner/config.toml.

The file is the single source of truth: nothing is inferred from the
environment, and a missing value is reported at install time rather than in the
middle of a ticket.
"""

from __future__ import annotations

import os
import re
import threading
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
    # How you call it when you want it to answer rather than to work. Its own
    # name, as Notion writes it when you @-mention the integration, is always
    # understood too — this is for the word you would actually type.
    mention: str = ""
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
        # "validated" reads the same way, against a named `review` or `done`: a
        # file that says where a ticket waits to be looked at, or where it goes
        # once it is, and nothing about where you accept it, described a board
        # that ends at the pull request. It falls back on `review`, which is
        # where the ticket already sits, and the runner reads a `validated` that
        # is `review` as "this board has no such gesture". Renaming some other
        # column is not a statement about this one: a file that names only
        # `ready` still gets the default, and the board decides from there.
        if key == "validated" and "validated" not in self.status:
            if "review" in self.status or "done" in self.status:
                return self.state("review")
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
    # How a validated pull request is merged. `gh` has to be told which of the
    # three it is, and the runner will not pick for you at the last moment: a
    # board that squashes wants every ticket squashed.
    merge_method: str = "squash"
    keep_worktree_on_failure: bool = True
    attach_sessions: bool = True
    session_host: str = ""
    notify: bool = True
    # The steps of a running session, written into its ticket as they happen.
    progress: bool = True
    progress_interval_seconds: int = 10
    # Answering in the comments: a ticket as somewhere to talk, not only
    # somewhere to ask. See conversation.py for what wakes an answer.
    reply: bool = True
    # A person wrote the comment and a person is waiting for the answer, so a
    # minute is soon enough — and the scan costs one request per page.
    reply_interval_seconds: int = 60
    reply_scan: int = 20
    reply_timeout_minutes: int = 10
    # `plan` is the guardrail, not the prompt: a conversation that quietly
    # edited a repository is the one thing nobody would expect of it.
    reply_permission_mode: str = "plan"
    auto_update: bool = True
    update_interval_seconds: int = 3600
    log_retention_days: int = 14
    dry_run: bool = False
    prompt_file: str = ""
    document_prompt_file: str = ""
    delivery_prompt_file: str = ""


# What `gh pr merge` accepts, and the whole of it: anything else is a typo, and
# a typo here would only be discovered by GitHub refusing the one merge you were
# watching.
MERGE_METHODS = ("squash", "merge", "rebase")


# The three moments worth a message. `blocked` is the one that matters: it is
# the only one that expects something back from you.
EVENTS = ("blocked", "failed", "done")


@dataclass
class Notify:
    """Where the runner reaches you, and whether it listens for an answer.

    Desktop notifications are the old behaviour and stay the default; a channel
    exists only if its two values are filled in. `replies` is the half that
    makes a notification a question: without it the runner still writes to
    Telegram or Slack, it just never reads what you write back.
    """

    desktop: bool = True
    replies: bool = True
    events: tuple[str, ...] = EVENTS
    telegram: dict[str, str] = field(default_factory=dict)
    slack: dict[str, str] = field(default_factory=dict)

    def wants(self, event: str) -> bool:
        return event in self.events

    @property
    def remote(self) -> bool:
        """Is there anywhere to write to besides this machine's screen?"""
        return bool(
            (self.telegram.get("token") and self.telegram.get("chat"))
            or (self.slack.get("token") and self.slack.get("channel"))
        )


@dataclass
class Web:
    """The console: a board, a command line and a chat, in one page.

    Loopback by default, and that is not a placeholder. Behind this port sits a
    runner that starts Claude Code sessions with `bypassPermissions` — so the
    port is arbitrary code execution on this machine, and anything reachable
    from elsewhere has to be a decision somebody took on purpose. `serve`
    refuses a non-loopback host unless a token is configured; the way to reach
    the console from another machine is an ssh tunnel, not a wider bind.
    """

    host: str = "127.0.0.1"
    port: int = 8787
    token: str = ""
    # How often the console asks Notion what the board looks like — and only
    # while a browser is actually watching. Nobody is watching most of the time,
    # and a poll nobody reads spends the integration's rate limit for nothing.
    poll_seconds: int = 15
    # A chat turn is a Claude session like any other, and wants the same kind of
    # ceiling. Shorter than a ticket's: somebody is sitting in front of it.
    chat_timeout_minutes: int = 20


@dataclass
class Config:
    notion: Notion
    runner: Runner
    projects: dict[str, str]
    path: Path
    web: Web = field(default_factory=Web)
    notify: Notify = field(default_factory=Notify)

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
    # What the session is doing right now, rewritten every few seconds while it
    # runs and cleared when it ends. The board's live column.
    "progress": "Progress",
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

# The columns of the board, and they are meant to be read in that order.
#
# "In review" rather than "Done": nothing is done when the runner lets go of a
# ticket — a pull request is waiting for a human, and calling that Done is how a
# board stops being believed. And `failed` and `blocked` are two columns, not
# one: the agent asking a question is waiting for *you*, a session that crashed
# is waiting for someone to read a log. The runner tells them apart; the board
# used to put both in "Draft" and throw that away.
#
# "Validated" is the answer to the question "In review" asks. Reviewing ends in
# a gesture — merge this, publish this — and that gesture is the one thing a
# board cannot do for you and the runner should not decide alone. So you move
# the ticket one column to the right, and the runner does the gesture: it
# merges the pull request, or it publishes what the ticket holds, and only then
# is anything Done. A board that does not offer the column has no such moment,
# and nothing changes: you merge by hand, as before.
_DEFAULT_STATUS = {
    "ready": "Ready",
    "running": "In progress",
    "review": "In review",
    "validated": "Validated",
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
    """Set one key of the [notion] table. See `write_value`."""
    return write_value(path, "notion", key, value)


# A TOML key that needs no quotes. Anything else — a project called "Site
# vitrine", a status column with an accent — is written quoted, and looked up
# under both spellings: the file may have been typed by hand.
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")

_ESCAPES = (("\\", "\\\\"), ('"', '\\"'), ("\n", "\\n"), ("\r", "\\r"), ("\t", "\\t"))


def _literal(value: object) -> str:
    """One TOML right-hand side, in the four shapes this file holds.

    A string is escaped rather than interpolated: a token with a quote in it
    used to write a line that stopped the file from parsing, and the next thing
    anybody saw was "configuration not found".
    """
    if isinstance(value, bool):  # before int: a bool *is* an int in Python
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_literal(str(item)) for item in value) + "]"
    text = str(value)
    for raw, encoded in _ESCAPES:
        text = text.replace(raw, encoded)
    text = "".join(character if character >= " " else "" for character in text)
    return f'"{text}"'


def write_value(path: Path, table: str, key: str, value: object) -> bool:
    """Set — or, with `value=None`, remove — one key of one table, in place.

    A TOML writer is not in the standard library and this file is one the user
    reads and edits by hand — rewriting it from a parsed tree would cost every
    comment in it, which is most of its value. So the line is edited, or added
    under the table header if it is not there.

    Removing rather than emptying is deliberate: a key the file does not carry
    is a key the loader fills in itself, and that is what the console means when
    a field is left blank. The comments around it survive, so the line comes
    back documented if it is ever set again.

    `table` is written as it appears between the brackets, dots included:
    "notify.telegram" finds `[notify.telegram]`.

    Returns whether the file changed.
    """
    text = path.read_text(encoding="utf-8")
    written = key if _BARE_KEY.match(key) else _literal(key)
    line = "" if value is None else f"{written} = {_literal(value)}"
    section = re.search(rf"^\[{re.escape(table)}\]\s*$", text, flags=re.M)
    if not section:
        if not line:
            return False
        path.write_text(f"{text.rstrip()}\n\n[{table}]\n{line}\n", encoding="utf-8")
        return True

    start = section.end()
    following = re.search(r"^\[", text[start:], flags=re.M)
    end = start + (following.start() if following else len(text) - start)
    body = text[start:end]

    spellings = "|".join({re.escape(key), re.escape(_literal(key))})
    existing = re.search(rf"^(?:{spellings})\s*=.*$", body, flags=re.M)
    if existing:
        if line:
            if existing.group(0).strip() == line:
                return False
            body = body[: existing.start()] + line + body[existing.end():]
        else:
            stop = existing.end() + (1 if body[existing.end() : existing.end() + 1] == "\n" else 0)
            body = body[: existing.start()] + body[stop:]
    elif line:
        body = "\n" + line + body
    else:
        return False

    path.write_text(text[:start] + body + text[end:], encoding="utf-8")
    return True


def edit(path: Path, changes: list[tuple[str, str, object]]) -> list[str]:
    """Apply a set of changes to the file — all of them, or none at all.

    This is what the console saves through, and it is the one writer that does
    not trust its caller. A configuration is not a form: half of it applied is a
    runner that claims tickets it cannot finish. So the edits are made on a copy
    beside the file, the copy is *loaded* — if it will not parse, or would leave
    a working installation unable to run, nothing moves — and only then does it
    take the file's place, in one `os.replace` and with its permissions.

    The file it displaces is kept as `config.toml.bak`, which is what you want
    the first time a save turns out to have been the wrong idea.

    Returns the names of the keys that actually changed, `table.key` each.
    """
    original = path.read_text(encoding="utf-8")
    try:
        load(path).require_usable()
        was_usable = True
    except ConfigError:
        was_usable = False

    # Named per call: two saves at once — two browser tabs, a tab and the CLI —
    # would otherwise edit the same copy and the loser would win.
    scratch = path.parent / f".{path.name}.saving.{os.getpid()}.{threading.get_ident()}"
    scratch.write_text(original, encoding="utf-8")
    try:
        touched = [
            f"{table}.{key}"
            for table, key, value in changes
            if write_value(scratch, table, key, value)
        ]
        if not touched:
            return []
        try:
            fresh = load(scratch)
            if was_usable:
                fresh.require_usable()
        # Broad on purpose: the loader coerces as it reads, and anything it
        # refuses to read — a port that is not a number, a path that is not one
        # — has to come back as "not saved" rather than as a traceback and half
        # a file. The scratch copy is what took it, so there is nothing to undo.
        except Exception as error:  # noqa: BLE001
            raise ConfigError(
                f"that would leave the configuration unusable — "
                f"{str(error).splitlines()[0].replace(str(scratch), str(path))}"
            ) from error
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = 0o600
        backup = path.parent / f"{path.name}.bak"
        backup.write_text(original, encoding="utf-8")
        backup.chmod(0o600)
        scratch.chmod(mode)
        os.replace(scratch, path)
    finally:
        if scratch.exists():
            scratch.unlink()
    return touched


def read_raw(path: Path) -> dict:
    """The file as it is written, with nothing filled in.

    `load` is the runner's view: every default applied, every floor enforced.
    This is the file's own, and the console needs it to tell "you chose the
    default" from "you said nothing and the default answered".
    """
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def defaults(table: str) -> dict[str, str]:
    """The names the runner falls back on, for one of the three naming tables.

    `properties`, `status`, `pages` — the three places where a board that spells
    a column its own way says so. Public because the console draws a field per
    key, and a key it did not know about would be a setting nobody can reach.
    """
    return dict(
        {
            "properties": _DEFAULT_PROPERTIES,
            "status": _DEFAULT_STATUS,
            "pages": _DEFAULT_PAGES,
        }[table]
    )


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
        mention=str(notion_raw.get("mention", "")).strip(),
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
        merge_method=(
            str(runner_raw.get("merge_method", "")).strip().lower()
            if str(runner_raw.get("merge_method", "")).strip().lower() in MERGE_METHODS
            else defaults.merge_method
        ),
        keep_worktree_on_failure=bool(
            runner_raw.get("keep_worktree_on_failure", defaults.keep_worktree_on_failure)
        ),
        attach_sessions=bool(runner_raw.get("attach_sessions", defaults.attach_sessions)),
        session_host=str(runner_raw.get("session_host", defaults.session_host)).strip(),
        notify=bool(runner_raw.get("notify", defaults.notify)),
        progress=bool(runner_raw.get("progress", defaults.progress)),
        # Ten seconds reads as live and costs three writes a ticket per tick.
        # The floor is five: below that, two tickets running at once would spend
        # the integration's rate limit on saying what they are about to do.
        progress_interval_seconds=max(
            5,
            int(runner_raw.get("progress_interval_seconds", defaults.progress_interval_seconds)),
        ),
        reply=bool(runner_raw.get("reply", defaults.reply)),
        # The floor is ten seconds, which is the fastest a run itself goes: a
        # zero here would turn every pass into a full scan of the board.
        reply_interval_seconds=max(
            10, int(runner_raw.get("reply_interval_seconds", defaults.reply_interval_seconds))
        ),
        reply_scan=max(1, int(runner_raw.get("reply_scan", defaults.reply_scan))),
        reply_timeout_minutes=max(
            1, int(runner_raw.get("reply_timeout_minutes", defaults.reply_timeout_minutes))
        ),
        reply_permission_mode=str(
            runner_raw.get("reply_permission_mode", defaults.reply_permission_mode)
        ).strip()
        or defaults.reply_permission_mode,
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
        delivery_prompt_file=str(
            runner_raw.get("delivery_prompt_file", defaults.delivery_prompt_file)
        ).strip(),
    )

    projects = {
        str(name): os.path.expanduser(str(value))
        for name, value in raw.get("projects", {}).items()
    }

    web_raw = raw.get("web", {})
    web_defaults = Web()
    web = Web(
        host=str(web_raw.get("host", web_defaults.host)).strip() or web_defaults.host,
        port=int(web_raw.get("port", web_defaults.port)),
        token=str(web_raw.get("token", web_defaults.token)).strip(),
        # Five seconds is the floor for the same reason as the live report's:
        # below that, a page left open in a tab becomes a second full-time
        # reader of the board.
        poll_seconds=max(5, int(web_raw.get("poll_seconds", web_defaults.poll_seconds))),
        chat_timeout_minutes=max(
            1, int(web_raw.get("chat_timeout_minutes", web_defaults.chat_timeout_minutes))
        ),
    )

    notify_raw = raw.get("notify", {})
    # `runner.notify` came first and said "one desktop notification per ticket".
    # It keeps saying exactly that: the new table only has to name what it
    # changes, and a file written before any of this existed behaves as it did.
    events = notify_raw.get("events", EVENTS)
    notify = Notify(
        desktop=bool(notify_raw.get("desktop", runner.notify)),
        replies=bool(notify_raw.get("replies", True)),
        # Filtered rather than trusted: a typo in this list would otherwise
        # silence a moment without ever saying so.
        events=tuple(
            name
            for name in (str(value).strip().lower() for value in events)
            if name in EVENTS
        ),
        telegram=_channel(notify_raw.get("telegram")),
        slack=_channel(notify_raw.get("slack")),
    )

    return Config(
        notion=notion,
        runner=runner,
        projects=projects,
        path=target,
        web=web,
        notify=notify,
    )


def _channel(raw: object) -> dict[str, str]:
    """One [notify.<channel>] table, as strings — a chat id is not a number.

    Telegram's chat ids are integers, negative for a group, and TOML will hand
    them over as such. Everything downstream compares them to what the API
    returns in JSON, where they are strings.
    """
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value).strip() for key, value in raw.items()}
