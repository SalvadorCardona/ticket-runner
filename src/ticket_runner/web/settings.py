"""The configuration file, described well enough for a browser to draw it.

`config.toml` is the single source of truth and stays a file you can open in an
editor. What this module adds is a *description* of it — one entry per key, with
the label, the sentence of help and the type — so the console can offer the same
settings without a second idea of what a setting is.

Three rules hold the whole thing together.

- **The file's own words, not the loader's.** A field shows what the file says;
  the value the runner would use when the file says nothing is shown beside it,
  greyed, as a placeholder. That is the difference between "you chose thirty
  minutes" and "nobody said, so thirty minutes it is" — and it is why clearing a
  field *removes the line* rather than writing an empty one.
- **A secret is never sent to the browser.** A token goes out as "set, ending in
  …f3a2" and comes back only when you type a new one. Clearing one is a gesture
  of its own, so that an empty field can keep meaning "leave it alone".
- **Nothing the browser says is trusted.** Every value is checked here against
  the same rules the loader applies — the floors, the three merge methods, the
  three events — and the file itself is loaded before the save is allowed to
  stand. See `config.edit`.

Adding a setting to `config.py` and not here is caught by the test suite: a key
the console cannot reach is a key that quietly stops existing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import config as config_module
from ..config import EVENTS, MERGE_METHODS, Config

# What Claude Code accepts, and what each of them means for a runner nobody is
# watching. `bypassPermissions` is the working default: a session that stops to
# ask permission at three in the morning is a session that times out.
PERMISSION_MODES = ("bypassPermissions", "acceptEdits", "default", "plan")


@dataclass(frozen=True)
class Field:
    """One key of one table, and everything the console needs to draw it."""

    table: str
    key: str
    kind: str  # text · secret · path · bool · int · choice · events
    label: str
    help: str = ""
    choices: tuple[str, ...] = ()
    minimum: int = 0
    # What has to happen for a change to count. Most of it is read again on the
    # next run and needs nothing; the exceptions say so rather than looking like
    # they worked.
    after: str = ""

    @property
    def name(self) -> str:
        return f"{self.table}.{self.key}"


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    blurb: str
    fields: tuple[Field, ...] = ()
    # The one section that is not a list of known keys: `[projects]` is a
    # mapping you add rows to, and the console draws it as such.
    pairs: str = ""


def _naming(table: str, blurbs: dict[str, str]) -> tuple[Field, ...]:
    """A field per key of one of the three naming tables.

    Generated from the defaults rather than listed again: a property the runner
    learns to read is a field the console offers the same day.
    """
    return tuple(
        Field(
            table=f"notion.{table}",
            key=key,
            kind="text",
            label=key.replace("_", " "),
            help=blurbs.get(key, ""),
        )
        for key in config_module.defaults(table)
    )


SECTIONS: tuple[Section, ...] = (
    Section(
        key="notion",
        title="Notion",
        blurb=(
            "The board, and the integration that reads it. `ticket-runner init <page-url>` "
            "fills these in by building the databases for you; this is where you look when "
            "it has to be done by hand."
        ),
        fields=(
            Field(
                "notion", "token", "secret", "Integration token",
                "The `ntn_…` secret of your internal integration. The board has to be "
                "shared with it — a token alone sees nothing.",
            ),
            Field(
                "notion", "workspace", "text", "Workspace page",
                "The page that holds Tickets, Projects, Agents and Context. A Notion URL "
                "does: only the identifier in it is kept.",
            ),
            Field(
                "notion", "tickets_database", "text", "Tickets database",
                "Only if you name no workspace page — the ticket database on its own.",
            ),
            Field(
                "notion", "mention", "text", "How you call it",
                "The word that asks it to answer in a comment rather than to work. Its own "
                "integration name always works too.",
            ),
        ),
    ),
    Section(
        key="runner",
        title="The run",
        blurb=(
            "How often the board is read, how many tickets may run at once, and how long "
            "one of them is allowed to take."
        ),
        fields=(
            Field(
                "runner", "workspace_root", "path", "Workspace root",
                "Where your repositories live. Worktrees are made beside them, never in them.",
            ),
            Field(
                "runner", "interval_seconds", "int", "Between two runs (seconds)",
                "How long the timer waits before looking at the board again.",
                minimum=1,
                after="`ticket-runner enable` writes it into the systemd timer",
            ),
            Field(
                "runner", "max_concurrent", "int", "Tickets at once",
                "Two sessions on one laptop is already a lot of machine.",
                minimum=1,
            ),
            Field(
                "runner", "timeout_minutes", "int", "A ticket may take (minutes)",
                "Past this, the session is killed and the ticket is put back with the reason.",
                minimum=1,
            ),
            Field(
                "runner", "model", "text", "Model",
                "Empty: whatever Claude Code is set to. A ticket's own Model column wins "
                "over this one.",
            ),
            Field(
                "runner", "permission_mode", "choice", "Permission mode",
                "How much a ticket's session may do without asking. Nobody is watching it: "
                "anything but `bypassPermissions` is a session that will sit waiting.",
                choices=PERMISSION_MODES,
            ),
            Field(
                "runner", "dry_run", "bool", "Dry run",
                "Say what would happen and touch nothing — no branch, no commit, no Notion "
                "write. The one switch to leave on while you are still deciding.",
            ),
            Field(
                "runner", "log_retention_days", "int", "Keep session logs (days)",
                "0 keeps them forever.",
            ),
        ),
    ),
    Section(
        key="git",
        title="Git and pull requests",
        blurb="What a ticket with a repository turns into, and how it is accepted.",
        fields=(
            Field("runner", "branch_prefix", "text", "Branch prefix",
                  "`ticket/` gives `ticket/1a2b3c4d-remove-the-header`."),
            Field("runner", "base_branch", "text", "Base branch",
                  "Empty: whatever the repository's HEAD points at."),
            Field("runner", "fetch", "bool", "Fetch before branching",
                  "So a ticket does not start from last week."),
            Field("runner", "push", "bool", "Push the branch"),
            Field("runner", "open_pull_request", "bool", "Open a pull request",
                  "Needs `gh` to be installed and logged in."),
            Field("runner", "merge_method", "choice", "Merge a validated ticket by",
                  "What `gh pr merge` is told when you move a ticket to Validated.",
                  choices=MERGE_METHODS),
            Field("runner", "keep_worktree_on_failure", "bool", "Keep the worktree on failure",
                  "The state a failed session died in, for you to look at. "
                  "`ticket-runner clean --force` sweeps them."),
        ),
    ),
    Section(
        key="live",
        title="While it runs",
        blurb=(
            "The parts that report as the work happens: the Progress column, the session "
            "links, and the answers written under a ticket's comments."
        ),
        fields=(
            Field("runner", "progress", "bool", "Write progress into the ticket",
                  "The board's live column: what the session is doing, as it does it."),
            Field("runner", "progress_interval_seconds", "int", "Progress cadence (seconds)",
                  "The floor is five: below it, two tickets at once spend the integration's "
                  "rate limit on saying what they are about to do.",
                  minimum=5),
            Field("runner", "attach_sessions", "bool", "Link the session on the ticket",
                  "A `ticket-runner://` link that reopens the very session in a terminal."),
            Field("runner", "session_host", "text", "Session host",
                  "Set it when the runner is not on the machine you click from — the link "
                  "then says which machine to open it on."),
            Field("runner", "reply", "bool", "Answer in the comments",
                  "A comment under one of its reports is answered, in the thread, by "
                  "something that has read the ticket and the repository."),
            Field("runner", "reply_interval_seconds", "int", "Look for comments every (seconds)",
                  minimum=10),
            Field("runner", "reply_scan", "int", "Tickets scanned for comments", minimum=1),
            Field("runner", "reply_timeout_minutes", "int", "An answer may take (minutes)",
                  minimum=1),
            Field("runner", "reply_permission_mode", "choice", "Permission mode for answers",
                  "`plan` is the guardrail: a conversation that quietly edited a repository "
                  "is the one thing nobody would expect of it.",
                  choices=PERMISSION_MODES),
        ),
    ),
    Section(
        key="prompts",
        title="Prompts",
        blurb=(
            "The three briefs the runner writes, each replaceable by a file of your own. "
            "Leave them empty to keep the ones built in."
        ),
        fields=(
            Field("runner", "prompt_file", "path", "A ticket with a repository"),
            Field("runner", "document_prompt_file", "path", "A ticket without one"),
            Field("runner", "delivery_prompt_file", "path", "A validated ticket, being published"),
        ),
    ),
    Section(
        key="notify",
        title="Being told",
        blurb=(
            "Where the runner reaches you, and whether it listens for an answer. What you "
            "reply on Telegram or Slack becomes a comment on the ticket, which is already "
            "what wakes a blocked one."
        ),
        fields=(
            Field("notify", "desktop", "bool", "Notify this machine's screen"),
            Field("notify", "replies", "bool", "Read what you write back",
                  "Off: it still tells you things, it just never listens."),
            Field("notify", "events", "events", "Worth a message",
                  "`blocked` is the one that expects something back from you; `done` is the "
                  "pull request waiting; `failed` is a log to read.",
                  choices=EVENTS),
            Field("notify.telegram", "token", "secret", "Telegram bot token",
                  "From @BotFather. `ticket-runner notify --pair` then finds the chat id."),
            Field("notify.telegram", "chat", "text", "Telegram chat id",
                  "Only that chat is ever read: a bot token is a public address."),
            Field("notify.slack", "token", "secret", "Slack bot token",
                  "The `xoxb-…` one. Scopes: `chat:write`, and `channels:history` "
                  "(`groups:history`, `im:history`) to read your replies."),
            Field("notify.slack", "channel", "text", "Slack channel id",
                  "··· → View channel details, at the bottom. And `/invite @your-bot` in "
                  "the channel — the step everyone forgets."),
        ),
    ),
    Section(
        key="web",
        title="This console",
        blurb=(
            "Behind this port sits a runner that starts Claude Code sessions with "
            "`bypassPermissions`. Anything that can reach it can run code on this machine, "
            "as you — which is why the bind is loopback and why widening it is a decision "
            "you have to take on purpose, token included."
        ),
        fields=(
            Field("web", "host", "text", "Bind address",
                  "Anything but `127.0.0.1` is refused unless a token is set below. The "
                  "answer that does not depend on a token never leaking is an ssh tunnel: "
                  "`ssh -L 8787:127.0.0.1:8787 <this machine>`.",
                  after="the console has to be restarted"),
            Field("web", "port", "int", "Port", minimum=1,
                  after="the console has to be restarted"),
            Field("web", "token", "secret", "Console token",
                  "Empty: one is drawn once and kept in "
                  "`~/.local/state/ticket-runner/web/token`. Setting one here is what "
                  "allows a non-loopback bind.",
                  after="the console has to be restarted, and this page reopened with the new token"),
            Field("web", "poll_seconds", "int", "Reread the board every (seconds)",
                  "Only while a browser is connected.", minimum=5),
            Field("web", "chat_timeout_minutes", "int", "A chat turn may take (minutes)",
                  minimum=1),
        ),
    ),
    Section(
        key="update",
        title="Staying up to date",
        blurb="A run asks the remote whether the installed code is still the newest.",
        fields=(
            Field("runner", "auto_update", "bool", "Update itself between two runs"),
            Field("runner", "update_interval_seconds", "int", "Ask at most every (seconds)",
                  minimum=60),
            Field("runner", "notify", "bool", "One desktop notification per ticket",
                  "The old switch, kept: “Notify this machine's screen” above defaults to it."),
        ),
    ),
    Section(
        key="projects",
        title="Projects",
        blurb=(
            "A Notion project, and the repository it means on this machine. Only needed "
            "when the project page says nothing: a `path` or a `github` property on the "
            "page keeps the mapping on the board, where every machine can read it."
        ),
        pairs="projects",
    ),
    Section(
        key="status",
        title="The columns of your board",
        blurb=(
            "What each moment is called in your Notion. Empty means the default, and the "
            "defaults are not arbitrary: leaving `blocked` unset while naming `failed` is "
            "how you say your board has one column for both."
        ),
        fields=_naming(
            "status",
            {
                "ready": "the column the runner claims from",
                "running": "where it puts a ticket it has taken",
                "review": "a pull request is waiting for you",
                "validated": "you accepted it — the runner merges, or publishes",
                "done": "in, and closed",
                "failed": "something broke; there is a log to read",
                "blocked": "it asked you something and is waiting",
            },
        ),
    ),
    Section(
        key="properties",
        title="The columns of the ticket database",
        blurb=(
            "What each property is called. The optional ones change nothing by their "
            "absence: a database without a Cost column is a database that is not told "
            "what a ticket cost."
        ),
        fields=_naming(
            "properties",
            {
                "status": "required",
                "project": "relation to the projects database",
                "agent": "which machine took the ticket",
                "pull_request": "written back when one is opened",
                "session": "the link that reopens the session",
                "model": "per-ticket model, overriding the one above",
                "priority": "which ready ticket goes first",
                "cost": "written back, in dollars",
                "duration": "written back, in minutes",
                "progress": "what the session is doing right now",
                "due": "a date here holds the ticket until that moment",
                "role": "relation to the agents database",
            },
        ),
    ),
    Section(
        key="pages",
        title="The rows of the workspace page",
        blurb=(
            "The titles the runner looks for under your workspace page. Only Tickets is "
            "required; the others change nothing by their absence."
        ),
        fields=_naming(
            "pages",
            {
                "tickets": "required",
                "projects": "a ticket's repository is found through it",
                "agents": "the crafts a ticket can be handled by",
                "context": "who the work is for, read into every prompt",
            },
        ),
    ),
)

FIELDS: dict[str, Field] = {
    entry.name: entry for section in SECTIONS for entry in section.fields
}


def _table(raw: dict, table: str) -> dict:
    """One `[a.b]` table of the parsed file, or an empty one."""
    node: object = raw
    for part in table.split("."):
        if not isinstance(node, dict):
            return {}
        node = node.get(part)
    return node if isinstance(node, dict) else {}


def _fallback(config: Config, entry: Field) -> object:
    """What the runner uses when the file says nothing about this key.

    Read off the loaded configuration rather than written down again, so the
    placeholder cannot drift from the default it claims to show.
    """
    if entry.table == "notion.status":
        return config_module.defaults("status")[entry.key]
    if entry.table == "notion.properties":
        return config_module.defaults("properties")[entry.key]
    if entry.table == "notion.pages":
        return config_module.defaults("pages")[entry.key]
    holder = {
        "notion": config.notion,
        "runner": config.runner,
        "notify": config.notify,
        "web": config.web,
    }.get(entry.table)
    if holder is None:  # a channel table: nothing is defaulted into it
        return ""
    value = getattr(holder, entry.key, "")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def _preview(secret: str) -> str:
    """Enough of a token to recognise it by, and not enough to use it."""
    secret = secret.strip()
    if not secret:
        return ""
    return f"…{secret[-4:]}" if len(secret) > 8 else "set"


def describe(config: Config) -> dict:
    """Every setting, as the console draws it. No secret leaves in here."""
    raw = config_module.read_raw(config.path)
    sections = []
    for section in SECTIONS:
        drawn = {
            "key": section.key,
            "title": section.title,
            "blurb": section.blurb,
            "pairs": section.pairs,
            "fields": [],
        }
        for entry in section.fields:
            stated = _table(raw, entry.table).get(entry.key)
            shown: dict = {
                "name": entry.name,
                "kind": entry.kind,
                "label": entry.label,
                "help": entry.help,
                "choices": list(entry.choices),
                "fallback": _fallback(config, entry),
                "after": entry.after,
                "stated": stated is not None,
            }
            if entry.kind == "secret":
                # Not `_fallback`: for a secret that is the value itself, and
                # the placeholder would carry out the very thing it exists to
                # keep in. A token has no default worth showing anyway.
                shown["value"] = ""
                shown["fallback"] = ""
                shown["preview"] = _preview(str(stated or ""))
            elif entry.kind == "events":
                shown["value"] = [str(item) for item in stated] if isinstance(stated, list) else None
            elif entry.kind == "bool":
                shown["value"] = bool(stated) if stated is not None else None
            elif entry.kind == "int":
                shown["value"] = int(stated) if isinstance(stated, int) else None
            else:
                shown["value"] = str(stated) if stated is not None else ""
            drawn["fields"].append(shown)
        sections.append(drawn)

    problem = ""
    try:
        config.require_usable()
    except config_module.ConfigError as error:
        problem = str(error).splitlines()[0]

    return {
        "path": str(config.path),
        "usable": not problem,
        "problem": problem,
        "sections": sections,
        "projects": [
            {"name": name, "path": path}
            for name, path in sorted(_table(raw, "projects").items())
        ],
    }


def _value(entry: Field, offered: object) -> object:
    """One value from the browser, as the file may hold it — or `None` to unset.

    Everything the loader would silently repair is refused here instead. A floor
    the loader raises quietly is a field that saves, comes back changed and
    tells nobody why.
    """
    if offered is None:
        return None
    if entry.kind == "bool":
        if not isinstance(offered, bool):
            raise ValueError(f"{entry.label}: yes or no")
        return offered
    if entry.kind == "int":
        if isinstance(offered, bool) or not isinstance(offered, (int, str)):
            raise ValueError(f"{entry.label}: a number")
        try:
            number = int(str(offered).strip())
        except ValueError:
            raise ValueError(f"{entry.label}: “{offered}” is not a number") from None
        if number < max(entry.minimum, 0):
            raise ValueError(f"{entry.label}: {entry.minimum} at the least")
        return number
    if entry.kind == "events":
        if not isinstance(offered, list):
            raise ValueError(f"{entry.label}: a list")
        chosen = [str(item).strip().lower() for item in offered]
        unknown = [name for name in chosen if name not in EVENTS]
        if unknown:
            raise ValueError(f"{entry.label}: no such moment “{unknown[0]}”")
        # An empty list is a real answer — "tell me nothing" — so it is written
        # rather than removed, which would bring the three back.
        return sorted(set(chosen), key=EVENTS.index)
    text = str(offered).strip()
    if entry.kind == "choice":
        if text and text not in entry.choices:
            raise ValueError(f"{entry.label}: one of {', '.join(entry.choices)}")
    # Blank means "say nothing about it", which is how the default comes back.
    return text or None


def _projects(raw: dict, offered: object) -> list[tuple[str, str, object]]:
    """The `[projects]` table as the browser now has it, against what is there."""
    if not isinstance(offered, list):
        raise ValueError("projects: a list of {name, path}")
    wanted: dict[str, str] = {}
    for row in offered:
        if not isinstance(row, dict):
            raise ValueError("projects: a list of {name, path}")
        name = str(row.get("name", "")).strip()
        path = str(row.get("path", "")).strip()
        if not name and not path:
            continue  # a row somebody started and left
        if not name:
            raise ValueError(f"a project mapped to {path} has no name")
        if not path:
            raise ValueError(f"“{name}” maps to nothing — give it a path, or remove the row")
        if name in wanted:
            raise ValueError(f"“{name}” is named twice")
        wanted[name] = path
    changes: list[tuple[str, str, object]] = [
        ("projects", name, None) for name in _table(raw, "projects") if name not in wanted
    ]
    changes += [("projects", name, path) for name, path in wanted.items()]
    return changes


def save(config: Config, payload: dict) -> dict:
    """Apply what the console sent. Nothing, or all of it — see `config.edit`.

    Only the keys the browser actually names are touched: a field left alone is
    a line the file keeps, comment and all. That is also what makes a secret
    safe to leave blank — blank was never sent.
    """
    offered = payload.get("settings")
    if offered is not None and not isinstance(offered, dict):
        raise ValueError("settings: a table of name → value")

    changes: list[tuple[str, str, object]] = []
    touched: list[Field] = []
    for name, value in (offered or {}).items():
        entry = FIELDS.get(str(name))
        if entry is None:
            raise ValueError(f"no such setting: {name}")
        changes.append((entry.table, entry.key, _value(entry, value)))
        touched.append(entry)

    if "projects" in payload:
        changes += _projects(config_module.read_raw(config.path), payload["projects"])

    if not changes:
        return {"saved": [], "after": []}

    written = config_module.edit(config.path, changes)
    return {
        "saved": written,
        # Said once each, and only for what actually moved: a notice about a
        # restart you do not need is a notice you stop reading.
        "after": sorted(
            {entry.after for entry in touched if entry.after and entry.name in written}
        ),
    }
