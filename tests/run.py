#!/usr/bin/env python3
"""The pure part of ticket-runner, under assertions.

    python3 tests/run.py

No framework and no dependency, for the same reason the runner has none: a test
suite that needs an install is a test suite that stops being run. Everything
here is pure — nothing touches Notion, git, the network or the disk beyond a
temporary file.

What is covered is what has already gone wrong once, or would go wrong silently:
identifiers that collide, a status name that does not exist, markdown that
reaches Notion as a wall of text, a summary that keeps its verdict.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import threading
import traceback
import contextlib
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ticket_runner import config as C  # noqa: E402
from ticket_runner import agents, channels, conversation, markdown, notion  # noqa: E402
from ticket_runner import progress, projects, prompt, provision, session, state  # noqa: E402
from ticket_runner.channels import slack as slack_channel, telegram as telegram_channel  # noqa: E402
from ticket_runner import update, workspace  # noqa: E402
from ticket_runner import runner as runner_module  # noqa: E402
from ticket_runner.runner import Runner  # noqa: E402
from ticket_runner import __version__  # noqa: E402
from ticket_runner.__main__ import _names, banner, subcommands, welcome  # noqa: E402
from ticket_runner.__main__ import main as cli_main  # noqa: E402
from ticket_runner.__main__ import build_parser  # noqa: E402
from ticket_runner.web import api as web_api  # noqa: E402
from ticket_runner.web import console as web_console  # noqa: E402
from ticket_runner.web import settings as web_settings  # noqa: E402
from ticket_runner.web import live as web_live  # noqa: E402
from ticket_runner.runner import short_id, slugify  # noqa: E402
from ticket_runner.projects import _normalise  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import release  # noqa: E402

CASES = []


def case(function):
    CASES.append(function)
    return function


# -- identifiers -------------------------------------------------------------


@case
def short_ids_tell_same_day_tickets_apart():
    """Notion IDs are time-ordered, so same-day tickets share a long prefix.

    Two real tickets, created minutes apart, collided on their first eight
    characters — and would have shared one scratch directory.
    """
    a = "3ca451680af480ae9443de0b65d9abf8"
    b = "3ca451680af480beb02ac9d2cb79078c"
    assert a[:8] == b[:8], "premise: these two really do share a prefix"
    assert short_id(a) != short_id(b)
    assert short_id("3ca45168-0af4-80ae-9443-de0b65d9abf8") == short_id(a)
    assert len(short_id(a)) == 8


@case
def a_log_is_found_however_its_id_was_pasted():
    b = "3ca451680af480beb02ac9d2cb79078c"
    name = f"20260828-112441-{short_id(b)}.jsonl"
    assert _names(b, name)
    assert _names("3ca45168-0af4-80be-b02a-c9d2cb79078c", name)
    assert _names("https://www.notion.so/Ticket-" + b, name)
    assert _names(short_id(b), name)
    assert not _names("3ca451680af480ae9443de0b65d9abf8", name), "a neighbour must not match"


@case
def slugs_survive_accents_and_emptiness():
    assert slugify("Supprimer la description") == "supprimer-la-description"
    assert slugify("Corriger l'entête « à faire »") == "corriger-l-entete-a-faire"
    assert slugify("") == "ticket"
    assert len(slugify("x" * 200)) <= 40


# -- projects ----------------------------------------------------------------


@case
def remotes_normalise_to_owner_and_name():
    for url in (
        "git@github.com:SalvadorCardona/trader-ia.git",
        "https://github.com/SalvadorCardona/trader-ia",
        "https://github.com/SalvadorCardona/trader-ia.git",
        "ssh://git@github.com/SalvadorCardona/trader-ia.git",
    ):
        assert _normalise(url) == "salvadorcardona/trader-ia", url


# -- configuration -----------------------------------------------------------


def _config(body: str) -> C.Config:
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n' + body)
    return C.load(path)


@case
def a_database_reference_is_normalised_but_a_name_is_not():
    assert C._database_id(
        "https://www.notion.so/w/Master-Tickets-3c3451680af480f5b1aad0785c0322b4?v=1"
    ) == "3c3451680af480f5b1aad0785c0322b4"
    assert C._database_id("3c345168-0af4-80f5-b1aa-d0785c0322b4") == "3c3451680af480f5b1aad0785c0322b4"
    # Not an identifier: handed back untouched, to be looked up by name.
    assert C._database_id("Master Tickets") == "Master Tickets"
    assert C.is_identifier("3c3451680af480f5b1aad0785c0322b4")
    assert not C.is_identifier("Master Tickets")


@case
def blocked_falls_back_on_failed_but_only_when_unset():
    config = _config('[notion.status]\nfailed = "Blocked"\n')
    assert config.notion.state("blocked") == "Blocked"
    assert config.notion.state("ready") == "Ready", "defaults survive a partial block"

    config = _config('[notion.status]\nfailed = "Draft"\nblocked = "Blocked"\n')
    assert config.notion.state("failed") == "Draft"
    assert config.notion.state("blocked") == "Blocked"

    config = _config("")
    assert config.notion.state("review") == "In review"
    assert config.notion.state("done") == "Done"
    assert config.notion.state("blocked") == "Blocked", "its own column, not the failure one"
    assert config.notion.state("failed") == "Failed"


@case
def review_falls_back_on_done_but_only_when_done_is_named():
    """A file that names `done` and not `review` has one column for both.

    Which is also what turns the merge watch off: there is no column for a
    ticket to wait in, so there is nothing to watch. A file that names neither
    gets the defaults, which are two — an open pull request and a merged one
    are not the same day.
    """
    config = _config('[notion.status]\ndone = "Shipped"\n')
    assert config.notion.state("review") == config.notion.state("done") == "Shipped"

    config = _config("")
    assert config.notion.state("review") == "In review"
    assert config.notion.state("done") == "Done", "the defaults keep them apart"

    config = _config('[notion.status]\nreview = "Waiting on you"\ndone = "Shipped"\n')
    assert config.notion.state("review") == "Waiting on you"
    assert config.notion.state("done") == "Shipped"


@case
def a_merge_method_gh_would_refuse_never_reaches_it():
    """The typo is caught here, not by GitHub refusing the merge you watched."""
    assert _config("").runner.merge_method == "squash"
    assert _config('[runner]\nmerge_method = "rebase"\n').runner.merge_method == "rebase"
    assert _config('[runner]\nmerge_method = "MERGE"\n').runner.merge_method == "merge"
    assert _config('[runner]\nmerge_method = "fast-forward"\n').runner.merge_method == "squash"

    from ticket_runner import git as git_module

    assert set(git_module.MERGE_FLAGS) == set(C.MERGE_METHODS)


@case
def the_interval_never_reaches_systemd_as_zero():
    assert _config("[runner]\ninterval_seconds = 0\n").runner.interval_seconds == 1
    assert _config("[runner]\ninterval_seconds = 10\n").runner.interval_seconds == 10
    assert _config("").runner.interval_seconds == 1800


@case
def the_update_check_never_runs_more_than_once_a_minute():
    """At a ten-second cadence, an unbounded value would fetch six times a minute."""
    assert _config("").runner.update_interval_seconds == 3600
    assert _config("[runner]\nupdate_interval_seconds = 5\n").runner.update_interval_seconds == 60
    assert _config("").runner.auto_update is True
    assert _config("[runner]\nauto_update = false\n").runner.auto_update is False


@case
def optional_properties_have_names_even_when_absent():
    config = _config("")
    for key in ("status", "project", "agent", "pull_request", "session", "model",
                "priority", "cost", "duration"):
        assert config.notion.prop(key), key


@case
def a_workspace_is_named_once_and_the_rest_is_found():
    config = _config("")
    assert config.notion.page("tickets") == "Tickets"
    assert config.notion.page("context") == "Context"
    renamed = _config('[notion.pages]\ncontext = "Qui je suis"\n')
    assert renamed.notion.page("context") == "Qui je suis"
    assert renamed.notion.page("tickets") == "Tickets", "defaults survive a partial block"


@case
def a_workspace_alone_is_enough_to_run():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        '[notion]\ntoken = "ntn_real"\n'
        'workspace = "https://www.notion.so/w/3a8451680af480918afcf0eb9cf70e7b?v=1"\n'
    )
    config = C.load(path)
    assert config.notion.workspace == "3a8451680af480918afcf0eb9cf70e7b", "URL reduced to an ID"
    assert not config.notion.tickets_database
    config.require_usable()  # neither raises nor needs a tickets database


@case
def neither_a_workspace_nor_a_database_is_refused():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntoken = "ntn_real"\n')
    try:
        C.load(path).require_usable()
    except C.ConfigError as error:
        assert "notion.workspace" in str(error)
    else:
        raise AssertionError("a configuration naming no tickets database must be refused")


# -- the workspace -----------------------------------------------------------


class _FakeClient:
    """Just enough Notion to resolve a workspace, and nothing that reaches out."""

    def __init__(self, rows: dict[str, str], text: str = "", broken: set[str] = frozenset()):
        self._rows = rows
        self._text = text
        self._broken = broken

    def resolve_database(self, identifier: str) -> str:
        if identifier in self._broken:
            raise notion.NotionError(f"{identifier}: object not found")
        return f"db-of-{identifier}"

    def query(self, database_id: str, filter_=None) -> list[notion.Page]:
        return [notion.Page(id=page, url="", title=title) for title, page in self._rows.items()]

    def blocks_text(self, page_id: str, depth: int = 0) -> str:
        if page_id in self._broken:
            raise notion.NotionError(f"{page_id}: object not found")
        return self._text


def _settings(**overrides) -> C.Notion:
    values = {"token": "ntn_real", "workspace": "space", "pages": {}}
    values.update(overrides)
    return C.Notion(**values)


@case
def the_rows_of_a_workspace_become_the_runners_databases():
    client = _FakeClient(
        {"Tickets": "p-tickets", "Projects": "p-projects", "Context": "p-context"},
        text="Je suis Salvador Cardona.",
    )
    space = workspace.resolve(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.projects == "db-of-p-projects"
    assert space.context == "Je suis Salvador Cardona."
    assert not space.warnings


@case
def a_row_is_found_however_its_title_is_capitalised():
    client = _FakeClient({"tickets": "p-tickets", "CONTEXT": "p-context"}, text="x")
    space = workspace.resolve(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.context == "x"


@case
def a_board_built_before_the_names_were_settled_still_resolves():
    """The rows shipped as "Master Tickets" and "Soul" before those names settled.

    Renaming four rows by hand is not a migration anyone should be asked to run,
    so the old titles are tried after the current ones — and only while the
    configuration itself names none, since a title someone typed is a title
    they meant.
    """
    client = _FakeClient(
        {"Master Tickets": "p-tickets", "Master project": "p-projects", "Soul": "p-soul"},
        text="who I am",
    )
    space = workspace.resolve(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.projects == "db-of-p-projects"
    assert space.context == "who I am"
    assert not space.warnings

    # The new names win when a board carries both, rather than the older row.
    both = _FakeClient({"Tickets": "p-new", "Master Tickets": "p-old"})
    assert workspace.resolve(both, _settings()).tickets == "db-of-p-new"

    # And a configuration that names a row is never second-guessed.
    named = _settings(pages={"tickets": "Backlog"})
    try:
        workspace.resolve(_FakeClient({"Master Tickets": "p-old"}), named)
    except notion.NotionError as error:
        assert "Backlog" in str(error)
    else:
        raise AssertionError("a named row must not fall back on a legacy title")


@case
def a_missing_context_page_warns_but_never_fails_a_run():
    client = _FakeClient({"Tickets": "p-tickets"})
    space = workspace.resolve(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.context == "" and space.projects == ""
    assert any("Context" in warning for warning in space.warnings)

    # Present but unreadable, and present but empty, are both worth saying too.
    unreadable = _FakeClient({"Tickets": "p-t", "Context": "p-context"}, broken={"p-context"})
    assert any("unreadable" in warning for warning in workspace.resolve(unreadable, _settings()).warnings)
    empty = _FakeClient({"Tickets": "p-t", "Context": "p-context"}, text="   ")
    assert any("empty" in warning for warning in workspace.resolve(empty, _settings()).warnings)


@case
def a_missing_tickets_page_is_the_one_thing_that_fails():
    client = _FakeClient({"Context": "p-context", "Projects": "p-projects"})
    try:
        workspace.resolve(client, _settings())
    except notion.NotionError as error:
        assert "Tickets" in str(error)
        assert "Context" in str(error), "the message lists what was actually found"
    else:
        raise AssertionError("a workspace without a tickets page must not resolve")


@case
def an_explicit_database_still_wins_over_the_workspace():
    client = _FakeClient({"Tickets": "p-tickets"})
    space = workspace.resolve(client, _settings(tickets_database="chosen"))
    assert space.tickets == "db-of-chosen"

    # And a configuration written before workspaces existed resolves the same.
    legacy = workspace.resolve(client, _settings(workspace="", tickets_database="chosen"))
    assert legacy.tickets == "db-of-chosen"
    assert legacy.rows == {} and not legacy.warnings


# -- provisioning ------------------------------------------------------------


class _Board:
    """A Notion that remembers what was created, without a network in sight."""

    def __init__(self, databases=None, rows=None, schemas=None, text=""):
        self._databases = databases or {}          # page id -> {title: db id}
        self._rows = rows or {}                    # db id -> {title: page id}
        self._schemas = schemas or {}              # db id -> {name: {shape}}
        self._text = text
        self.created = []
        self.patched = []
        self.appended = []

    # reading
    def child_databases(self, page_id):
        return dict(self._databases.get(page_id, {}))

    def schema(self, database_id):
        return {name: next(iter(shape)) for name, shape in self._schemas.get(database_id, {}).items()}

    def database(self, database_id):
        return {"properties": {
            name: {"type": next(iter(shape)), **shape}
            for name, shape in self._schemas.get(database_id, {}).items()
        }}

    def query(self, database_id, filter_=None):
        return [
            notion.Page(id=page, url="", title=title)
            for title, page in self._rows.get(database_id, {}).items()
        ]

    def blocks_text(self, page_id, depth=0):
        return self._text

    # writing
    def create_database(self, parent_page_id, title, properties, *, inline=True):
        identifier = f"db-{title.lower().replace(' ', '-')}"
        self._databases.setdefault(parent_page_id, {})[title] = identifier
        self._schemas[identifier] = dict(properties)
        self._rows.setdefault(identifier, {})
        self.created.append(identifier)
        return identifier

    def add_properties(self, database_id, properties):
        self._schemas.setdefault(database_id, {}).update(properties)
        self.patched.append((database_id, sorted(properties)))

    def create_row(self, database_id, title, values=None):
        page = f"page-{title.lower().replace(' ', '-')}"
        self._rows.setdefault(database_id, {})[title] = page
        self.created.append(page)
        return page

    def append_markdown(self, page_id, markdown):
        # A page that has just been written to is no longer empty — which is
        # what stops the second `init` from seeding the context page again.
        self.appended.append(page_id)
        self._text = markdown
        return 1


@case
def a_bare_page_becomes_the_whole_board():
    board = _Board()
    report = provision.provision(board, _settings(), "root")

    assert report.workspace == "db-ticket-runner"
    assert report.tickets == "db-tickets"
    rows = board._rows["db-ticket-runner"]
    assert set(rows) == {"Tickets", "Projects", "Agents", "Context"}

    schema = board._schemas["db-tickets"]
    for expected in ("Status", "Project", "Agent", "Runner", "Session", "Scheduled"):
        assert expected in schema, expected

    # The relations point at databases that existed before the tickets did.
    assert schema["Project"]["relation"]["database_id"] == "db-projects"
    assert schema["Agent"]["relation"]["database_id"] == "db-agents"

    # A status property cannot be created through the API; a select can, and the
    # runner reads both. Every column must be there, validated included.
    options = [option["name"] for option in schema["Status"]["select"]["options"]]
    assert options == [
        "Ready", "In progress", "In review", "Validated", "Done", "Failed", "Blocked",
    ]

    assert board.appended, "the context page is seeded rather than left blank"


@case
def running_init_twice_changes_nothing():
    board = _Board()
    provision.provision(board, _settings(), "root")
    before = dict(board._schemas["db-tickets"])
    board.created.clear()

    second = provision.provision(board, _settings(), "root")
    assert board.created == [], "nothing is created a second time"
    assert board._schemas["db-tickets"] == before
    assert second.tickets == "db-tickets"
    assert all(verb == "kept" for verb, _ in second.steps), second.steps


@case
def init_completes_a_board_that_predates_a_column():
    """The second reason this command exists: adding what a version did not have.

    A board built before `Scheduled` gets the column rather than a line in a
    changelog telling its owner to add it by hand.
    """
    board = _Board(
        databases={"root": {"ticket-runner": "dir"}, "page-tickets": {"Tickets": "db-tickets"}},
        rows={"dir": {"Tickets": "page-tickets"}},
        schemas={"db-tickets": {"Name": {"title": {}}, "Status": {"select": {"options": [
            {"name": "Ready", "color": "blue"}, {"name": "Mine", "color": "purple"},
        ]}}}},
    )
    provision.provision(board, _settings(), "root")

    schema = board._schemas["db-tickets"]
    assert "Scheduled" in schema and "Cost" in schema

    # Options are merged, never replaced: a column somebody added is still there.
    options = [option["name"] for option in schema["Status"]["select"]["options"]]
    assert "Mine" in options and "Blocked" in options
    assert options.index("Mine") < options.index("Blocked"), "what exists keeps its place"


@case
def a_real_status_column_is_reported_rather_than_patched():
    """The one thing the API cannot do, said out loud instead of discovered late.

    A `status` property built in Notion's own interface accepts no new options
    from the API. Silence here would surface as a ticket failing to be marked
    "Blocked", weeks later, at the end of a session.
    """
    board = _Board(
        databases={"root": {"ticket-runner": "dir"}, "page-tickets": {"Tickets": "db-tickets"}},
        rows={"dir": {"Tickets": "page-tickets"}},
        schemas={"db-tickets": {"Name": {"title": {}}, "Status": {"status": {"options": [
            {"name": "Ready"}, {"name": "In progress"},
        ]}}}},
    )
    report = provision.provision(board, _settings(), "root")

    assert not any(name == "Status" for _, names in board.patched for name in names)
    told = [what for verb, what in report.steps if verb == "by hand"]
    assert told and "In review" in told[0] and "Blocked" in told[0], told
    assert "Ready" not in told[0], "only what is actually missing"


@case
def a_column_someone_retyped_is_left_alone():
    board = _Board(
        databases={"root": {"ticket-runner": "dir"}, "page-tickets": {"Tickets": "db-tickets"}},
        rows={"dir": {"Tickets": "page-tickets"}},
        schemas={"db-tickets": {"Name": {"title": {}}, "Cost": {"rich_text": {}}}},
    )
    provision.provision(board, _settings(), "root")
    assert board._schemas["db-tickets"]["Cost"] == {"rich_text": {}}, "not overruled"


@case
def two_states_on_one_column_produce_one_option():
    """Notion refuses a select that lists the same option twice."""
    settings = _settings()
    settings.status = {"failed": "Needs you", "blocked": "Needs you"}
    names = [option["name"] for option in provision.status_options(settings)]
    assert names.count("Needs you") == 1
    # Six: the two that were merged count once, and renaming a failure column
    # says nothing about the validated one, which keeps its default.
    assert len(names) == 6 and "Validated" in names

    settings.status = {"review": "Done", "done": "Done"}
    names = [option["name"] for option in provision.status_options(settings)]
    assert names.count("Done") == 1
    assert "Validated" not in names, "a board that ends at the pull request has no gesture"


@case
def the_workspace_is_written_back_into_the_configuration():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\n# keep me\ntoken = "ntn_x"\nworkspace = ""\n\n[runner]\nfetch = true\n')

    assert C.write_notion_value(path, "workspace", "abc") is True
    assert C.write_notion_value(path, "workspace", "abc") is False, "already says that"

    text = path.read_text()
    assert 'workspace = "abc"' in text
    assert "# keep me" in text, "a hand-edited file keeps its comments"
    assert "[runner]\nfetch = true" in text, "other tables are untouched"
    assert C.load(path).notion.workspace == "abc"


# -- the prompt --------------------------------------------------------------


@case
def the_prompt_reads_from_the_widest_frame_to_the_narrowest():
    text = prompt.build(
        prompt.DEFAULT,
        project="Animalink",
        title="Retirer l'entête",
        body="Le header prend trop de place.",
        repo="/home/x/animalink",
        branch="ticket/x",
        base="main",
        url="https://notion.so/x",
        brief="Ton: direct, pas d'emoji.",
        context="Je suis Salvador Cardona, développeur web.",
    )
    assert text.index("Salvador Cardona") < text.index("Ton: direct"), "the global frame comes first"
    assert text.index("Ton: direct") < text.index("# Context"), "then the project, then the mechanics"
    assert "Le header prend trop de place." in text


@case
def a_workspace_without_a_context_page_changes_nothing():
    common = dict(
        project="Animalink", title="t", body="b", repo="/r", branch="br", base="main", url="u"
    )
    bare = prompt.build(prompt.DEFAULT, **common)
    assert "# Who you are working for" not in bare
    assert prompt.build(prompt.DOCUMENT, **common, context="   ") == prompt.build(
        prompt.DOCUMENT, **common
    ), "whitespace is not a context"


# -- the role a ticket is handled by -----------------------------------------


class _AgentClient:
    def __init__(self, page: notion.Page | None, brief: str = "", broken: bool = False):
        self._page, self._brief, self._broken = page, brief, broken

    def page(self, page_id: str) -> notion.Page:
        if self._page is None:
            raise notion.NotionError("object not found")
        return self._page

    def blocks_text(self, page_id: str, depth: int = 0) -> str:
        if self._broken:
            raise notion.NotionError("object not found")
        return self._brief


def _agent_page(title: str, model: str = "") -> notion.Page:
    properties = {"Name": {"type": "title", "title": [{"plain_text": title}]}}
    if model:
        properties["Model"] = {"type": "select", "select": {"name": model}}
    return notion.Page(id="p-agent", url="", title=title, properties=properties)


@case
def an_agent_is_a_page_and_may_name_its_model():
    client = _AgentClient(_agent_page("Rédacteur", "haiku"), brief="Ton direct, pas d'emoji.")
    agent = agents.resolve(client, "p-agent")
    assert agent.name == "Rédacteur"
    assert agent.brief == "Ton direct, pas d'emoji."
    assert agent.model == "haiku"
    assert agent, "a named agent is truthy"


@case
def an_unreadable_agent_is_no_agent_rather_than_a_failed_ticket():
    assert not agents.resolve(_AgentClient(None), "p-agent").name
    # The page reads but its body does not: the role is lost, the run is not.
    partial = agents.resolve(_AgentClient(_agent_page("Rédacteur"), broken=True), "p-agent")
    assert partial.name == "Rédacteur" and partial.brief == ""
    assert not agents.Agent(), "no agent at all is falsy"


# -- the discussion on a ticket ----------------------------------------------


class _CommentClient:
    def __init__(self, texts: list[str], error: str = ""):
        self._texts, self._error = texts, error

    def comments(self, page_id: str) -> list[notion.Comment]:
        if self._error:
            raise notion.NotionError(self._error)
        return [notion.Comment(text) for text in self._texts]


def _bare_runner(client) -> Runner:
    """A Runner with its Notion replaced, and nothing else touched."""
    runner = Runner.__new__(Runner)
    runner.client = client
    runner.agent_label = "ticket-runner@laptop"
    runner.quiet = True
    runner._comments = {}
    runner._spellings = conversation.names()
    runner._me = ""          # Notion never said; the signature is all there is
    runner._identity_error = ""
    return runner


def _runner_reading(texts: list[str], error: str = "") -> tuple[Runner, list[str]]:
    runner = _bare_runner(_CommentClient(texts, error))
    ticket = type("T", (), {"page": notion.Page(id="p-ticket", url="", title="t")})()
    return runner, runner.discussion(ticket)


@case
def a_question_a_run_asked_comes_back_with_its_answer():
    _, lines = _runner_reading([
        "ticket-runner@laptop — blocked.\nThe ticket does not say which header.\n\n"
        "Session: `abc-123` — `claude --resume abc-123`\nLog: /home/x/log.jsonl",
        "Celui du dashboard, pas du site public.",
    ])
    assert lines == [
        "a previous run: blocked. The ticket does not say which header.",
        "the ticket's author: Celui du dashboard, pas du site public.",
    ], lines
    assert "Session:" not in "".join(lines), "the machinery of a past run is not context"


@case
def a_long_discussion_is_cut_from_the_oldest_end():
    _, lines = _runner_reading([f"comment number {index} " + "x" * 300 for index in range(20)])
    assert len(lines) <= 10, "at most the last ten"
    assert sum(len(line) for line in lines) <= 2000
    assert "number 19" in lines[-1], "the newest survives"
    assert "number 0" not in " ".join(lines), "the oldest is what goes"


@case
def comments_the_integration_cannot_read_are_not_a_failure():
    _, lines = _runner_reading([], error="403 API token does not have access")
    assert lines == []


def _answered(texts: list[str], error: str = "") -> bool:
    """Would a reply on that ticket put it back in the queue?"""
    runner = _bare_runner(_CommentClient(texts, error))
    ticket = type("T", (), {"page": notion.Page(id="p-ticket", url="", title="t")})()
    return runner._answered(ticket)


REPORT = "ticket-runner@laptop — blocked.\nThe ticket does not say which header."
DONE = "ticket-runner@laptop — done.\nFait."


@case
def answering_a_ticket_the_runner_handled_puts_it_back_in_the_queue():
    """The reply is the whole gesture: nothing to move on the board."""
    assert _answered([REPORT, "Celui du dashboard, pas du site public."])
    # Several rounds, and the answer is still the last word.
    assert _answered([REPORT, "réponse", DONE, "et le footer ?"])


@case
def a_ticket_wakes_only_once_per_answer():
    assert not _answered([REPORT]), "the runner having the last word is not an answer"
    assert not _answered([REPORT, "réponse", DONE]), (
        "the report the next run posts is what closes the ticket again"
    )
    assert not _answered([])


@case
def a_ticket_no_run_of_ours_ever_touched_is_left_alone():
    assert not _answered(["Une question posée avant qu'aucun run n'y touche."])
    assert not _answered(["ticket-runner@vps — done.\nFait.", "et pour le footer ?"]), (
        "a ticket handled by another host is that host's to pick up"
    )
    assert not _answered([REPORT, "réponse"], error="403 API token does not have access")


@case
def waking_looks_everywhere_but_where_a_status_already_speaks():
    """Done stays done, in review waits on a merge, validated on the runner."""
    runner = Runner.__new__(Runner)
    runner.config = _config("")
    runner._workspace = workspace.Workspace(tickets="db")
    runner.client = type("S", (), {"schema": lambda self, database: {"Status": "status"}})()
    excluded = {
        condition["status"]["does_not_equal"] for condition in runner._woken_filter()["and"]
    }
    assert excluded == {"In review", "Validated", "Done", "Ready", "In progress"}
    assert all(condition["property"] == "Status" for condition in runner._woken_filter()["and"])
    # Five names spoken, and everything else — failed, blocked, whatever the
    # board adds later — left in, because that is where an answer is expected.
    assert len(runner._woken_filter()["and"]) == 5


# -- talking in the comments -------------------------------------------------

ME = "bot-user-id"


def _said(text: str, *, by: str = "human", thread: str = "d1", ident: str = "") -> notion.Comment:
    return notion.Comment(
        text, id=ident or f"c-{abs(hash((text, thread))) % 10**6}", discussion_id=thread,
        created_by=by,
    )


def _pending(comments: list[notion.Comment], mention: str = "") -> list[conversation.Thread]:
    return conversation.waiting(
        comments, me=ME, spellings=conversation.names(mention, "Ticket Runner")
    )


@case
def comments_are_grouped_into_the_threads_they_belong_to():
    grouped = conversation.threads([
        _said("le rapport", by=ME, thread="d1"),
        _said("une remarque sans rapport", thread="d2"),
        _said("et pourquoi ?", thread="d1"),
    ])
    assert [thread.discussion for thread in grouped] == ["d1", "d2"], "in the order they appear"
    assert len(grouped[0].comments) == 2
    assert grouped[0].last.text == "et pourquoi ?"
    assert grouped[0].spoken_by(ME) and not grouped[1].spoken_by(ME)


@case
def a_comment_with_no_thread_of_its_own_is_not_lumped_with_the_others():
    """Notion answered without a discussion: two remarks are still two remarks."""
    grouped = conversation.threads([
        notion.Comment("une chose", id="c1"),
        notion.Comment("une autre", id="c2"),
    ])
    assert len(grouped) == 2


@case
def replying_under_its_report_is_how_you_talk_to_it():
    pending = _pending([
        _said("ticket-runner@laptop — done.\nFait.", by=ME),
        _said("pourquoi ce nom de branche ?"),
    ])
    assert [thread.last.text for thread in pending] == ["pourquoi ce nom de branche ?"]


@case
def naming_it_reaches_it_in_a_thread_it_never_spoke_in():
    """A remark of yours is a remark of yours — until you name it."""
    remark = [_said("il faudra penser à prévenir Marie", thread="d9")]
    assert _pending(remark) == []
    assert len(_pending([_said("@claude tu en penses quoi ?", thread="d9")])) == 1
    # The word is yours to choose, and its own name always works.
    assert len(_pending([_said("@ia une idée ?", thread="d9")], mention="@ia")) == 1
    assert len(_pending([_said("Ticket Runner, une idée ?", thread="d9")])) == 1


@case
def it_never_answers_itself():
    """The one failure mode here that would never stop on its own."""
    conversed = [
        _said("ticket-runner@laptop — done.\nFait.", by=ME),
        _said("pourquoi ?"),
        _said("parce que la branche existait déjà.", by=ME),
    ]
    assert _pending(conversed) == [], "we had the last word"
    # And without knowing who we are, nothing is answered at all: our own
    # replies would read as somebody else's questions.
    assert conversation.waiting(conversed, me="", spellings=conversation.names()) == []


@case
def a_question_it_has_already_answered_is_not_answered_twice():
    """Notion hands back a thread whose reply is still in flight."""
    ledger = conversation.Ledger(path=Path(tempfile.mkdtemp()) / "conversations.json")
    ledger.remember_thread("d1", session="s-1", comment="c-42")
    assert ledger.answered("d1") == "c-42"
    assert ledger.session_of("d1") == "s-1", "the next question resumes the same session"
    ledger.forget_session("d1")
    assert ledger.session_of("d1") == "" and ledger.answered("d1") == "c-42"


@case
def naming_it_asks_for_words_where_a_bare_answer_asks_for_work():
    """The `blocked` loop is untouched; the mention is what opts out of it."""
    report = "ticket-runner@laptop — blocked.\nQuel en-tête ?"
    assert _answered([report, "celui du dashboard."]), "a plain answer still runs the ticket"
    assert not _answered([report, "@claude pourquoi tu demandes ?"])
    assert not _answered([report, "Ticket Runner, pourquoi tu demandes ?"])


@case
def the_name_is_stripped_from_the_message_but_only_where_it_is_a_salutation():
    spellings = conversation.names("", "Ticket Runner")
    assert conversation.strip_mention("@claude pourquoi ?", spellings) == "pourquoi ?"
    assert conversation.strip_mention("@claude — pourquoi ?", spellings) == "pourquoi ?"
    kept = "demande à claude ce qu'il en pense"
    assert conversation.strip_mention(kept, spellings) == kept


class _KnownCommentClient:
    """Comments that say who wrote them, as Notion's do."""

    def __init__(self, comments: list[notion.Comment]):
        self._comments = comments

    def comments(self, page_id: str) -> list[notion.Comment]:
        return self._comments

    def me(self) -> str:
        return ME

    def my_name(self) -> str:
        return "Ticket Runner"


