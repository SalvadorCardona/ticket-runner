#!/usr/bin/env python3
"""The road a ticket travels, end to end, under assertions.

    python3 tests/functional.py

`tests/run.py` covers the pure part and assumes it touches nothing — not Notion,
not git, not the network. What that leaves uncovered is the road itself: ready
ticket, worktree, session, branch, pull request, status written back. And that
is the half which breaks quietly. A ticket that runs on an empty directory, a
session paid for and thrown away, a pull request nobody ever linked to its
ticket — none of those raises anything. They leave a board that still looks
plausible.

So the world is doubled rather than mocked. A Notion of our own answers on a
local port and keeps a state any test can read back; a repository and a bare
remote stand in for GitHub; a `claude` and a `gh` at the head of `PATH` do what
the real ones do, minus the thinking and the network. The runner is told none of
it: it loads a configuration, reads its board and works. The one thing it cannot
guess is where Notion lives, and that is the single seam added to the code —
`TICKET_RUNNER_NOTION_API`, see `notion.endpoint`.

Nothing here leaves the machine, and nothing is written outside a temporary
directory: `XDG_STATE_HOME` moves with the test, and takes the worktrees, the
logs and the history with it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ticket_runner import config as C  # noqa: E402
from ticket_runner import notion  # noqa: E402
from ticket_runner.config import PRIORITIES  # noqa: E402
from ticket_runner.runner import Runner  # noqa: E402

CASES = []


def case(function):
    CASES.append(function)
    return function


def _ident() -> str:
    """A Notion identifier: 32 hexadecimal characters, as `is_identifier` reads."""
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# -- a Notion of our own -----------------------------------------------------


def _rich(text: str) -> list[dict]:
    """Rich text as Notion hands it back — content to write, plain_text to read."""
    return [{"type": "text", "text": {"content": text}, "plain_text": text}]


def _stored(value: dict) -> dict:
    """One written property, as a reader would then find it.

    `notion._encode` writes `{"status": {"name": "Done"}}`: the type is the only
    key, and it is not repeated inside. What comes back from the API carries it
    as `type`, and a rich text carries `plain_text` beside the content it was
    given. Doing both here is what makes a value written by the runner readable
    by the runner — which is most of what these tests are about.
    """
    kind = next(iter(value))
    stored = {"type": kind, **value}
    if kind in ("rich_text", "title"):
        stored[kind] = [
            {**part, "plain_text": part.get("text", {}).get("content", "")}
            for part in value[kind]
        ]
    return stored


class Board:
    """Notion reduced to what `notion.py` actually asks of it.

    Pages, databases, blocks and comments in four dictionaries, and the routing
    that serves them. Everything a test wants to know afterwards — the status a
    ticket ended on, the pull request written into it, what was said in its
    comments — is read straight off here rather than off a transcript of
    requests: the point is the board somebody would look at on Monday.
    """

    def __init__(self) -> None:
        self.databases: dict[str, dict] = {}
        self.pages: dict[str, dict] = {}
        self.blocks: dict[str, list[dict]] = {}
        self.comments: list[dict] = []
        self.requests: list[str] = []
        # Every request this Notion could not answer, so that a run is never
        # silently short of one: most roads in `notion.py` swallow a refusal.
        self.refused: list[str] = []
        self.me = {"object": "user", "id": _ident(), "name": "Ticket Runner", "type": "bot"}

    # -- building a board ----------------------------------------------------

    def database(self, title: str, properties: dict) -> str:
        identifier = _ident()
        self.databases[identifier] = {
            "object": "database",
            "id": identifier,
            "title": _rich(title),
            "properties": properties,
        }
        return identifier

    def page(
        self,
        properties: dict[str, dict],
        *,
        database: str = "",
        body: str = "",
    ) -> str:
        identifier = _ident()
        self.pages[identifier] = {
            "object": "page",
            "id": identifier,
            "url": f"https://notion.invalid/{identifier}",
            "created_time": _now(),
            "last_edited_time": _now(),
            "parent": (
                {"type": "database_id", "database_id": database}
                if database
                else {"type": "workspace", "workspace": True}
            ),
            "properties": properties,
        }
        self.blocks[identifier] = (
            [{"object": "block", "id": _ident(), "type": "paragraph",
              "has_children": False, "paragraph": {"rich_text": _rich(line)}}
             for line in body.splitlines() if line.strip()]
            if body
            else []
        )
        return identifier

    # -- reading it back -----------------------------------------------------

    def value(self, page_id: str, name: str) -> Any:
        page = self.pages[page_id]
        return notion.read(
            notion.Page(id=page_id, url="", title="", properties=page["properties"]), name
        )

    def body(self, page_id: str) -> str:
        """The page's blocks, flattened — enough to say what was written into it."""
        lines = []
        for block in self.blocks.get(page_id, []):
            payload = block.get(block.get("type", ""), {})
            lines.append("".join(part.get("plain_text", "") for part in payload.get("rich_text", [])))
        return "\n".join(lines)

    def said(self, page_id: str) -> list[str]:
        """Everything commented on that page, oldest first."""
        return [
            "".join(part.get("plain_text", "") for part in comment["rich_text"])
            for comment in self.comments
            if comment["page"] == page_id
        ]

    # -- serving it ----------------------------------------------------------

    def handle(self, method: str, path: str, query: dict, body: dict, token: str):
        """One request, routed. The endpoints `notion.py` calls, and those only.

        Anything else is refused *and remembered*: a client that grew a request
        nobody doubled here would otherwise fail somewhere far from here, and
        most of the roads in `notion.py` swallow a refusal on purpose.
        """
        self.requests.append(f"{method} {path}")
        if not token.startswith("Bearer "):
            return 401, {"message": "API token is invalid"}
        parts = [part for part in path.split("/") if part]
        if parts and parts[0] == "v1":
            parts = parts[1:]
        route = (method, *("*" if C.is_identifier(part) else part for part in parts))
        identifier = next((part for part in parts if C.is_identifier(part)), "")

        if route == ("GET", "databases", "*"):
            found = self.databases.get(identifier)
            return (200, found) if found else (404, {"message": "database not found"})
        if route == ("POST", "databases", "*", "query"):
            return 200, self._query(identifier, body)
        if route == ("GET", "pages", "*"):
            found = self.pages.get(identifier)
            return (200, found) if found else (404, {"message": "page not found"})
        if route == ("PATCH", "pages", "*"):
            return self._update(identifier, body)
        if route == ("GET", "blocks", "*", "children"):
            return 200, {"results": self.blocks.get(identifier, []), "has_more": False}
        if route == ("PATCH", "blocks", "*", "children"):
            return 200, {"results": self._append(identifier, body.get("children", []))}
        if route == ("PATCH", "blocks", "*"):
            return 200, {"object": "block", "id": identifier}
        if route == ("GET", "comments"):
            page = (query.get("block_id") or [""])[0].replace("-", "")
            return 200, {
                "results": [one for one in self.comments if one["page"] == page],
                "has_more": False,
            }
        if route == ("POST", "comments"):
            return self._comment(body)
        if route == ("GET", "users", "me"):
            return 200, self.me
        self.refused.append(f"{method} /{'/'.join(parts)}")
        return 404, {"message": f"the fake Notion does not serve {method} /{'/'.join(parts)}"}

    def _query(self, database_id: str, body: dict) -> dict:
        if database_id not in self.databases:
            return {"results": [], "has_more": False}
        filter_ = body.get("filter")
        results = [
            page
            for page in self.pages.values()
            if page["parent"].get("database_id") == database_id and self._matches(page, filter_)
        ]
        return {"results": results, "has_more": False, "next_cursor": None}

    def _matches(self, page: dict, filter_: dict | None) -> bool:
        if not filter_:
            return True
        if "and" in filter_:
            return all(self._matches(page, one) for one in filter_["and"])
        if "or" in filter_:
            return any(self._matches(page, one) for one in filter_["or"])
        name = filter_.get("property", "")
        value = notion.read(
            notion.Page(id=page["id"], url="", title="", properties=page["properties"]), name
        )
        for kind, condition in filter_.items():
            if kind == "property" or not isinstance(condition, dict):
                continue
            if "equals" in condition and value != condition["equals"]:
                return False
            if "does_not_equal" in condition and value == condition["does_not_equal"]:
                return False
        return True

    def _update(self, page_id: str, body: dict):
        page = self.pages.get(page_id)
        if not page:
            return 404, {"message": "page not found"}
        schema = {}
        database = page["parent"].get("database_id", "")
        if database in self.databases:
            schema = self.databases[database]["properties"]
        for name, value in body.get("properties", {}).items():
            if schema and name not in schema:
                # Notion refuses a property the database does not declare, and
                # the runner leans on that: `update` skips those before writing.
                return 400, {"message": f"{name} is not a property that exists"}
            page["properties"][name] = _stored(value)
        page["last_edited_time"] = _now()
        return 200, page

    def _append(self, block_id: str, children: list[dict]) -> list[dict]:
        created = []
        for child in children:
            block = {"object": "block", "id": _ident(), "has_children": False, **child}
            payload = block.get(block.get("type", ""))
            if isinstance(payload, dict) and isinstance(payload.get("rich_text"), list):
                # Written without `plain_text`, read with it — see `_stored`.
                payload["rich_text"] = [
                    {**part, "plain_text": part.get("text", {}).get("content", "")}
                    for part in payload["rich_text"]
                ]
            self.blocks.setdefault(block_id, []).append(block)
            created.append(block)
        return created

    def _comment(self, body: dict):
        discussion = body.get("discussion_id", "")
        page = (body.get("parent") or {}).get("page_id", "").replace("-", "")
        if discussion and not page:
            page = next(
                (one["page"] for one in self.comments if one["discussion_id"] == discussion), ""
            )
        if not page:
            return 400, {"message": "a comment needs a parent page or a discussion"}
        comment = {
            "object": "comment",
            "id": _ident(),
            "page": page,
            "discussion_id": discussion or _ident(),
            "created_time": _now(),
            "created_by": {"object": "user", "id": self.me["id"]},
            "rich_text": [
                {**part, "plain_text": part.get("text", {}).get("content", "")}
                for part in body.get("rich_text", [])
            ],
        }
        self.comments.append(comment)
        return 200, comment


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._answer("GET")

    def do_POST(self) -> None:
        self._answer("POST")

    def do_PATCH(self) -> None:
        self._answer("PATCH")

    def log_message(self, *args: object) -> None:
        """A test suite that narrates every request is a test suite nobody reads."""

    def _answer(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        parsed = urlparse(self.path)
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        try:
            status, payload = self.server.board.handle(  # type: ignore[attr-defined]
                method,
                parsed.path,
                parse_qs(parsed.query),
                body,
                self.headers.get("Authorization", ""),
            )
        except Exception as error:  # noqa: BLE001 — a fake that raises must still answer
            # 400 rather than 500: the client retries a 500 four times, a minute
            # apart, and a broken double would spend that minute before saying
            # anything. This one is our fault and says so at once.
            self.server.board.refused.append(f"{method} {parsed.path}: {error}")  # type: ignore[attr-defined]
            status, payload = 400, {"message": f"{type(error).__name__}: {error}"}
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@contextmanager
def _notion_server():
    """A Notion answering on a loopback port nobody chose in advance."""
    board = Board()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.board = board  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", board
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# -- the machine the runner thinks it is on ----------------------------------


GIT = '''
"""`git`, recorded and then run for real.

A scenario that wants to say "this ticket touched no repository" has to be able
to say it of every git command, not of the ones somebody thought of.
"""
import json, os, sys

# Written in when the script is laid down: the real git, found before this one
# went to the head of the PATH.
REAL = None

log = os.environ.get("FAKE_GIT_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"cwd": os.getcwd(), "args": sys.argv[1:]}) + "\\n")
os.execv(REAL, ["git", *sys.argv[1:]])
'''

CLAUDE = '''
"""A Claude Code session, reduced to what the runner reads of one.

It does the one thing a session is judged on — leaving something behind — and
says so in the stream the runner parses: a commit in a repository, an
`ANSWER.md` where there is none. `FAKE_CLAUDE_FAIL` makes it the other kind of
session, the one that stops and explains itself.
"""
import json, os, subprocess, sys
from pathlib import Path

args = sys.argv[1:]
prompt = args[-1] if args else ""
session = args[args.index("--session-id") + 1] if "--session-id" in args else ""

log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"cwd": os.getcwd(), "session": session, "prompt": prompt}) + "\\n")


def emit(event):
    print(json.dumps(event), flush=True)


emit({"type": "system", "subtype": "init", "session_id": session})

refused = os.environ.get("FAKE_CLAUDE_FAIL", "")
if refused:
    emit({"type": "result", "subtype": "error_during_execution", "is_error": True,
          "result": refused, "session_id": session, "num_turns": 1, "total_cost_usd": 0.0})
    raise SystemExit(1)

here = Path.cwd()
if (here / ".git").exists():
    (here / "FAKE.md").write_text("the session was here\\n", encoding="utf-8")
    subprocess.run(["git", "add", "FAKE.md"], cwd=here, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.name=Fake Claude", "-c", "user.email=fake@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "Écrit par la fausse session"],
                   cwd=here, check=True, capture_output=True)
    said = "RESULT: ok — un fichier écrit et commité"
else:
    (here / "ANSWER.md").write_text("La réponse.", encoding="utf-8")
    said = "RESULT: ok — la réponse est dans ANSWER.md"

emit({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}})
emit({"type": "result", "subtype": "success", "is_error": False, "result": said,
      "session_id": session, "num_turns": 3, "total_cost_usd": 0.02})
'''

GH = '''
"""`gh`, reduced to the questions the runner asks it.

Opening a pull request is the one gesture of a code ticket that leaves the
machine, so it is the one worth recording: what was asked, from where, and the
URL handed back — which is what the ticket is then supposed to carry.
"""
import json, os, sys

args = sys.argv[1:]
log = os.environ.get("FAKE_GH_LOG", "")


def option(name):
    return args[args.index(name) + 1] if name in args else ""


def recorded():
    if not log or not os.path.exists(log):
        return []
    with open(log, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


if args[:2] == ["pr", "create"]:
    number = len([one for one in recorded() if one["command"] == "pr create"]) + 1
    url = "https://github.com/fake/repo/pull/" + str(number)
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"command": "pr create", "cwd": os.getcwd(), "url": url,
                                     "base": option("--base"), "title": option("--title"),
                                     "body": option("--body")}) + "\\n")
    print("Creating pull request for " + option("--base"))
    print(url)
    raise SystemExit(0)

if args[:2] == ["pr", "view"]:
    # `--json state` asks about a pull request by its URL; `--json url` asks
    # whether this branch already has one, and here it never does.
    if "state" in args:
        print("OPEN")
        raise SystemExit(0)
    raise SystemExit(1)

if args[:2] == ["pr", "list"]:
    raise SystemExit(0)

raise SystemExit(1)
'''


def _script(path: Path, source: str) -> None:
    path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
    path.chmod(0o755)


def _binaries(into: Path) -> None:
    """The three commands the runner shells out to, at the head of `PATH`.

    `git` is the real one behind a recorder, `claude` and `gh` are doubles —
    those two are the network and the money.
    """
    into.mkdir(parents=True, exist_ok=True)
    real = shutil.which("git") or "/usr/bin/git"
    _script(into / "git", GIT.replace("REAL = None", f"REAL = {real!r}"))
    _script(into / "claude", CLAUDE)
    _script(into / "gh", GH)


def _git(args: list[str], cwd: Path) -> None:
    """A git command of the fixtures' own, identity included.

    Spelled out rather than inherited: a machine whose global configuration has
    no name, or signs every commit, must not be the reason a test fails.
    """
    result = subprocess.run(
        ["git", "-c", "user.name=Bench", "-c", "user.email=bench@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# -- the board, the configuration, the run -----------------------------------


TICKETS = {
    "Name": {"type": "title", "title": {}},
    "Status": {
        "type": "status",
        "status": {
            "options": [
                {"name": name}
                for name in ("Ready", "In progress", "In review", "Validated",
                             "Done", "Failed", "Blocked")
            ]
        },
    },
    "Project": {"type": "relation", "relation": {}},
    "Runner": {"type": "rich_text", "rich_text": {}},
    "Pull Request": {"type": "url", "url": {}},
    "Session": {"type": "rich_text", "rich_text": {}},
    "Priority": {"type": "select", "select": {"options": [{"name": name} for name in PRIORITIES]}},
    "Scheduled": {"type": "date", "date": {}},
    "Duration": {"type": "number", "number": {}},
    "Cost": {"type": "number", "number": {}},
}

# The installation every scenario runs on. The road under test is on — fetch,
# push, pull request — and what is off is not cheating: each of those is a road
# of its own, already covered in `tests/run.py`, or one that reaches outside the
# machine, which is the one thing a test may not do.
SETTINGS = {
    "fetch": True,
    "push": True,
    "open_pull_request": True,
    "keep_worktree_on_failure": False,  # so "no orphan worktree" means something
    "attach_sessions": False,           # nothing is moved into ~/.claude
    "notify": False,                    # no desktop notification from a test
    "progress": False,                  # the live report is its own machinery
    "reply": False,                     # so is answering comments
    "schedule": False,
    "auto_update": False,
    "log_retention_days": 0,
    "timeout_minutes": 1,
    "max_concurrent": 2,
}


class Bench:
    """One machine, one board, and the gestures a scenario is written in."""

    def __init__(self, root: Path, board: Board, database: str, logs: dict[str, Path]) -> None:
        self.root = root
        self.board = board
        self.database = database
        self.logs = logs
        self.config = root / "config.toml"

    # -- fixtures ------------------------------------------------------------

    def repository(self, name: str) -> Path:
        """A clone with a bare remote of its own, standing in for GitHub."""
        bare = self.root / "remotes" / f"{name}.git"
        work = self.root / "workspace" / name
        bare.parent.mkdir(parents=True, exist_ok=True)
        work.parent.mkdir(parents=True, exist_ok=True)
        _git(["init", "--bare", "--initial-branch=main", str(bare)], self.root)
        _git(["init", "--initial-branch=main", str(work)], self.root)
        (work / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        _git(["add", "README.md"], work)
        _git(["commit", "-m", "premier commit"], work)
        _git(["remote", "add", "origin", str(bare)], work)
        _git(["push", "--set-upstream", "origin", "main"], work)
        return work

    def project(self, name: str, repository: Path | None = None, brief: str = "") -> str:
        """A project page: a title, and the path its tickets are worked on."""
        properties = {"Name": _stored({"title": _rich(name)})}
        if repository is not None:
            properties["Path"] = _stored({"rich_text": _rich(str(repository))})
        return self.board.page(properties, body=brief)

    def ticket(self, title: str, body: str, project: str = "", status: str = "Ready") -> str:
        properties = {
            "Name": _stored({"title": _rich(title)}),
            "Status": _stored({"status": {"name": status}}),
        }
        if project:
            properties["Project"] = _stored({"relation": [{"id": project}]})
        return self.board.page(properties, database=self.database, body=body)

    # -- running -------------------------------------------------------------

    def run(self) -> list[dict]:
        """One pass of the runner, exactly the one the timer makes."""
        for path in self.logs.values():
            path.write_text("", encoding="utf-8")
        results = Runner(C.load(self.config), quiet=True).tick()
        assert not self.board.refused, f"the fake Notion could not answer {self.board.refused}"
        return results

    # -- reading back --------------------------------------------------------

    def status(self, ticket: str) -> str:
        return str(self.board.value(ticket, "Status") or "")

    def git_calls(self) -> list[dict]:
        return _lines(self.logs["FAKE_GIT_LOG"])

    def pull_requests(self) -> list[dict]:
        return [one for one in _lines(self.logs["FAKE_GH_LOG"]) if one["command"] == "pr create"]

    def sessions(self) -> list[dict]:
        return _lines(self.logs["FAKE_CLAUDE_LOG"])

    def worktrees(self, repository: Path) -> list[str]:
        """The worktrees git knows about, the repository itself excluded."""
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(repository), capture_output=True, text=True, timeout=60,
        )
        return [
            line.split(" ", 1)[1]
            for line in result.stdout.splitlines()
            if line.startswith("worktree ") and line.split(" ", 1)[1] != str(repository)
        ]

    def branches(self, repository: Path) -> list[str]:
        """What the bare remote of that repository holds."""
        bare = self.root / "remotes" / f"{repository.name}.git"
        result = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            cwd=str(bare), capture_output=True, text=True, timeout=60,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def files_on(self, repository: Path, branch: str) -> list[str]:
        bare = self.root / "remotes" / f"{repository.name}.git"
        result = subprocess.run(
            ["git", "ls-tree", "--name-only", branch],
            cwd=str(bare), capture_output=True, text=True, timeout=60,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]


CONFIGURATION = """# Written by tests/functional.py — a whole installation, in a temporary directory.
[notion]
token = "ntn_functional_tests"
tickets_database = "{database}"

[runner]
workspace_root = "{workspace}"
{settings}
"""


@contextmanager
def bench(**overrides: object):
    """A machine with a Notion, a workspace and a PATH of its own.

    Everything it changes is put back on the way out, the temporary directory
    included — so two scenarios never share a board, a state directory or a
    branch, and a scenario that fails leaves the machine as it found it.
    """
    with tempfile.TemporaryDirectory(prefix="ticket-runner-functional-") as directory:
        root = Path(directory)
        _binaries(root / "bin")
        with _notion_server() as (api, board):
            logs = {
                name: root / "logs" / f"{name.lower()}.jsonl"
                for name in ("FAKE_GIT_LOG", "FAKE_GH_LOG", "FAKE_CLAUDE_LOG")
            }
            for path in logs.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            environment = {
                notion.API_ENV: api,
                "XDG_STATE_HOME": str(root / "state"),
                "PATH": f"{root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
                "FAKE_CLAUDE_FAIL": "",
                **{name: str(path) for name, path in logs.items()},
            }
            with _environ(environment):
                database = board.database("Tickets", TICKETS)
                settings = {**SETTINGS, **overrides}
                (root / "config.toml").write_text(
                    CONFIGURATION.format(
                        database=database,
                        workspace=root / "workspace",
                        settings="\n".join(
                            f"{key} = {json.dumps(value)}" for key, value in settings.items()
                        ),
                    ),
                    encoding="utf-8",
                )
                yield Bench(root, board, database, logs)


@contextmanager
def _environ(changes: dict[str, str]):
    previous = {name: os.environ.get(name) for name in changes}
    os.environ.update(changes)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# -- the scenarios -----------------------------------------------------------


@case
def a_code_ticket_comes_back_as_a_pull_request():
    """Ready → worktree → session → branch → pull request → the ticket says so.

    The whole road in one pass, and the last step is the one that goes wrong
    quietly: a pull request that opens and is never written back onto the ticket
    leaves a board saying the work is still to do.
    """
    with bench() as machine:
        repository = machine.repository("site")
        project = machine.project("Site", repository)
        ticket = machine.ticket("Corriger l'entête", "Le titre est faux, corrige-le.", project)

        results = machine.run()

        assert len(results) == 1, results
        assert results[0]["status"] == "done", results
        assert machine.status(ticket) == "In review", machine.status(ticket)

        branch = results[0]["branch"]
        assert branch.startswith("ticket/corriger-l-entete-"), branch
        assert branch in machine.branches(repository), machine.branches(repository)
        assert "FAKE.md" in machine.files_on(repository, branch)

        opened = machine.pull_requests()
        assert len(opened) == 1, opened
        assert opened[0]["base"] == "main", opened[0]
        assert opened[0]["title"] == "Corriger l'entête", opened[0]
        page = machine.board.pages[ticket]["url"]
        assert page in opened[0]["body"], "the pull request does not link back to the ticket"
        assert machine.board.value(ticket, "Pull Request") == opened[0]["url"]

        assert str(machine.board.value(ticket, "Runner") or "").startswith("ticket-runner@")
        assert machine.board.value(ticket, "Session"), "the session was not written onto the ticket"
        assert machine.board.value(ticket, "Duration") is not None

        said = machine.board.said(ticket)
        assert said, "the ticket came back without a word"
        assert opened[0]["url"] in said[-1], said[-1]
        assert not machine.worktrees(repository), "a worktree was left behind on a run that worked"


@case
def a_writing_ticket_is_answered_in_its_page_and_touches_no_repository():
    """A project with no repository: the deliverable is the Notion page.

    And nothing else. A document ticket that quietly made a worktree, or ran one
    git command anywhere, would be a writing task turned into a commit on
    something — which is the failure this scenario exists to catch.
    """
    with bench() as machine:
        project = machine.project("Lettre d'information", None, brief="On écrit court.")
        ticket = machine.ticket("Rédiger l'édito", "Deux paragraphes sur l'automne.", project)

        results = machine.run()

        assert len(results) == 1, results
        assert results[0]["status"] == "done" and results[0]["kind"] == "document", results
        assert machine.status(ticket) == "Done", machine.status(ticket)
        assert "La réponse." in machine.board.body(ticket), machine.board.body(ticket)
        assert results[0]["blocks"] > 0

        assert not machine.git_calls(), machine.git_calls()
        assert not machine.pull_requests(), "a document ticket opened a pull request"
        assert machine.board.value(ticket, "Pull Request") is None

        sessions = machine.sessions()
        assert len(sessions) == 1, sessions
        assert "On écrit court." in sessions[0]["prompt"], "the project's brief never reached it"
        state = Path(os.environ["XDG_STATE_HOME"]) / "ticket-runner"
        assert not (state / "worktrees").exists(), "a document ticket made a worktree"
        assert not list((state / "scratch").glob("*")), "its scratch directory was left behind"


@case
def a_session_that_fails_leaves_a_readable_ticket_and_no_worktree():
    """The failure has to be readable on the board, and cost nothing on disk.

    A failed run used to be the one that left things behind: a ticket stuck in
    "in progress" and a worktree holding a branch, which then refuses the next
    attempt at the very same ticket.
    """
    with bench() as machine:
        repository = machine.repository("site")
        project = machine.project("Site", repository)
        ticket = machine.ticket("Une tâche impossible", "Fais l'impossible.", project)

        with _environ({"FAKE_CLAUDE_FAIL": "la session s'est arrêtée : rien à faire ici"}):
            results = machine.run()

        assert len(results) == 1, results
        assert results[0]["status"] == "failed", results
        assert machine.status(ticket) == "Failed", machine.status(ticket)

        said = machine.board.said(ticket)
        assert said, "a ticket that failed was not told why"
        assert "rien à faire ici" in said[-1], said[-1]

        assert not machine.worktrees(repository), machine.worktrees(repository)
        worktrees = Path(os.environ["XDG_STATE_HOME"]) / "ticket-runner" / "worktrees"
        assert not list(worktrees.glob("*")), "the worktree is still on disk"
        assert not machine.pull_requests(), "a failed session still opened a pull request"
        assert machine.branches(repository) == ["main"], machine.branches(repository)


@case
def a_ticket_runs_in_the_repository_its_project_names():
    """Two projects, one ticket: the relation decides which repository is touched.

    The expensive mistake here is silent — a ticket committed to the wrong clone
    is work nobody ever finds — so the other repository is checked as closely as
    the right one.
    """
    with bench() as machine:
        site = machine.repository("site")
        api = machine.repository("api")
        machine.project("Site", site)
        second = machine.project("API", api)
        ticket = machine.ticket("Ajouter une route", "Une route de plus.", second)

        results = machine.run()

        assert results[0]["status"] == "done", results
        assert results[0]["project"] == "API", results
        branch = results[0]["branch"]
        assert branch.startswith("ticket/ajouter-une-route-"), branch

        assert branch in machine.branches(api), machine.branches(api)
        assert machine.branches(site) == ["main"], machine.branches(site)
        assert "FAKE.md" in machine.files_on(api, branch)
        assert "FAKE.md" not in machine.files_on(site, "main")

        sessions = machine.sessions()
        assert len(sessions) == 1, sessions
        # The worktree is named after the project it belongs to, and the session
        # ran in it — which is the same statement as the two above, said where
        # the work actually happened rather than where it landed.
        assert Path(sessions[0]["cwd"]).name.startswith("api-"), sessions[0]["cwd"]
        assert not machine.worktrees(site) and not machine.worktrees(api)


def main() -> int:
    started = time.monotonic()
    failures = 0
    for function in CASES:
        try:
            function()
        except Exception:  # noqa: BLE001 — a test runner reports, it does not raise
            failures += 1
            print(f"  ✗ {function.__name__}")
            print("".join("      " + line for line in traceback.format_exc().splitlines(True)))
        else:
            print(f"  ✓ {function.__name__}")
    total = len(CASES)
    print(f"\n{total - failures}/{total} passed in {time.monotonic() - started:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