def _knowing(comments: list[notion.Comment]) -> Runner:
    runner = _bare_runner(_KnownCommentClient(comments))
    runner.config = _config("")
    runner._me = None  # asked of Notion, as in a real run
    runner._spellings = None
    return runner


def _ticket():
    return type("T", (), {"page": notion.Page(id="p", url="", title="t")})()


REPORT_BY_US = _said("ticket-runner@laptop — blocked.\nQuel en-tête ?", by=ME)


@case
def talking_on_a_ticket_does_not_put_it_back_in_the_queue():
    """Its own answer is not an instruction it was given — or every conversation
    would end in a run nobody asked for."""
    talked = [
        REPORT_BY_US,
        _said("@claude pourquoi tu demandes ?"),
        _said("parce que la page en a deux.", by=ME),
    ]
    assert not _knowing(talked)._answered(_ticket())
    # And the moment you actually answer the question, it runs again.
    assert _knowing([*talked, _said("celui du dashboard.")])._answered(_ticket())


@case
def an_answer_given_on_your_phone_is_still_your_answer():
    """It carries the runner's token — the runner is what posts it — and it is
    the ticket's author speaking. So it wakes the ticket exactly as the same
    word typed into Notion would, rather than reading as the runner's own last
    word and closing the very question it answers."""
    relayed = channels.answer(
        channels.Reply(channel="telegram", text="oui", ticket="p", title="t", who="Salvador")
    )
    assert conversation.is_relayed(relayed), "channels and conversation share one sentence"
    assert not conversation.ours(_said(relayed, by=ME), ME)
    assert _knowing([REPORT_BY_US, _said(relayed, by=ME)])._answered(_ticket())
    # And what the runner says in its own voice still is not an answer to itself.
    assert not _knowing([REPORT_BY_US, _said("parce que la page en a deux.", by=ME)])._answered(
        _ticket()
    )


@case
def its_own_answers_are_not_read_back_as_yours():
    runner = _knowing([
        REPORT_BY_US,
        _said("pourquoi ?"),
        _said("parce que la page en a deux.", by=ME),
        _said("celui du dashboard."),
    ])
    lines = runner.discussion(_ticket())
    assert lines == [
        "a previous run: blocked. Quel en-tête ?",
        "the ticket's author: pourquoi ?",
        "answered in the comments, by us: parce que la page en a deux.",
        "the ticket's author: celui du dashboard.",
    ], lines


@case
def a_thread_transcript_tells_its_two_voices_apart():
    thread = conversation.threads([
        _said("ticket-runner@laptop — done.", by=ME),
        _said("pourquoi ?"),
        _said("parce que.", by=ME),
        _said("et sinon ?"),
    ])[0]
    lines = conversation.transcript(thread, ME)
    assert lines == [
        "you: ticket-runner@laptop — done.",
        "them: pourquoi ?",
        "you: parce que.",
    ], lines
    assert all("et sinon" not in line for line in lines), "the message being answered is not history"


@case
def the_scan_moves_across_the_board_a_window_at_a_time():
    """One request per page, and a run that can come round every ten seconds."""
    ledger = conversation.Ledger(path=Path(tempfile.mkdtemp()) / "conversations.json")
    pages = [f"p{index}" for index in range(5)]
    assert ledger.rotate(pages, 2) == ["p0", "p1"]
    assert ledger.rotate(pages, 2) == ["p2", "p3"]
    assert ledger.rotate(pages, 2) == ["p4", "p0"], "it wraps rather than starting over"
    assert ledger.rotate(pages, 10) == pages, "a window wider than the board is the board"
    assert ledger.rotate([], 2) == []


@case
def the_pass_holds_off_until_its_own_interval_has_passed():
    ledger = conversation.Ledger(path=Path(tempfile.mkdtemp()) / "conversations.json")
    assert ledger.due(60), "a runner that has never looked is due at once"
    ledger.stamp()
    assert not ledger.due(60)
    assert ledger.due(0)


@case
def what_the_runner_remembers_survives_a_restart():
    path = Path(tempfile.mkdtemp()) / "conversations.json"
    ledger = conversation.Ledger(path=path)
    ledger.remember_page("3ca45168-0af4-80ae-9443-de0b65d9abf8")
    ledger.remember_thread("d1", session="s-1", comment="c-1")
    ledger.cursor = 3
    ledger.save()

    again = conversation.Ledger.load(path)
    assert again.known_pages() == ["3ca451680af480ae9443de0b65d9abf8"], "dashes and all"
    assert again.session_of("d1") == "s-1"
    assert again.cursor == 3
    assert conversation.Ledger.load(Path(tempfile.mkdtemp()) / "none.json").known_pages() == []


class _ThreadClient:
    """Pages with comments on them, and nothing else."""

    def __init__(self, pages: dict[str, list[notion.Comment]]):
        self.pages = pages
        self.asked: list[str] = []

    def comments(self, page_id: str) -> list[notion.Comment]:
        self.asked.append(page_id)
        if page_id not in self.pages:
            raise notion.NotionError("404 could not find block")
        return self.pages[page_id]

    def my_name(self) -> str:
        return "Ticket Runner"


def _talking(pages: dict[str, list[notion.Comment]], *, claimed: set[str] = frozenset(), scan=20):
    runner = _bare_runner(_ThreadClient(pages))
    runner.config = _config("")
    runner.config.runner.reply_scan = scan
    runner._spellings = None  # resolved from the client, as in a real run
    runner._me = ME
    runner._claimed = set(claimed)
    runner._ledger_lock = threading.Lock()
    runner._ledger = conversation.Ledger(path=Path(tempfile.mkdtemp()) / "conversations.json")
    for page in pages:
        runner._ledger.remember_page(page)
    return runner


REPLIED_TO = [
    _said("ticket-runner@laptop — done.\nFait.", by=ME),
    _said("pourquoi ce nom de branche ?"),
]


@case
def a_ticket_about_to_run_is_left_to_the_run_that_will_read_it():
    """The comment is already going into its prompt; two answers would be one
    too many, and one of them would be the runner talking over itself."""
    runner = _talking({"pone": REPLIED_TO, "ptwo": REPLIED_TO}, claimed={"ptwo"})
    assert [page for page, _ in runner._pending(ME)] == ["pone"]


@case
def a_pass_answers_one_thread_per_page_and_stops_at_five():
    two = [
        _said("ticket-runner@laptop — done.", by=ME, thread="d1"),
        _said("pourquoi ?", thread="d1"),
        _said("@claude et ici ?", thread="d2"),
    ]
    runner = _talking({"pone": two})
    pending = runner._pending(ME)
    assert len(pending) == 1 and pending[0][1].discussion == "d1", "the next pass takes the other"

    crowd = {f"page{index}": REPLIED_TO for index in range(9)}
    assert len(_talking(crowd)._pending(ME)) == conversation.ANSWERS


@case
def a_page_that_cannot_be_read_costs_that_page_and_nothing_else():
    runner = _talking({"ptwo": REPLIED_TO})
    runner._ledger.remember_page("pgone")
    assert [page for page, _ in runner._pending(ME)] == ["ptwo"]


@case
def the_pages_this_run_has_already_read_cost_no_second_request():
    runner = _talking({"pone": REPLIED_TO})
    runner._comments["pone"] = REPLIED_TO  # as `woken` leaves it
    assert len(runner._pending(ME)) == 1
    assert runner.client.asked == [], "nothing was asked of Notion twice"


class _TalkingClient(_ThreadClient):
    """A page, its discussion, and what got written back into it."""

    def __init__(self, pages, body: str = "Supprimer l'entête."):
        super().__init__(pages)
        self._body = body
        self.posted: list[tuple[str, str, str]] = []

    def me(self) -> str:
        return ME

    def page(self, page_id: str) -> notion.Page:
        return notion.Page(id=page_id, url=f"https://notion.so/{page_id}", title="Un ticket")

    def blocks_text(self, block_id: str, depth: int = 0) -> str:
        return self._body

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.posted.append((page_id, text, discussion_id))

    def update(self, database_id: str, page_id: str, values: dict) -> None:
        raise AssertionError("a conversation moves nothing on the board")


@contextmanager
def _no_session(answer: str = "Parce que la branche d'hier était déjà en revue.", ok=True):
    """Claude, replaced by its answer. Records how it was asked.

    `ok` may be a list, read one entry per call: that is how a session that
    cannot be resumed is told from one that has nothing to say.
    """
    calls: list[dict] = []
    verdicts = list(ok) if isinstance(ok, (list, tuple)) else None

    def fake_run(prompt_text, **kwargs):
        calls.append({"prompt": prompt_text, **kwargs})
        good = verdicts.pop(0) if verdicts else (ok if verdicts is None else True)
        return session.Outcome(
            ok=good, blocked=False, session_id=kwargs.get("session_id", "s-1"),
            summary="", log=Path("/tmp/none.jsonl"), answer=answer if good else "",
            error="" if good else "claude exited with code 1", seconds=12.0, cost_usd=0.01,
        )

    original = session.run
    session.run = fake_run
    try:
        yield calls
    finally:
        session.run = original


@case
def answering_a_comment_writes_in_its_thread_and_nowhere_else():
    with _state_home(), _no_session() as calls:
        runner = _talking({"pone": REPLIED_TO})
        runner.client = _TalkingClient({"pone": REPLIED_TO})
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db", context="Je suis Salvador.")
        answered = runner.converse()

    assert len(answered) == 1 and answered[0]["status"] == "answered"
    page, text, discussion = runner.client.posted[0]
    assert (page, discussion) == ("pone", "d1"), "under the question, not at the bottom"
    assert text == "Parce que la branche d'hier était déjà en revue."

    asked = calls[0]
    assert asked["permission_mode"] == "plan", "it talks; it does not work"
    assert asked["resume"] is False and asked["timeout_minutes"] == 10
    assert "pourquoi ce nom de branche ?" in asked["prompt"]
    assert "Supprimer l'entête." in asked["prompt"], "it knows the ticket it is under"
    assert "Je suis Salvador." in asked["prompt"], "and who it is answering"


@case
def a_second_question_lands_in_the_same_conversation():
    with _state_home(), _no_session() as calls:
        runner = _talking({"pone": REPLIED_TO})
        runner.client = _TalkingClient({"pone": REPLIED_TO})
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db")
        runner.converse()

        again = [*REPLIED_TO, _said("et le footer ?", ident="c-later")]
        runner.client.pages["pone"] = again
        runner._comments.clear()
        runner._ledger.at = 0.0  # the interval, not the point of this test
        runner.converse()

    assert len(calls) == 2
    assert calls[1]["resume"] is True and calls[1]["session_id"] == calls[0]["session_id"]
    assert calls[1]["prompt"].strip().endswith("et le footer ?")
    assert "Supprimer l" not in calls[1]["prompt"], "a resumed session has the frame already"


@case
def a_session_that_says_nothing_is_still_answered_for():
    """Silence in a thread reads as being ignored, which is worse than a failure."""
    with _state_home(), _no_session(ok=False) as calls:
        runner = _talking({"pone": REPLIED_TO})
        runner.client = _TalkingClient({"pone": REPLIED_TO})
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db")
        runner.converse()

    assert len(calls) == 1, "nothing to resume, so nothing to retry"
    assert "could not answer" in runner.client.posted[0][1]
    assert "Log:" in runner.client.posted[0][1], "and where to go and look"


@case
def a_conversation_whose_session_is_gone_starts_a_new_one():
    """The transcript was pruned, or the machine changed. Notion still has the
    thread, which is enough to carry on from."""
    with _state_home(), _no_session(ok=[True, False, True]) as calls:
        runner = _talking({"pone": REPLIED_TO})
        runner.client = _TalkingClient({"pone": REPLIED_TO})
        runner.dry_run = False
        runner._workspace = workspace.Workspace(tickets="db")
        runner.converse()

        runner.client.pages["pone"] = [*REPLIED_TO, _said("et le footer ?", ident="c-later")]
        runner._comments.clear()
        runner._ledger.at = 0.0
        runner.converse()

    assert [call["resume"] for call in calls] == [False, True, False]
    assert calls[2]["session_id"] != calls[1]["session_id"]
    assert "Supprimer l" in calls[2]["prompt"], "a fresh session is told everything again"
    assert len(runner.client.posted) == 2 and "could not answer" not in runner.client.posted[1][1]


@case
def a_pass_that_is_turned_off_or_too_soon_asks_notion_nothing():
    with _state_home(), _no_session() as calls:
        runner = _talking({"pone": REPLIED_TO})
        runner.client = _TalkingClient({"pone": REPLIED_TO})
        runner.dry_run = False
        runner.config.runner.reply = False
        assert runner.converse() == []

        runner.config.runner.reply = True
        runner._ledger.stamp()
        assert runner.converse() == [], "the interval has not passed"
        assert runner.client.asked == [] and calls == []


@case
def a_conversation_prompt_says_what_it_is_not_allowed_to_do():
    text = prompt.conversation(
        prompt.CONVERSATION,
        project="Animalink", title="t", body="b", where="Repository: /r", url="u",
        message="pourquoi ce nom ?",
        thread=["them: pourquoi ?"],
        context="Je suis Salvador.",
        brief="Ton: direct.",
        agent_name="Rédacteur",
        agent_brief="Deux angles.",
        comments=["a previous run: done. fait"],
    )
    assert "talking, not working" in text
    order = [text.index(mark) for mark in (
        "b",                        # the ticket itself
        "already been said",        # then what was said about it
        "Je suis Salvador.",        # then the widest frame
        "Ton: direct.",             # then the project
        "Deux angles.",             # then the role
        "# Context",                # then the mechanics
        "This thread so far",       # then the conversation being had
        "pourquoi ce nom ?",        # and last, the message to answer
    )]
    assert order == sorted(order), order
    # A resumed session is sent the message and not the whole frame again.
    assert runner_module._message_of(text) == "pourquoi ce nom ?"


@case
def a_ticket_without_a_project_still_reads_as_a_sentence():
    text = prompt.conversation(
        prompt.CONVERSATION,
        project="", title="t", body="", where="Working directory: /tmp/x", url="u",
        message="et alors ?",
    )
    assert "that belongs to no project" in text
    assert "This thread so far" not in text and "# Your role" not in text
    assert "everything is in the title" in text


@case
def an_answer_too_long_for_a_comment_is_cut_where_it_breathes():
    assert conversation.trim("court") == "court"
    long = ("Une phrase. " * 200).strip()
    cut = conversation.trim(long, limit=200)
    assert len(cut) < 400 and cut.endswith("ask for it in pieces.")
    assert cut.split("[…]")[0].rstrip().endswith("."), "cut on a sentence, not mid-word"


@case
def the_role_sits_between_the_project_and_the_mechanics():
    text = prompt.build(
        prompt.DEFAULT,
        project="Animalink", title="t", body="b", repo="/r", branch="br", base="main", url="u",
        context="Je suis Salvador.",
        brief="Ton: direct.",
        agent_name="Rédacteur",
        agent_brief="Deux ou trois angles, toujours.",
        comments=["the ticket's author: plutôt court."],
    )
    order = [text.index(mark) for mark in (
        "b",                        # the ticket itself
        "already been said",        # then what was said about it
        "Je suis Salvador.",        # then the widest frame
        "Ton: direct.",             # then the project
        "Deux ou trois angles",     # then the role
        "# Context",                # then the mechanics
    )]
    assert order == sorted(order), order
    assert "# Your role — Rédacteur" in text


@case
def a_ticket_with_no_agent_and_no_comments_reads_as_before():
    common = dict(
        project="Animalink", title="t", body="b", repo="/r", branch="br", base="main", url="u"
    )
    bare = prompt.build(prompt.DEFAULT, **common)
    assert "# Your role" not in bare and "already been said" not in bare
    assert prompt.build(prompt.DEFAULT, **common, comments=[], agent_brief="  ") == bare


# -- session outcome ---------------------------------------------------------


@case
def a_verdict_is_read_from_the_last_result_line():
    assert session._verdict("blah\nRESULT: ok — removed the header") == "ok"
    assert session._verdict("**RESULT: blocked — which page?**") == "blocked"
    assert session._verdict("nothing of the sort") == ""
    # The last one wins: an agent may quote the format before using it.
    assert session._verdict("RESULT: blocked — x\nRESULT: ok — y") == "ok"


@case
def a_summary_drops_the_verdict_it_repeats():
    assert session._summary("x\nRESULT: ok — removed the header") == "removed the header"
    assert session._summary("**RESULT: blocked — which page?**") == "which page?"
    assert session._summary("no verdict here") == "no verdict here"


@case
def project_keys_match_what_claude_code_writes_on_disk():
    """Observed against real ~/.claude/projects folders."""
    assert session.project_key(Path("/home/salva/workspace/labo/trader-ia")) == (
        "-home-salva-workspace-labo-trader-ia"
    )
    assert session.project_key(
        Path("/home/salva/.local/state/ticket-runner/worktrees/trader-ia-3ca45168")
    ) == "-home-salva--local-state-ticket-runner-worktrees-trader-ia-3ca45168"


@case
def a_remote_link_carries_its_host():
    """Once the runner is on a server, the session is there too.

    A link with a host resolves to an ssh command instead of a local claude,
    which is what keeps the Session column clickable from a laptop.
    """
    from urllib.parse import parse_qs, urlparse

    link = session.deep_link("abc-123", "/srv/work/app", "salva@vps")
    parsed = urlparse(link)
    query = parse_qs(parsed.query)
    assert query["host"] == ["salva@vps"]
    assert query["cwd"] == ["/srv/work/app"]
    # Without a host the link stays purely local.
    assert "host=" not in session.deep_link("abc-123", "/srv/work/app")


@case
def a_deep_link_survives_a_round_trip():
    from urllib.parse import parse_qs, urlparse

    link = session.deep_link("0486a9fd-44f6-4fff-9dee-9e58bc4062ba", "/home/me/my work")
    parsed = urlparse(link)
    assert parsed.scheme == session.SCHEME
    assert parsed.netloc == "session"
    assert parsed.path.strip("/") == "0486a9fd-44f6-4fff-9dee-9e58bc4062ba"
    assert parse_qs(parsed.query)["cwd"][0] == "/home/me/my work"
    assert session.deep_link("abc") == "ticket-runner://session/abc"


# -- Notion encoding ---------------------------------------------------------


@case
def values_are_encoded_for_the_type_the_database_declares():
    assert notion._encode("status", "Done") == {"status": {"name": "Done"}}
    assert notion._encode("select", "Done") == {"select": {"name": "Done"}}
    assert notion._encode("url", "https://x") == {"url": "https://x"}
    assert notion._encode("number", 1.5) == {"number": 1.5}
    # A property the database does not have is skipped, not guessed at.
    assert notion._encode(None, "Done") is None
    assert notion._encode("status", None) is None


@case
def long_text_is_split_below_notions_limit():
    chunks = notion._rich_text("a" * 5000)
    assert len(chunks) == 3
    assert all(len(chunk["text"]["content"]) <= 1900 for chunk in chunks)
    assert notion._rich_text("") == [{"type": "text", "text": {"content": ""}}]


@case
def blocks_become_readable_text_for_the_prompt():
    todo = {"type": "to_do", "to_do": {"checked": True, "rich_text": [{"plain_text": "fait"}]}}
    assert notion._block_text(todo, 0) == "- [x] fait"
    heading = {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Titre"}]}}
    assert notion._block_text(heading, 0) == "## Titre"
    divider = {"type": "divider", "divider": {}}
    assert notion._block_text(divider, 0) == "---"


@case
def properties_are_read_back_as_plain_python():
    page = notion.Page(
        id="x", url="u", title="t",
        properties={
            "Status": {"type": "status", "status": {"name": "Done"}},
            "Empty": {"type": "status", "status": None},
            "Cost": {"type": "number", "number": 0.42},
            "Project": {"type": "relation", "relation": [{"id": "abc"}]},
            "Session": {"type": "url", "url": "ticket-runner://session/x"},
        },
    )
    assert notion.read(page, "Status") == "Done"
    assert notion.read(page, "Empty") is None
    assert notion.read(page, "Cost") == 0.42
    assert notion.read(page, "Project") == ["abc"]
    assert notion.read(page, "Session") == "ticket-runner://session/x"
    assert notion.read(page, "Absent") is None


# -- markdown to Notion blocks -----------------------------------------------


@case
def markdown_keeps_its_shape_as_notion_blocks():
    blocks = markdown.to_blocks(
        "# Plan\n\nUn **paragraphe**.\n\n## Étapes\n- point\n- [x] fait\n1. numéroté\n\n"
        "> citation\n\n---\n\n```python\nprint(1)\n```\n"
    )
    assert [block["type"] for block in blocks] == [
        "heading_1", "paragraph", "heading_2", "bulleted_list_item",
        "to_do", "numbered_list_item", "quote", "divider", "code",
    ]
    assert blocks[4]["to_do"]["checked"] is True
    assert blocks[8]["code"]["language"] == "python"


@case
def an_unknown_code_language_does_not_break_the_publish():
    """Notion rejects a language it does not know; we fall back rather than fail."""
    blocks = markdown.to_blocks("```klingon\nnuqneH\n```")
    assert blocks[0]["code"]["language"] == "plain text"
    blocks = markdown.to_blocks("```sh\nls\n```")
    assert blocks[0]["code"]["language"] == "shell", "aliases resolve"


@case
def inline_formatting_becomes_annotations_and_links():
    parts = markdown.inline("Un **gras**, un [lien](https://x.fr), et `du code`")
    assert parts[1]["annotations"]["bold"] is True
    assert parts[3]["text"]["link"] == {"url": "https://x.fr"}
    assert parts[5]["annotations"]["code"] is True
    # Plain text carries no annotations object at all.
    assert "annotations" not in parts[0]


@case
def anything_unrecognised_still_reaches_the_page():
    blocks = markdown.to_blocks("| a | b |\n| - | - |\n| 1 | 2 |")
    assert all(block["type"] == "paragraph" for block in blocks)
    assert len(blocks) == 3, "a table degrades to rows, it does not vanish"


@case
def blocks_are_chunked_below_notions_append_limit():
    blocks = markdown.to_blocks("\n\n".join(f"ligne {index}" for index in range(250)))
    batches = markdown.chunked(blocks)
    assert len(batches) == 3
    assert all(len(batch) <= 100 for batch in batches)
    assert sum(len(batch) for batch in batches) == len(blocks)
    assert markdown.chunked([]) == [[]]


# -- scheduling --------------------------------------------------------------


@case
def a_bare_date_means_the_start_of_that_day_here():
    """Not midnight UTC: a ticket dated "30 August" starts on the 30th, locally."""
    from datetime import datetime

    from ticket_runner.runner import scheduled_for

    moment = scheduled_for("2026-08-30")
    assert moment is not None and moment.tzinfo is not None
    assert (moment.year, moment.month, moment.day, moment.hour) == (2026, 8, 30, 0)
    assert moment.utcoffset() == datetime.now().astimezone().utcoffset()


@case
def a_date_with_a_time_keeps_its_offset():
    from ticket_runner.runner import scheduled_for

    moment = scheduled_for("2026-08-30T14:30:00.000+02:00")
    assert moment is not None
    assert (moment.hour, moment.minute) == (14, 30)
    assert moment.utcoffset().total_seconds() == 7200


@case
def an_unreadable_date_never_holds_a_ticket_back():
    """A value the runner cannot parse must not silently freeze a ticket."""
    from ticket_runner.runner import scheduled_for

    assert scheduled_for(None) is None
    assert scheduled_for("") is None
    assert scheduled_for("bientôt") is None


@case
def notion_truncates_a_datetime_to_the_minute():
    """Not our doing, but it decides how precise scheduling can be.

    Sending 14:48:27 stores 14:48:00, so a ticket fires at the top of the minute
    it names. Worth pinning: a future change here would look like the runner
    firing early.
    """
    from ticket_runner.runner import scheduled_for

    stored = scheduled_for("2026-08-28T14:48:00.000+02:00")
    assert stored is not None and (stored.hour, stored.minute, stored.second) == (14, 48, 0)


@case
def a_date_range_schedules_on_its_end():
    """Notion dates may be ranges; the runner reads the moment work is due."""
    page = notion.Page(
        id="x", url="u", title="t",
        properties={
            "Due": {"type": "date", "date": {"start": "2026-08-30", "end": "2026-09-02"}},
            "Single": {"type": "date", "date": {"start": "2026-08-30", "end": None}},
            "Empty": {"type": "date", "date": None},
        },
    )
    assert notion.read(page, "Due") == "2026-09-02"
    assert notion.read(page, "Single") == "2026-08-30"
    assert notion.read(page, "Empty") is None


# -- staying up to date ------------------------------------------------------


@contextmanager
def _state_home():
    """A throwaway XDG_STATE_HOME, for what the runner keeps between two runs."""
    previous = os.environ.get("XDG_STATE_HOME")
    os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()
    try:
        yield Path(os.environ["XDG_STATE_HOME"]) / "ticket-runner"
    finally:
        if previous is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = previous


@case
def an_update_needs_both_sides_to_be_known():
    """A check that could not reach the remote must not look like a new version.

    Everything else here fails quietly, so `stale` is the one place where a
    missing answer would otherwise turn into a reinstall.
    """
    assert update.Status(current="a" * 40, latest="b" * 40).stale
    assert not update.Status(current="a" * 40, latest="a" * 40).stale
    assert not update.Status(current="a" * 40).stale
    assert not update.Status(reason="git fetch: could not resolve host").stale
    assert not update.Status().stale


@case
def the_check_is_hourly_rather_than_once_per_run():
    """At a ten-second cadence the difference is 360 git fetches an hour."""
    with _state_home():
        assert update.due(3600), "an installation never checked is due at once"
        update.remember(update.Status(current="a" * 40, latest="a" * 40))
        assert not update.due(3600), "and not again before the interval is out"
        assert update.due(0)
        assert update.last_check() > 0


@case
def a_stamp_that_cannot_be_read_makes_the_check_due():
    with _state_home() as state_home:
        state_home.mkdir(parents=True)
        (state_home / "update.json").write_text("half a line of jso")
        assert update.last_check() == 0.0
        assert update.due(3600)


@case
def a_copy_is_told_apart_from_a_clone_before_anything_is_fetched():
    """An install made with TR_SRC has no remote: a reason, not a failure."""
    status = update._look(Path(tempfile.mkdtemp()))
    assert not status.stale and "copy" in status.reason


# -- runner ------------------------------------------------------------------


@case
def a_template_only_body_counts_as_blank():
    """A Notion template fills a new page with empty headings.

    They are not blank text, so without this they would travel into the prompt
    as noise and stop the "everything is in the title" fallback from firing.
    """
    from ticket_runner.runner import is_blank

    assert is_blank("## Ce qu'il faut faire\n## Où\n## Comment on saura\n")
    assert is_blank("")
    assert is_blank("   \n\n---\n")
    assert not is_blank("## Ce qu'il faut faire\nRetirer le header.")
    assert not is_blank("Une seule ligne de texte")


# -- a merged pull request closes its ticket ---------------------------------


class _BoardClient:
    """A tickets database that answers queries and remembers what was written."""

    def __init__(self, pages: list[notion.Page], options: list[str] | None = None):
        self._pages = pages
        self._options = options if options is not None else ["In review", "Validated", "Done"]
        self.written: list[tuple[str, dict]] = []
        self.comments_written: list[str] = []
        self.queried: list[object] = []

    def schema(self, database_id: str) -> dict[str, str]:
        return {"Status": "status", "Pull Request": "url"}

    def options(self, database_id: str, name: str) -> list[str]:
        return list(self._options)

    def me(self) -> str:
        return "u-runner"

    def comments(self, page_id: str) -> list[notion.Comment]:
        return []

    def blocks_text(self, block_id: str, depth: int = 0) -> str:
        return "Le post d'annonce, écrit la semaine dernière et relu depuis."

    def query(self, database_id: str, filter_=None) -> list[notion.Page]:
        self.queried.append(filter_)
        wanted = (filter_ or {}).get("status", {}).get("equals")
        return [page for page in self._pages if notion.read(page, "Status") == wanted]

    def update(self, database_id: str, page_id: str, values: dict) -> None:
        self.written.append((page_id, values))

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.comments_written.append(text)


def _reviewed(page_id: str, status: str, pull_request: str | None) -> notion.Page:
    properties = {"Status": {"type": "status", "status": {"name": status}}}
    if pull_request is not None:
        properties["Pull Request"] = {"type": "url", "url": pull_request}
    return notion.Page(id=page_id, url="", title=page_id, properties=properties)


def _board_runner(pages: list[notion.Page], status: dict[str, str], options=None) -> Runner:
    """A Runner with nothing underneath it but a fake board."""
    runner = Runner.__new__(Runner)
    runner.client = _BoardClient(pages, options)
    runner.config = C.Config(
        notion=C.Notion(properties=dict(C._DEFAULT_PROPERTIES), status=status),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere"),
        notify=C.Notify(desktop=False),
    )
    runner._workspace = workspace.Workspace(tickets="db")
    runner.agent_label = "ticket-runner@laptop"
    runner.quiet = True
    runner.dry_run = False
    runner._claimed = set()
    runner._comments = {}
    runner._spellings = conversation.names()
    runner._me = ""
    runner._identity_error = ""
    runner._ledger_lock = threading.Lock()
    runner._ledger = conversation.Ledger(
        path=Path(tempfile.mkdtemp()) / "conversations.json"
    )
    return runner


@contextmanager
def _github(states: dict[str, str], merge=None):
    """`gh`, replaced by what it would have said."""
    from ticket_runner import git as git_module

    asked, original = git_module.pull_request_state, git_module.merge_pull_request
    git_module.pull_request_state = lambda url: states.get(url, "")
    if merge is not None:
        git_module.merge_pull_request = merge
    try:
        yield
    finally:
        git_module.pull_request_state = asked
        git_module.merge_pull_request = original


def _closing(pages: list[notion.Page], states: dict[str, str], status: dict[str, str]):
    """Run `close_merged` against a fake board and a fake GitHub."""
    runner = _board_runner(pages, status)
    with _github(states):
        return runner.client, runner.close_merged()


@case
def a_merged_pull_request_moves_its_ticket_to_done():
    client, closed = _closing(
        [
            _reviewed("p-merged", "In review", "https://github.com/x/y/pull/1"),
            _reviewed("p-open", "In review", "https://github.com/x/y/pull/2"),
            _reviewed("p-ready", "Not started", None),
        ],
        {"https://github.com/x/y/pull/1": "MERGED", "https://github.com/x/y/pull/2": "OPEN"},
        {"review": "In review", "done": "Done"},
    )
    assert closed == 1
    assert client.written == [("p-merged", {"Status": "Done"})]
    assert "merged" in client.comments_written[0]


@case
def a_ticket_is_never_closed_on_an_answer_github_did_not_give():
    """No pull request, or no `gh` to ask: the ticket stays where it is."""
    client, closed = _closing(
        [
            _reviewed("p-nothing", "In review", None),
            _reviewed("p-empty", "In review", ""),
            _reviewed("p-unreachable", "In review", "https://github.com/x/y/pull/3"),
        ],
        {},  # as when gh is missing or not authenticated
        {"review": "In review", "done": "Done"},
    )
    assert closed == 0 and client.written == []


@case
def a_board_without_a_review_column_is_never_even_queried():
    """`review` following `done` means there is nowhere for a ticket to wait."""
    client, closed = _closing(
        [_reviewed("p-done", "Done", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "MERGED"},
        {"done": "Done"},
    )
    assert closed == 0 and client.written == []



# -- validating is the gesture the runner acts on ----------------------------


def _validating(
    pages: list[notion.Page],
    states: dict[str, str],
    status: dict[str, str],
    *,
    options=None,
    refuses: str = "",
):
    """Run `deliver` against a fake board, a fake GitHub, and no session."""
    from ticket_runner import git as git_module

    runner = _board_runner(pages, status, options)
    merges: list[tuple[str, str]] = []
    published: list[str] = []

    def merge(url: str, method: str = "squash") -> str:
        merges.append((url, method))
        if refuses:
            raise git_module.GitError(refuses)
        return "merged"

    # Publishing runs a Claude session, which is the one thing these tests do
    # not do: what is checked here is that a ticket with no pull request goes
    # down that road at all.
    runner._publish = lambda ticket, project: published.append(ticket.id)
    with _github(states, merge=merge):
        return runner.client, merges, published, runner.deliver()


@case
def validating_a_ticket_is_what_merges_its_pull_request():
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
    )
    assert merges == [("https://github.com/x/y/pull/1", "squash")]
    assert client.written == [("p-validated", {"Status": "Done"})]
    assert results and results[0]["status"] == "done"
    assert "validated" in client.comments_written[0]


@case
def a_pull_request_already_merged_only_moves_its_ticket():
    """Merged by hand between two runs: nothing to merge, still done."""
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "MERGED"},
        {},
    )
    assert merges == []
    assert client.written == [("p-validated", {"Status": "Done"})]
    assert "already been merged" in client.comments_written[0]


@case
def a_merge_github_refuses_leaves_the_ticket_blocked_and_says_why():
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
        refuses="gh pr merge: Pull request is not mergeable: the merge commit cannot be cleanly created",
    )
    assert len(merges) == 1, "refused once, not retried in the same pass"
    assert client.written == [("p-validated", {"Status": "Blocked"})]
    assert "not mergeable" in client.comments_written[0]
    assert results and results[0]["status"] == "blocked"


@case
def a_pull_request_closed_rather_than_merged_is_a_question_not_a_merge():
    client, merges, _, _ = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "CLOSED"},
        {},
    )
    assert merges == []
    assert client.written == [("p-validated", {"Status": "Blocked"})]


@case
def nothing_is_merged_on_an_answer_github_did_not_give():
    """`gh` missing or unauthenticated: the ticket waits for the next pass."""
    client, merges, _, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {},
        {},
    )
    assert merges == [] and client.written == [] and results == []


@case
def a_validated_ticket_with_no_pull_request_is_published_rather_than_merged():
    """The Instagram post, the email, the announcement: work with no branch."""
    client, merges, published, _ = _validating(
        [
            _reviewed("p-post", "Validated", None),
            _reviewed("p-empty", "Validated", ""),
        ],
        {},
        {},
    )
    assert merges == [] and client.written == []
    assert published == ["ppost", "pempty"]  # `Ticket.id` drops the dashes


@case
def a_board_without_a_validated_column_is_never_even_queried():
    """No such option on the board, no such gesture: not even a query."""
    client, merges, published, results = _validating(
        [_reviewed("p-validated", "Validated", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {},
        options=["Ready", "In progress", "In review", "Done"],
    )
    assert results == [] and merges == [] and published == []
    assert client.queried == [], "a board with no column is not read at all"


@case
def a_file_that_names_its_columns_without_validated_asked_for_no_gesture():
    """Most often a file written before the column existed. It stays as it was."""
    settings = C.Notion(status={"review": "In review", "done": "Done"})
    assert settings.state("validated") == settings.state("review") == "In review"

    # But renaming some other column says nothing about this one: a file that
    # only translates "Ready" has not asked for the gesture to go away.
    settings = C.Notion(status={"ready": "À faire"})
    assert settings.state("validated") == "Validated"
    assert settings.state("ready") == "À faire"

    client, merges, published, results = _validating(
        [_reviewed("p-review", "In review", "https://github.com/x/y/pull/1")],
        {"https://github.com/x/y/pull/1": "OPEN"},
        {"review": "In review", "done": "Done"},
    )
    assert results == [] and merges == [] and published == []
    assert client.queried == []

    # And a file that names nothing at all gets the whole board, gesture included.
    assert C.Notion().state("validated") == "Validated"


@case
def a_validated_ticket_on_a_repository_with_no_pull_request_asks_rather_than_publishes():
    """Nothing to merge, and nothing on the page to publish: a question."""
    runner = _board_runner([_reviewed("p-code", "Validated", None)], {})
    runner.resolver = None
    runner._project_of = lambda ticket: projects.Project(name="Site", path=Path("/repo"))
    results = runner.deliver()
    assert runner.client.written == [("p-code", {"Status": "Blocked"})]
    assert "no pull request to merge" in runner.client.comments_written[0]
    assert results and results[0]["status"] == "blocked"


@case
def a_dry_run_says_what_it_would_merge_and_merges_nothing():
    runner = _board_runner(
        [
            _reviewed("p-pr", "Validated", "https://github.com/x/y/pull/1"),
            _reviewed("p-post", "Validated", None),
        ],
        {},
    )
    runner.dry_run = True
    said: list[str] = []
    runner.quiet = False
    runner.say = said.append
    with _github({"https://github.com/x/y/pull/1": "OPEN"}, merge=_never_merged):
        results = runner.deliver()
    assert runner.client.written == [], "a dry run writes nothing"
    assert [done["status"] for done in results] == ["dry-run", "dry-run"]
    assert any("would merge https://github.com/x/y/pull/1" in line for line in said)
    assert any("would publish what it holds" in line for line in said)


def _never_merged(url: str, method: str = "squash") -> str:
    raise AssertionError("a dry run never merges anything")


@case
def a_publication_a_crash_interrupted_comes_back_as_a_question():
    """Put back in ready it would be redone; the post may already be out."""
    claimed = notion.Page(
        id="ppost",  # `Ticket.id` drops the dashes, and a claim is filed under it
        url="",
        title="Le post",
        properties={
            "Status": {"type": "status", "status": {"name": "In progress"}},
            "Runner": {"type": "rich_text", "rich_text": [{"plain_text": "ticket-runner@laptop"}]},
        },
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )
    runner = _board_runner([claimed], {})
    with _state_home():
        state.claim("ppost", "Validated")
        recovered = runner.sweep()
        assert state.claims() == {}, "the note is dropped once it has been read"
    assert recovered == 1
    assert runner.client.written == [("ppost", {"Status": "Blocked"})]
    said = runner.client.comments_written[0]
    assert "may have gone out" in said and "“Validated”" in said


@case
def a_ticket_claimed_from_ready_is_still_put_back_in_the_queue():
    claimed = notion.Page(
        id="p-work",
        url="",
        title="Le header",
        properties={
            "Status": {"type": "status", "status": {"name": "In progress"}},
            "Runner": {"type": "rich_text", "rich_text": [{"plain_text": "ticket-runner@laptop"}]},
        },
        raw={"last_edited_time": "2020-01-01T00:00:00.000+00:00"},
    )
    runner = _board_runner([claimed], {})
    with _state_home():
        assert runner.sweep() == 1
    assert runner.client.written == [("p-work", {"Status": "Ready"})]
    assert "picked up again" in runner.client.comments_written[0]


@case
def publishing_hands_the_page_as_it_stands_to_a_session_and_then_closes_it():
    """The whole road for a ticket with no branch: claim, publish, done."""
    runner = _board_runner([_reviewed("p-post", "Validated", None)], {})
    runner.config.runner.progress = False
    runner.config.runner.attach_sessions = False
    runner.resolver = None  # a ticket with no project never reaches it

    asked: list[str] = []

    def fake_run(prompt_text, **kwargs):
        asked.append(prompt_text)
        return session.Outcome(
            ok=True, blocked=False, session_id=kwargs.get("session_id", "s-1"),
            summary="publié sur le compte Instagram", log=Path("/tmp/none.jsonl"),
            seconds=90.0, turns=4,
        )

    original = runner_module.session.run
    runner_module.session.run = fake_run
    try:
        with _state_home():
            results = runner.deliver()
    finally:
        runner_module.session.run = original

    # Claimed first, exactly as a run claims a ticket, and only then closed:
    # a second machine watching the board must not post the same thing twice.
    assert [values["Status"] for _, values in runner.client.written] == [
        "In progress", "Done",
    ]
    assert results and results[0]["kind"] == "delivery"

    prompt_text = asked[0]
    assert "Le post d'annonce" in prompt_text, "the page as it stands is what goes out"
    assert "publishing, not producing" in prompt_text
    assert "publié sur le compte Instagram" in runner.client.comments_written[0]


# -- the live report ---------------------------------------------------------


def _assistant(*blocks) -> dict:
    return {"type": "assistant", "message": {"content": list(blocks)}}


def _tool(name: str, **payload) -> dict:
    return {"type": "tool_use", "name": name, "input": payload}


@case
def an_event_becomes_the_line_a_human_would_write():
    steps = progress.describe(
        _assistant(
            {"type": "text", "text": "I will read the config.\n\nThen the tests."},
            _tool("Bash", command="npm test -- --watch=false"),
            _tool("Read", file_path="src/app/config.ts"),
        )
    )
    assert [step.line for step in steps] == [
        # What was said keeps its own shape; what was done is a line.
        "I will read the config.\nThen the tests.",
        "Bash · npm test -- --watch=false",
        "Read · src/app/config.ts",
    ]
    assert [step.said for step in steps] == [True, False, False]


@case
def what_the_agent_said_is_written_whole_and_not_cut_to_a_bullet():
    """A paragraph of reasoning is the part a human reads; it goes down entire."""
    said = "Le ticket parle de la documentation. " * 20  # far past a bullet's 200
    steps = progress.describe(_assistant({"type": "text", "text": said}))
    assert steps[0].label == said.strip() and "…" not in steps[0].label

    live, client, clock = _reporting()
    live.add(steps[0])
    live.add(progress.Step("Bash", "npm test"))
    clock.now += 11
    live.flush()
    # Prose is a paragraph, a tool call is a bullet, and the two are kept apart.
    assert client.kinds == ["paragraph", "bulleted_list_item"], "no rule before the first word"
    assert client.blocks[0] == said.strip()

    live.add(steps[0])
    clock.now += 11
    live.flush()
    assert client.kinds[-2:] == ["divider", "paragraph"]
    # The board column shows a line, whatever the page shows.
    assert len(client.properties[-1]) <= progress.LINE


@case
def a_turn_too_long_for_a_ticket_page_is_the_only_one_cut():
    steps = progress.describe(_assistant({"type": "text", "text": "x" * (progress.SAID + 500)}))
    assert len(steps[0].label) == progress.SAID and steps[0].label.endswith("…")

    live, client, clock = _reporting()
    live.add(steps[0])
    clock.now += 11
    live.flush()
    # Notion caps a piece of rich text, not a block: the paragraph is in pieces.
    assert client.pieces[-1] > 1 and client.blocks[-1] == steps[0].label


@case
def the_markdown_an_agent_writes_reaches_the_page_as_markup():
    live, client, clock = _reporting()
    live.add(progress.Step("**Interprétation** : lire `README.md`.", said=True))
    clock.now += 11
    live.flush()
    assert client.blocks == ["Interprétation : lire README.md."], "no stray asterisks"
    marked = [name for mark in client.marks for name, on in mark.items() if on]
    assert marked == ["bold", "code"]


@case
def a_tool_nobody_named_still_says_what_it_touched():
    """An MCP tool, a new built-in: unknown is not a reason to say nothing."""
    steps = progress.describe(_assistant(_tool("mcp__github__create_pull_request", url="x/y#3")))
    assert steps[0].line == "create_pull_request · x/y#3"


@case
def only_a_failing_tool_result_is_worth_a_line():
    quiet = progress.describe(
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}
    )
    loud = progress.describe(
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "is_error": True, "content": [{"text": "exit 1"}]}
                ]
            },
        }
    )
    assert quiet == []
    assert loud[0].line == "Error · exit 1"
    # The payload is the log's business, never the ticket's.
    assert progress.describe({"type": "result", "num_turns": 4}) == []


class _Live:
    """A Notion that counts what a live report would have written to it."""

    def __init__(self, refuse=False):
        self.refuse = refuse
        self.blocks = []          # the text of every child appended under the toggle
        self.kinds = []           # and its block type
        self.pieces = []          # and how many pieces of rich text it took
        self.marks = []           # every annotation any of those pieces carried
        self.titles = []          # every title the toggle has carried
        self.properties = []      # every value written to the board column

    def append_blocks(self, block_id, blocks):
        if self.refuse:
            raise notion.NotionError("403 forbidden")
        if block_id == "page":
            return ["toggle"]
        for block in blocks:
            kind = block["type"]
            parts = block[kind].get("rich_text", [])
            self.kinds.append(kind)
            self.pieces.append(len(parts))
            self.blocks.append("".join(part["text"]["content"] for part in parts))
            self.marks += [part["annotations"] for part in parts if part.get("annotations")]
        return ["block"] * len(blocks)

    def update_block(self, block_id, payload):
        if self.refuse:
            raise notion.NotionError("403 forbidden")
        self.titles.append(payload["toggle"]["rich_text"][0]["text"]["content"])

    def update(self, database_id, page_id, values):
        if self.refuse:
            raise notion.NotionError("403 forbidden")
        self.properties.append(values["Progress"])


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _reporting(refuse=False, interval=10.0):
    clock, client = _Clock(), _Live(refuse)
    live = progress.Live(
        client,
        "page",
        database="db",
        property_name="Progress",
        interval=interval,
        clock=clock,
        say=lambda message: None,
    )
    return live, client, clock


@case
def the_steps_are_written_on_the_cadence_and_not_before():
    """Six events a second must not become six writes a second."""
    live, client, clock = _reporting()
    for index in range(5):
        clock.now += 1
        live.add(progress.Step("Read", f"file-{index}.py"))
    assert client.blocks == [], "nothing written before the cadence came round"

    clock.now += 6
    live.add(progress.Step("Bash", "pytest"))
    assert len(client.blocks) == 6, "one write, carrying everything that waited"
    assert client.titles[-1].startswith("⏳ Live")
    assert client.properties[-1] == "Bash · pytest", "the board column shows the last step"


@case
def what_is_still_waiting_is_written_when_the_session_ends():
    live, client, clock = _reporting()
    live.add(progress.Step("Edit", "src/x.py"))
    clock.now += 120
    live.close("removed the header")

    assert client.blocks == ["Edit  src/x.py"]
    assert client.titles[-1] == "✓ 1 step(s) · 2 min · removed the header"
    # A finished ticket no longer claims to be doing anything.
    assert client.properties[-1] == ""


@case
def a_session_that_did_nothing_leaves_no_toggle_behind():
    live, client, _ = _reporting()
    live.close("nothing to do")
    assert client.blocks == [] and client.titles == []


@case
def the_same_step_twice_in_a_row_is_said_once():
    live, client, clock = _reporting()
    live.add(progress.Step("Read", "src/x.py"))
    live.add(progress.Step("Read", "src/x.py"))
    live.add(progress.Step("Read", "src/y.py"))
    clock.now += 11
    live.flush()
    assert client.blocks == ["Read  src/x.py", "Read  src/y.py"]


@case
def a_notion_that_refuses_costs_the_report_and_not_the_ticket():
    """Reporting is commentary: it never becomes a reason to fail a ticket."""
    live, client, clock = _reporting(refuse=True)
    for index in range(10):
        clock.now += 11
        live.add(progress.Step("Read", f"file-{index}.py"))
    live.close("done anyway")
    assert live.disabled and client.blocks == []


@case
def a_reporter_never_writes_more_than_a_page_can_hold():
    live, client, clock = _reporting()
    for index in range(progress.MAX_STEPS + 50):
        live.add(progress.Step("Read", f"file-{index}.py"))
    clock.now += 11
    live.flush()
    assert len(client.blocks) == progress.MAX_STEPS + 1, "the steps, then one line saying enough"
    assert client.blocks[-1].startswith("…")

    # Capped is not disabled: the steps stop, the report still says how it ended.
    live.add(progress.Step("Read", "one-too-many.py"))
    clock.now += 11
    live.close("done")
    assert len(client.blocks) == progress.MAX_STEPS + 1
    assert client.titles[-1].startswith("✓") and client.titles[-1].endswith("· done")



# -- the web console ---------------------------------------------------------


@case
def a_typed_command_is_split_without_a_shell():
    """No shell means no metacharacter: the words go to execve as they are."""
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    assert commands.parse(">status") == ["status"]
    assert commands.parse("history -n 5") == ["history", "-n", "5"]
    # A quoted argument stays one argument, accents and spaces included.
    assert commands.parse('run --ticket "à faire"') == ["run", "--ticket", "à faire"]


@case
def a_command_the_cli_does_not_have_is_refused():
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    for line in ("rm -rf /", "run; rm -rf /", "sh -c whoami", "../../bin/sh"):
        try:
            commands.parse(line)
        except ValueError:
            continue
        raise AssertionError(f"{line!r} should not have been accepted")


@case
def the_commands_that_would_hang_a_browser_are_not_offered():
    """`config` opens an editor and `serve` is the console itself.

    Both are refused *and* left out of the list the error message offers: naming
    a verb and then refusing it is a small lie told to somebody already lost.
    """
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    for verb in web_console.REFUSED:
        assert verb not in commands.allowed
        try:
            commands.parse(verb)
        except ValueError as error:
            assert verb in str(error)
        else:
            raise AssertionError(f"{verb} should have been refused")
    assert "run" in commands.allowed and "status" in commands.allowed


@case
def following_a_log_is_dropped_rather_than_left_to_hang():
    """`logs -f` never returns, and the live panel already is that feed."""
    commands = web_console.Commands(lambda *a, **k: None, subcommands())
    assert commands.parse("logs -f") == ["logs"]
    assert commands.parse("logs abc123 --follow") == ["logs", "abc123"]


@case
def a_browser_that_reconnects_is_given_only_what_it_missed():
    """The backlog is replayed by event id, or a suspend would double the chat."""
    hub = web_live.Hub()
    hub.publish("chat", stage="sent", text="one")
    hub.publish("chat", stage="answer", text="two")
    hub.publish("board", tickets=[])

    fresh = hub.subscribe()  # a first connection: the board, and no transcript
    kinds = [fresh.get_nowait().kind for _ in range(fresh.qsize())]
    assert kinds == ["board"], kinds

    back = hub.subscribe(after=1)  # a reconnection, having seen event 1
    seen = [back.get_nowait() for _ in range(back.qsize())]
    assert [event.kind for event in seen] == ["chat", "board"]
    assert seen[0].payload["text"] == "two"


@case
def an_event_carries_its_id_so_the_browser_can_ask_again():
    hub = web_live.Hub()
    hub.publish("step", label="Read", detail="src/x.py")
    channel = hub.subscribe(after=0)
    hub.publish("step", label="Bash", detail="npm test")
    event = channel.get_nowait()
    assert event.encode().startswith("id: 2\nevent: step\ndata: {")
    assert '"label": "Bash"' in event.encode()


@case
def a_log_line_becomes_the_step_the_board_would_have_shown():
    """The live panel and the Notion toggle read the same events, one way."""
    line = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "npm test"}}]},
        }
    )
    steps = web_live.steps(line)
    assert [step.line for step in steps] == ["Bash · npm test"]
    assert web_live.steps("not json at all") == []


@case
def a_session_log_is_tailed_forward_and_never_twice():
    hub = web_live.Hub()
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        log = folder / "20260830-120000-1a2b3c4d.jsonl"
        event = json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "reading"}]}}
        )
        log.write_text(event + "\n", encoding="utf-8")
        tail = web_live.Tail(hub, folder)
        assert tail.pass_once() == 1
        assert tail.pass_once() == 0, "a pass that adds nothing must publish nothing"

        # A half-written line is left for the next pass rather than dropped.
        with log.open("a", encoding="utf-8") as handle:
            handle.write(event[:20])
        assert tail.pass_once() == 0
        with log.open("a", encoding="utf-8") as handle:
            handle.write(event[20:] + "\n")
        assert tail.pass_once() == 1


@case
def the_board_is_published_only_when_it_has_moved():
    """A poll that redrew an unchanged board would lose your scroll for nothing."""
    hub = web_live.Hub()
    boards = [{"tickets": [{"title": "one"}]}, {"tickets": [{"title": "one"}]},
              {"tickets": [{"title": "two"}]}]
    watch = web_live.Watch(hub, lambda: boards.pop(0), interval=5)
    published = []
    hub.publish = lambda kind, **payload: published.append(kind)  # type: ignore[method-assign]
    watch.refresh()
    watch.refresh()
    watch.refresh()
    assert published == ["board", "board"], published


@case
def a_notion_that_will_not_answer_reaches_the_console_as_a_notice():
    """Named `notice`: EventSource already fires an `error` of its own."""
    hub = web_live.Hub()
    said = []
    hub.publish = lambda kind, **payload: said.append((kind, payload))  # type: ignore[method-assign]

    def broken() -> dict:
        raise notion.NotionError("object not found\nsecond line nobody needs")

    web_live.Watch(hub, broken).refresh()
    assert said == [("notice", {"where": "board", "message": "object not found"})]


@case
def a_session_identifier_is_read_from_either_shape_of_the_column():
    """A URL column holds a link, a text column holds the bare ID. Same session."""
    from ticket_runner.web.api import _session_id

    identifier = "6f1c2b70-1c39-4f0a-9a52-1f3c1a2b3c4d"
    assert _session_id(identifier) == identifier
    assert _session_id(session.deep_link(identifier, cwd="/home/me/work")) == identifier
    assert _session_id(session.deep_link(identifier, host="server")) == identifier
    assert _session_id("") == ""


@case
def the_console_only_listens_beyond_localhost_when_told_to():
    """Behind the port sits bypassPermissions: a generated token is not consent."""
    from ticket_runner.web import server as web_server

    configuration = C.Config(
        notion=C.Notion(token="ntn_x", tickets_database="a" * 32),
        runner=C.Runner(),
        projects={},
        path=Path("/nowhere/config.toml"),
        web=C.Web(host="0.0.0.0"),
    )
    explained = io.StringIO()
    with contextlib.redirect_stdout(explained):
        assert web_server.serve(configuration, announce=False) == 2, "must refuse, not serve"
    assert "bypassPermissions" in explained.getvalue(), "and say why, not just refuse"


@case
def a_relation_is_written_as_notion_spells_it():
    """A ticket created from the console names its project, or it is not one."""
    page = "3ca451680af480ae9443de0b65d9abf8"
    assert notion._encode("relation", page) == {"relation": [{"id": page}]}
    assert notion._encode("relation", [page]) == {"relation": [{"id": page}]}
    assert notion._encode("relation", []) == {"relation": []}



# -- the settings tab ---------------------------------------------------------


def _saved(body: str = "") -> tuple[Path, C.Config]:
    """A configuration file on disk, and the runner's reading of it."""
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(
        "# a file somebody wrote by hand\n"
        '[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n' + body,
        encoding="utf-8",
    )
    return path, C.load(path)


@case
def a_value_is_written_as_toml_spells_it():
    """Four shapes, and a string that would otherwise end the line early."""
    assert C._literal(True) == "true" and C._literal(False) == "false"
    assert C._literal(1800) == "1800"
    assert C._literal(["blocked", "done"]) == '["blocked", "done"]'
    assert C._literal('a "quoted" \\ path') == '"a \\"quoted\\" \\\\ path"'

    path, _ = _saved()
    assert C.write_value(path, "runner", "dry_run", True)
    assert C.write_value(path, "runner", "interval_seconds", 900)
    assert C.write_value(path, "notify", "events", ["blocked"])
    # A project called "Site vitrine" is not a bare key, and has to survive
    # being written and read back under the same name.
    assert C.write_value(path, "projects", "Site vitrine", "~/work/site")
    config = C.load(path)
    assert config.runner.dry_run is True
    assert config.runner.interval_seconds == 900
    assert config.notify.events == ("blocked",)
    assert "Site vitrine" in config.projects
    assert C.write_value(path, "projects", "Site vitrine", "~/work/site") is False


@case
def clearing_a_field_removes_the_line_rather_than_emptying_it():
    """A key the file does not carry is a key the loader answers itself.

    Which is the whole grammar of the settings tab: blank means "say nothing",
    and the default comes back — comments and all, for the next time it is set.
    """
    path, _ = _saved('\n[runner]\n# how often it looks\nmodel = "opus"\ninterval_seconds = 60\n')
    assert C.write_value(path, "runner", "model", None) is True
    assert C.write_value(path, "runner", "model", None) is False, "already gone"
    text = path.read_text()
    assert "model" not in text
    assert "# how often it looks" in text, "the comments around it survive"
    assert C.load(path).runner.model == "", "and the default answers"


@case
def a_save_is_all_of_it_or_none_of_it():
    """Half a configuration is a runner that claims tickets it cannot finish."""
    path, config = _saved('\n[runner]\ninterval_seconds = 900\n')
    before = path.read_text()
    try:
        web_settings.save(
            config,
            {"settings": {"runner.max_concurrent": 4, "runner.merge_method": "fast-forward"}},
        )
    except ValueError as error:
        assert "squash" in str(error), error
    else:
        raise AssertionError("a merge method gh would refuse must not be saved")
    assert path.read_text() == before, "the good half must not have landed either"
    assert not [item for item in path.parent.iterdir() if item.name != "config.toml"]


@case
def a_floor_the_loader_would_repair_quietly_is_refused_here():
    """The loader raises a zero interval to one. A form that did so would lie."""
    path, config = _saved()
    for name, value in (
        ("runner.interval_seconds", 0),
        ("runner.progress_interval_seconds", 1),
        ("web.poll_seconds", 2),
        ("runner.update_interval_seconds", 30),
    ):
        try:
            web_settings.save(config, {"settings": {name: value}})
        except ValueError as error:
            assert "at the least" in str(error), error
            continue
        raise AssertionError(f"{name} = {value} should have been refused")


@case
def a_save_that_would_leave_it_unusable_is_refused():
    """The copy is loaded before it is allowed to take the file's place."""
    path, config = _saved()
    before = path.read_text()
    try:
        web_settings.save(config, {"settings": {"notion.token": None}})
    except C.ConfigError as error:
        assert "unusable" in str(error)
        assert ".saving" not in str(error), "and names the file, not the copy"
    else:
        raise AssertionError("a configuration with no token must not be saved")
    assert path.read_text() == before


@case
def a_token_is_never_sent_to_the_browser():
    """A secret goes out as "set, ending in …abcd", and comes back only typed."""
    path, config = _saved(
        '\n[notify.slack]\ntoken = "xoxb-1234567890wxyz"\nchannel = "C1"\n'
    )
    drawn = json.dumps(web_settings.describe(config), ensure_ascii=False)
    assert "ntn_real" not in drawn and "xoxb-1234567890wxyz" not in drawn
    assert "…wxyz" in drawn, "enough to recognise it by"

    fields = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    assert fields["notify.slack.token"]["stated"] is True
    assert fields["notify.slack.token"]["fallback"] == "", "a secret has no default to show"
    assert fields["notify.telegram.token"]["stated"] is False
    assert fields["notify.telegram.token"]["preview"] == ""
    # Typing one sets it; the gesture that clears one is its own.
    web_settings.save(config, {"settings": {"notify.slack.token": "xoxb-new"}})
    assert C.load(path).notify.slack["token"] == "xoxb-new"
    web_settings.save(C.load(path), {"settings": {"notify.slack.token": None}})
    assert "token" not in C.load(path).notify.slack


@case
def what_the_file_says_is_told_apart_from_what_it_falls_back_on():
    """Otherwise a save would write every default into the file it read."""
    path, config = _saved("\n[runner]\ninterval_seconds = 900\n")
    fields = {
        field["name"]: field
        for section in web_settings.describe(config)["sections"]
        for field in section["fields"]
    }
    stated = fields["runner.interval_seconds"]
    assert stated["value"] == 900 and stated["stated"] is True
    silent = fields["runner.max_concurrent"]
    assert silent["value"] is None and silent["stated"] is False
    assert silent["fallback"] == C.Runner().max_concurrent, "the default, shown greyed"
    # The three naming tables are drawn from the defaults, not listed twice.
    assert fields["notion.status.validated"]["fallback"] == "Validated"
    assert fields["notion.properties.progress"]["fallback"] == "Progress"


@case
def every_setting_the_file_holds_is_one_the_console_can_reach():
    """A key added to config.py and not described is a key nobody can set.

    The console draws itself from `settings.SECTIONS`; this is what keeps that
    description from falling behind the dataclasses it describes.
    """
    expected = set()
    for table, holder in (("runner", C.Runner()), ("web", C.Web()), ("notify", C.Notify())):
        for name in vars(holder):
            # The two channel tables are their own sections, and `projects` is a
            # mapping you add rows to rather than a list of known keys.
            if name in ("telegram", "slack"):
                continue
            expected.add(f"{table}.{name}")
    for name in vars(C.Notion()):
        if name in ("pages", "properties", "status"):
            continue
        expected.add(f"notion.{name}")
    for table in ("pages", "properties", "status"):
        expected |= {f"notion.{table}.{key}" for key in C.defaults(table)}
    expected |= {"notify.telegram.token", "notify.telegram.chat"}
    expected |= {"notify.slack.token", "notify.slack.channel"}

    missing = expected - set(web_settings.FIELDS)
    assert not missing, f"not reachable from the console: {sorted(missing)}"
    unknown = set(web_settings.FIELDS) - expected
    assert not unknown, f"described but not read by the loader: {sorted(unknown)}"

    for name, field in web_settings.FIELDS.items():
        assert field.label, name
        assert field.kind in ("text", "secret", "path", "bool", "int", "choice", "events"), name
        if field.kind == "choice":
            assert field.choices, name


@case
def the_projects_table_gains_and_loses_rows():
    """The one section that is a mapping rather than a list of known keys."""
    path, config = _saved('\n[projects]\n"Site vitrine" = "~/work/site"\nold = "~/work/old"\n')
    web_settings.save(
        config,
        {"projects": [
            {"name": "Site vitrine", "path": "~/work/site-v2"},
            {"name": "Trader IA", "path": "~/work/trader"},
        ]},
    )
    projects = C.load(path).projects
    assert set(projects) == {"Site vitrine", "Trader IA"}, "the row you removed is gone"
    assert projects["Site vitrine"].endswith("site-v2")


@case
def a_setting_that_needs_more_than_saving_says_so_and_only_when_it_moved():
    """A notice about a restart you do not need is a notice you stop reading."""
    path, config = _saved()
    result = web_settings.save(config, {"settings": {"runner.interval_seconds": 600}})
    assert result["saved"] == ["runner.interval_seconds"]
    assert any("timer" in note for note in result["after"])

    result = web_settings.save(C.load(path), {"settings": {"runner.max_concurrent": 3}})
    assert result["after"] == [], "nothing to do but the next run"
    # Saving what the file already says changes nothing and claims nothing.
    assert web_settings.save(C.load(path), {"settings": {"runner.max_concurrent": 3}})["saved"] == []


# -- being told, and answering ------------------------------------------------


@contextmanager
def _state():
    """A state directory of its own, so a test never reads yesterday's cursor."""
    previous = os.environ.get("XDG_STATE_HOME")
    with tempfile.TemporaryDirectory() as directory:
        os.environ["XDG_STATE_HOME"] = directory
        try:
            yield Path(directory)
        finally:
            if previous is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = previous


@contextmanager
def _api(module, answers: dict):
    """Replace one channel's HTTP call with a table of canned answers."""
    calls: list[tuple[str, dict | None]] = []

    def fake(url, payload=None, headers=None):
        calls.append((url, payload))
        for fragment, body in answers.items():
            if fragment in url:
                return body
        return {"ok": True, "result": {}}

    original = module.request
    module.request = fake
    try:
        yield calls
    finally:
        module.request = original


@case
def a_word_is_a_verdict_only_when_it_opens_the_sentence():
    assert channels.decide("oui") == "yes"
    assert channels.decide("Yes, and rename the column while you are there") == "yes"
    assert channels.decide("👍") == "yes"
    assert channels.decide("non") == "no"
    assert channels.decide("No — that column stays") == "no"
    assert channels.decide("aucune idée, demande à Marie") == "", "not every sentence is a verdict"
    assert channels.decide("I have no idea") == "", "a no in the middle is not an answer"
    assert channels.decide("   ") == ""


@case
def a_bare_yes_reaches_the_agent_as_a_sentence():
    """"oui" means nothing to a session that never saw the notification."""
    written = channels.answer(channels.Reply(channel="telegram", text="oui", who="Salvador"))
    assert "Salvador" in written
    assert "go ahead" in written
    assert written.count("oui") == 0, "the word itself adds nothing once it is spelled out"

    kept = channels.answer(
        channels.Reply(channel="slack", text="oui, et renomme la colonne aussi")
    )
    assert "go ahead" in kept
    assert "renomme la colonne" in kept, "what was said around the word is the instruction"

    free = channels.answer(channels.Reply(channel="telegram", text="celui du dashboard"))
    assert "celui du dashboard" in free
    assert "go ahead" not in free and "do not" not in free


TICKET = "3ca451680af480ae9443de0b65d9abf8"
OTHER = "3ca451680af480beb02ac9d2cb79078c"


def _asks() -> list[channels.Ask]:
    return [
        channels.Ask(ref="10", ticket=OTHER, title="Le footer"),
        channels.Ask(ref="11", ticket=TICKET, title="Le header"),
    ]


@case
def an_answer_finds_its_ticket_by_thread_first_then_by_name():
    channel = telegram_channel.Telegram("token", "42")
    replied = channel._route(channels.Incoming(ref="12", thread="10", text="oui"), _asks())
    assert replied.ticket == OTHER, "a reply to a message answers that message"

    named = channel._route(
        channels.Incoming(ref="12", text="oui pour 3ca45168-0af4-80be-b02a-c9d2cb79078c"),
        _asks(),
    )
    assert named.ticket == OTHER, "a ticket named in the text is not a guess either"

    last = channel._route(channels.Incoming(ref="12", text="oui"), _asks())
    assert last.ticket == TICKET, "a bare yes answers the question just asked"
    assert channel._route(channels.Incoming(ref="12", text="oui"), []) is None


@case
def a_telegram_message_from_anywhere_else_is_not_an_answer():
    """A bot token is a public address: anyone can write to it."""
    channel = telegram_channel.Telegram("token", "42")
    updates = {
        "ok": True,
        "result": [
            {"update_id": 7, "message": {"message_id": 1, "chat": {"id": 42},
                                         "from": {"first_name": "Salvador"}, "text": "oui"}},
            {"update_id": 8, "message": {"message_id": 2, "chat": {"id": 99},
                                         "from": {"first_name": "Someone"}, "text": "rm -rf"}},
            {"update_id": 9, "message": {"message_id": 3, "chat": {"id": 42},
                                         "from": {"is_bot": True}, "text": "echo"}},
        ],
    }
    with _api(telegram_channel, {"getUpdates": updates}) as calls:
        incoming, cursor = channel._fetch("", [])
    assert [message.text for message in incoming] == ["oui"]
    assert incoming[0].who == "Salvador"
    assert cursor == "10", "the offset acknowledges what was read, so it is read once"
    assert calls[0][1]["allowed_updates"] == ["message"]


def _update(identifier: int, message: int, text: str) -> dict:
    return {
        "update_id": identifier,
        "message": {
            "message_id": message,
            "chat": {"id": 42},
            "from": {"first_name": "Salvador"},
            "text": text,
        },
    }


SENT = {"sendMessage": {"ok": True, "result": {"message_id": 5}}}


@case
def nothing_said_before_the_runner_was_listening_is_an_answer():
    """Telegram keeps a day of updates; Slack keeps everything ever said."""
    channel = telegram_channel.Telegram("token", "42")
    backlog = {"ok": True, "result": [_update(7, 1, "oui"), _update(8, 2, "et le footer ?")]}
    with _state():
        with _api(telegram_channel, {"getUpdates": backlog, **SENT}):
            channel.send("?", ticket=TICKET, title="Le header", ask=True)
            assert channel.collect() == [], "a backlog is a conversation, not a queue"
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": [_update(9, 3, "oui")]}}) as calls:
            assert [reply.text for reply in channel.collect()] == ["oui"]
            assert calls[0][1]["offset"] == 9, "the first poll only settled where now is"


@case
def what_a_channel_reads_once_it_never_reads_again():
    channel = telegram_channel.Telegram("token", "42")
    with _state():
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": []}, **SENT}):
            channel.send("Blocked · le header ?", ticket=TICKET, title="Le header", ask=True)
            assert channel.collect() == []
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": [_update(7, 1, "oui")]}}):
            first = channel.collect()
        assert [reply.ticket for reply in first] == [TICKET]
        assert first[0].title == "Le header", "the question remembers what it was about"
        with _api(telegram_channel, {"getUpdates": {"ok": True, "result": []}}) as calls:
            assert channel.collect() == []
            assert calls[0][1]["offset"] == 8, "resumed where the last run stopped"


@case
def a_room_shared_with_other_people_never_guesses():
    """In Slack the message beside yours belongs to somebody else's thread."""
    ask = [channels.Ask(ref="100.0", ticket=TICKET, title="Le header")]
    loose = channels.Incoming(ref="100.4", text="ok")
    assert slack_channel.Slack("xoxb", "C1")._route(loose, ask) is None
    assert telegram_channel.Telegram("token", "42")._route(loose, ask).ticket == TICKET
    threaded = channels.Incoming(ref="100.4", thread="100.0", text="ok")
    assert slack_channel.Slack("xoxb", "C1")._route(threaded, ask).ticket == TICKET
    named = channels.Incoming(ref="100.4", text=f"ok pour {TICKET}")
    assert slack_channel.Slack("xoxb", "C1")._route(named, ask).ticket == TICKET


@case
def an_acknowledgement_hangs_where_each_service_counts_threads_from():
    """Slack threads from the first message; Telegram quotes the last one."""
    reply = channels.Reply(channel="", text="oui", ref="100.4", thread="100.0")
    assert slack_channel.Slack("xoxb", "C1")._thread_of(reply) == "100.0"
    assert telegram_channel.Telegram("token", "42")._thread_of(reply) == "100.4"


@case
def slack_reads_the_thread_the_question_opened():
    """A message in a thread never appears in the channel's history."""
    channel = slack_channel.Slack("xoxb-token", "C1")
    answers = {
        "conversations.history": {"ok": True, "messages": [
            {"ts": "100.2", "user": "U1", "text": "et le footer ?"},
            {"ts": "100.1", "bot_id": "B1", "text": "🙋 Blocked · le header"},
            {"ts": "099.9", "user": "U1", "text": "déjà lu"},
        ]},
        "conversations.replies": {"ok": True, "messages": [
            {"ts": "100.0", "bot_id": "B1", "text": "🙋 Blocked · le header"},
            {"ts": "100.3", "user": "U1", "thread_ts": "100.0", "text": "oui"},
        ]},
    }
    with _api(slack_channel, answers):
        incoming, cursor = channel._fetch("100.0", [channels.Ask(ref="100.0", ticket=TICKET)])
    said = [(message.text, message.thread) for message in incoming]
    assert said == [("et le footer ?", ""), ("oui", "100.0")], said
    assert cursor == "100.3", "the newest timestamp seen, whichever call saw it"


@case
def slack_never_reads_its_own_voice_back():
    channel = slack_channel.Slack("xoxb-token", "C1")
    assert channel._read({"ts": "2", "bot_id": "B1", "text": "posted by us"}, "1") is None
    assert channel._read({"ts": "2", "subtype": "channel_join", "user": "U1"}, "1") is None
    assert channel._read({"ts": "1", "user": "U1", "text": "old"}, "1") is None
    assert channel._read({"ts": "2", "user": "U1", "text": "oui"}, "1").text == "oui"


@case
def a_question_outlives_the_run_that_asked_it():
    """An answer typed tomorrow morning still knows which ticket it settles."""
    channel = telegram_channel.Telegram("token", "42")
    with _state():
        with _api(telegram_channel, {"sendMessage": {"ok": True, "result": {"message_id": 1}}}):
            for index in range(channels.ASKS + 3):
                channel.send("?", ticket=f"{index:032d}", title=f"ticket {index}", ask=True)
        remembered = channels._memory()["telegram"]["asks"]
    assert len(remembered) == channels.ASKS, "a bounded memory, not a growing file"
    assert remembered[-1]["title"] == f"ticket {channels.ASKS + 2}"


@case
def a_channel_exists_only_once_both_of_its_values_are_there():
    half = _config('[notify.telegram]\ntoken = "123:abc"\n')
    assert not half.notify.remote and channels.open(half.notify) == []

    whole = _config('[notify.telegram]\ntoken = "123:abc"\nchat = 4242\n')
    assert whole.notify.remote
    assert whole.notify.telegram["chat"] == "4242", "a chat id is compared to JSON, so it is text"
    assert [channel.name for channel in channels.open(whole.notify)] == ["telegram"]

    both = _config(
        '[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
        '[notify.slack]\ntoken = "xoxb"\nchannel = "C1"\n'
    )
    assert [channel.name for channel in channels.open(both.notify)] == ["telegram", "slack"]


@case
def the_switch_that_came_first_still_means_what_it_said():
    """`runner.notify` was the desktop notification, and stays it."""
    assert _config("").notify.desktop is True
    assert _config('[runner]\nnotify = false\n').notify.desktop is False
    assert _config('[runner]\nnotify = false\n\n[notify]\ndesktop = true\n').notify.desktop is True


@case
def a_moment_nobody_named_is_dropped_rather_than_never_sent():
    every = _config("")
    assert every.notify.wants("blocked") and every.notify.wants("done")
    only = _config('[notify]\nevents = ["blocked", "Failed", "merged"]\n')
    assert only.notify.events == ("blocked", "failed"), only.notify.events
    assert not only.notify.wants("done")
    assert not only.notify.wants("merged"), "a typo is not a moment"


@case
def a_value_can_be_written_into_a_table_that_has_a_dot_in_its_name():
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text('[notion]\ntoken = "ntn_real"\ntickets_database = "abc"\n')
    assert C.write_value(path, "notify.telegram", "chat", "4242") is True
    assert C.write_value(path, "notify.telegram", "chat", "4242") is False, "already says that"
    assert C.load(path).notify.telegram["chat"] == "4242"
    assert 'token = "ntn_real"' in path.read_text(), "the rest of the file is untouched"


class _AnsweringClient:
    """A Notion that only has to remember what was written on which page."""

    def __init__(self, error: str = ""):
        self.written: list[tuple[str, str]] = []
        self._error = error

    def comment(self, page_id: str, text: str) -> None:
        if self._error:
            raise notion.NotionError(self._error)
        self.written.append((page_id, text))


class _StubChannel(channels.Channel):
    name = "telegram"

    def __init__(self, replies: list[channels.Reply]):
        self._replies = replies
        self.said: list[str] = []

    def collect(self) -> list[channels.Reply]:
        return list(self._replies)

    def acknowledge(self, reply: channels.Reply, text: str) -> bool:
        self.said.append(text)
        return True


@contextmanager
def _channel(stub):
    original = channels.open
    channels.open = lambda settings: [stub]
    try:
        yield stub
    finally:
        channels.open = original


def _answering(replies: list[channels.Reply], error: str = "") -> tuple[Runner, _StubChannel]:
    runner = Runner.__new__(Runner)
    runner.config = _config('[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n')
    runner.client = _AnsweringClient(error)
    runner.dry_run = False
    runner.quiet = True
    stub = _StubChannel(replies)
    with _channel(stub):
        runner.answers()
    return runner, stub


@case
def an_answer_from_a_phone_becomes_the_comment_that_wakes_the_ticket():
    """One path, not two: the reply is a comment, and comments already wake."""
    runner, stub = _answering(
        [channels.Reply(channel="telegram", text="oui", ticket=TICKET, title="Le header")]
    )
    assert len(runner.client.written) == 1
    page, text = runner.client.written[0]
    assert page == TICKET
    assert "go ahead" in text
    assert not text.startswith("ticket-runner@"), (
        "signed as ours, the answer would close the ticket instead of waking it"
    )
    assert stub.said and "Le header" in stub.said[0], "an answer nobody confirms is a phone call"


@case
def a_message_that_answers_nothing_is_never_written_to_a_ticket():
    runner, stub = _answering([channels.Reply(channel="telegram", text="tiens, une idée")])
    assert runner.client.written == []
    assert stub.said == [], "a bot that answers ordinary talk is a bot nobody keeps"

    runner, stub = _answering([channels.Reply(channel="telegram", text="oui")])
    assert runner.client.written == []
    assert stub.said, "a yes that landed nowhere was meant for us, and is told it missed"


@case
def a_notion_that_refuses_the_answer_says_so_where_it_was_typed():
    runner, stub = _answering(
        [channels.Reply(channel="telegram", text="oui", ticket=TICKET, title="Le header")],
        error="403 API token does not have access",
    )
    assert runner.client.written == []
    assert "403" in stub.said[0]


@case
def a_blocked_ticket_travels_with_its_question_and_its_link():
    sent: list[dict] = []
    runner = Runner.__new__(Runner)
    runner.config = _config(
        '[notify]\ndesktop = false\n\n[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n'
    )
    runner.dry_run = False
    runner.quiet = True
    ticket = type("T", (), {
        "page": notion.Page(id=TICKET, url="https://notion.so/t", title="Le header"),
        "title": "Le header",
        "url": "https://notion.so/t",
    })()

    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append({"text": text, **rest})
    try:
        runner._tell(
            "blocked", ticket, "Blocked · Le header",
            "Which header — the dashboard one or the public site?",
            ask=True,
        )
    finally:
        channels.announce = original

    assert len(sent) == 1
    message = sent[0]
    assert "Which header" in message["text"], "the agent's question, not the runner's summary"
    assert "https://notion.so/t" in message["text"], "a notification you have to go and find"
    assert "Answer here" in message["text"]
    assert message["ask"] is True and message["ticket"] == TICKET


@case
def nothing_is_sent_anywhere_during_a_dry_run():
    sent: list[str] = []
    runner = Runner.__new__(Runner)
    runner.config = _config('[notify.telegram]\ntoken = "123:abc"\nchat = "42"\n')
    runner.dry_run = True
    runner.quiet = True
    ticket = type("T", (), {
        "page": notion.Page(id=TICKET, url="u", title="t"), "title": "t", "url": "u",
    })()
    original = channels.announce
    channels.announce = lambda settings, text, **rest: sent.append(text)
    try:
        runner._tell("done", ticket, "Ready to review · t", "branch")
    finally:
        channels.announce = original
    assert sent == []


# -- releases ----------------------------------------------------------------


@case
def the_version_and_the_changelog_never_drift():
    """The one invariant the whole release system rests on.

    `__version__` and the newest released section of CHANGELOG.md are written by
    the same command, in the same breath. If they are ever seen apart, something
    edited one of them by hand — and the release that follows would ship a
    number whose notes describe a different one.
    """
    version = release.read_version()
    release.parse(version)  # raises if it is not a version at all

    entries = release.released(release.CHANGELOG.read_text(encoding="utf-8"))
    for name, date, body in entries:
        release.parse(name)
        assert date, f"[{name}] has no date"
        assert body.strip(), f"[{name}] has no notes"

    order = [release.order(name) for name, _date, _body in entries]
    assert order == sorted(order, reverse=True), "the changelog runs newest first"

    if entries:
        assert entries[0][0] == version, (
            f"__version__ is {version}, the newest changelog section is [{entries[0][0]}]"
        )


@case
def a_release_only_ever_moves_forward():
    assert release.next_version("0.1.0", "patch") == "0.1.1"
    assert release.next_version("0.1.9", "minor") == "0.2.0"
    assert release.next_version("0.9.3", "major") == "1.0.0"
    assert release.next_version("1.2.3", "2.0.0") == "2.0.0"

    for backwards in ("0.1.0", "1.2.2", "1.0.0"):
        try:
            release.next_version("1.2.3", backwards)
        except release.Problem:
            pass
        else:
            raise AssertionError(f"{backwards} after 1.2.3 must be refused")

    # Once, in a repository's life: nothing released yet, so the number the tree
    # already carries is the number to release it under.
    assert release.next_version("0.1.0", "0.1.0", first=True) == "0.1.0"


@case
def a_bump_promotes_the_notes_and_opens_an_empty_unreleased():
    text = (
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A thing.\n\n"
        "## [0.1.0] - 2026-01-01\n\n### Added\n\n- The first thing.\n"
    )
    moved = release.promote(text, "0.2.0", "2026-08-31")

    names = [name for name, _date, _body in release.sections(moved)]
    assert names == ["Unreleased", "0.2.0", "0.1.0"], names

    assert release.notes_for(moved, "0.2.0") == "### Added\n\n- A thing."
    assert release.notes_for(moved, "0.1.0") == "### Added\n\n- The first thing."
    unreleased = dict((name, body) for name, _date, body in release.sections(moved))
    assert unreleased["Unreleased"].strip() == "", "the next cycle starts empty"


@case
def an_empty_unreleased_is_not_a_release():
    """A tag with no notes is a tag, and nobody came here for a tag."""
    for refused in (
        "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n- One.\n",
        "# Changelog\n\n## [0.1.0] - 2026-01-01\n\n- One.\n",
    ):
        try:
            release.promote(refused, "0.2.0", "2026-08-31")
        except release.Problem:
            pass
        else:
            raise AssertionError("an empty or missing [Unreleased] must be refused")

    already = "# Changelog\n\n## [Unreleased]\n\n- New.\n\n## [0.2.0] - 2026-01-01\n\n- Old.\n"
    try:
        release.promote(already, "0.2.0", "2026-08-31")
    except release.Problem:
        pass
    else:
        raise AssertionError("a version that already has a section must be refused")


@case
def the_dash_in_a_changelog_heading_is_whichever_one_was_typed():
    """The file is written by hand, and a hand that writes em dashes writes them here.

    A heading the parser fails to see is a release whose notes silently come out
    empty, which is only noticed once it is published.
    """
    for dash in ("-", "\u2013", "\u2014"):
        text = f"# Changelog\n\n## [0.1.0] {dash} 2026-01-01\n\n- One.\n"
        assert release.notes_for(text, "0.1.0") == "- One.", dash


def _plain(text: str) -> str:
    """The same output a pipe would get: colour is not part of what is asserted."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


@case
def a_bare_command_line_presents_the_product_and_its_version():
    """`ticket-runner`, typed alone, is somebody's first look at what they installed.

    So it answers the two questions that come with that — what is this, and
    which version am I on — before it lists the verbs. The frame is drawn from
    the uncoloured text, which is what keeps it square once colours are on.
    """
    with _state_home():
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            assert cli_main([]) == 0
        printed = _plain(buffer.getvalue())

    assert f"ticket-runner {__version__}" in printed
    assert "Turns ready Notion tickets into Claude Code sessions." in printed
    for name in subcommands():
        assert f"\n    {name} " in printed or f"\n    {name}  " in printed, (
            f"{name} is a command the welcome screen does not name"
        )

    framed = [line for line in _plain(banner()).splitlines() if line.strip()]
    assert len({len(line) for line in framed}) == 1, "the frame is not square"


@case
def a_waiting_update_is_said_on_the_welcome_screen():
    """The one thing worth adding to a version number: that it is not the newest.

    Read from the stamp a run already wrote — a welcome screen that fetched
    would be a network round trip for every `ticket-runner` typed by mistake.
    """
    with _state_home():
        update.remember(update.Status(current="a" * 40, latest="b" * 40))
        assert "b" * 8 in _plain(banner())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            welcome(build_parser())
        assert "ticket-runner update" in _plain(buffer.getvalue())


@case
def the_console_header_and_the_command_line_agree_on_the_version():
    """One number, two surfaces: what --version prints is what the browser shows.

    The console reads it bare — an update waiting is a separate field, so the
    header can print a version where a version belongs rather than a sentence.
    """
    with _state_home():
        assert web_api._version() == __version__
        assert web_api._update_available() == "", "nothing checked yet is not an update"
        update.remember(update.Status(current="a" * 40, latest="b" * 40))
        assert web_api._version() == __version__
        assert web_api._update_available() == "b" * 8


@case
def the_console_header_shows_the_version_it_is_given():
    """The number reaches the header, rather than staying in the payload."""
    app = (Path(__file__).resolve().parents[1] / "src/ticket_runner/web/static/app.js").read_text(
        encoding="utf-8"
    )
    page = (Path(__file__).resolve().parents[1] / "src/ticket_runner/web/static/index.html").read_text(
        encoding="utf-8"
    )
    assert 'id="version"' in page, "the header has nowhere to print the version"
    assert "info.version" in app and '$("version")' in app
    assert "info.update" in app, "an update waiting has to be said too"


@case
def the_header_says_what_the_runner_is_doing_without_words():
    """The bar's shader is handed the same three facts the bar's words carry.

    A moving picture nobody wired to anything is decoration. This one is a
    status light — the stream, the run, the event that just landed — so what it
    is told, and that it is told at all, is worth pinning down.
    """
    static = Path(__file__).resolve().parents[1] / "src/ticket_runner/web/static"
    page = (static / "index.html").read_text(encoding="utf-8")
    app = (static / "app.js").read_text(encoding="utf-8")
    header = (static / "header.js").read_text(encoding="utf-8")

    assert 'id="bar-fx"' in page, "the bar has nowhere to draw"
    assert page.index("header.js") < page.index("app.js"), "app.js calls what header.js defines"
    assert 'fx("setAlive"' in app, "a dropped stream has to reach the bar"
    assert 'fx("setEnergy"' in app, "a run in progress has to reach the bar"
    assert 'fx("pulse")' in app, "an event landing has to reach the bar"
    assert "if (window.HeaderFX)" in app, "a machine with no WebGL still runs the console"
    for name in ("setEnergy", "setAlive", "pulse"):
        assert f"api.{name}" in header, f"the bar answers to {name}"


@case
def the_header_gives_the_machine_back_when_nobody_is_looking():
    """A shader in the chrome of a local tool is a promise about the fan.

    Four things keep it from costing a laptop its afternoon, and every one of
    them is the sort a refactor drops without noticing: a hidden tab draws
    nothing, a machine that cannot keep up is asked for less, a screen asking
    for stillness gets it, and a context taken away is not a black rectangle.
    """
    header = (
        Path(__file__).resolve().parents[1] / "src/ticket_runner/web/static/header.js"
    ).read_text(encoding="utf-8")

    assert "document.hidden" in header, "a tab nobody is looking at still renders"
    assert "prefers-reduced-motion" in header, "stillness asked for is not given"
    assert "state.scale" in header, "a slow machine is never asked for less"
    assert "webglcontextlost" in header, "a lost context leaves a black bar"
    assert "devicePixelRatio" in header, "a retina screen is rendered at full density"


@case
def the_console_asks_for_nothing_it_did_not_ship():
    """Nothing the page loads comes from anywhere but this machine.

    The console is served by `http.server` on loopback, and a header that
    reached for a library on a CDN would be a console that looks broken on a
    train and tells somebody else when you opened it.
    """
    # An `xmlns` is a name, not an address; what is looked for here is the
    # shapes that actually make the browser open a socket.
    reaches = ('src="http', "src='http", 'href="http', "href='http",
               "url(http", "url('http", 'url("http', "@import", "//unpkg", "//cdn")
    static = Path(__file__).resolve().parents[1] / "src/ticket_runner/web/static"
    for name in ("index.html", "app.js", "header.js", "style.css"):
        text = (static / name).read_text(encoding="utf-8")
        for shape in reaches:
            assert shape not in text, f"{name} reaches off the machine: {shape}"


@case
def the_version_is_rewritten_where_the_product_reads_it():
    """`__version__` is what --version and the console header print.

    The rewrite is a regular expression over the real file, so this checks it
    against the real file's shape rather than against a fixture that agrees
    with it by construction.
    """
    with tempfile.TemporaryDirectory() as directory:
        init = Path(directory) / "__init__.py"
        init.write_text(release.INIT.read_text(encoding="utf-8"), encoding="utf-8")
        release.write_version("9.9.9", init)
        assert release.read_version(init) == "9.9.9"
        assert '__version__ = "9.9.9"' in init.read_text(encoding="utf-8")


def main() -> int:
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
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
