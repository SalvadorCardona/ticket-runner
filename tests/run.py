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

import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ticket_runner import config as C  # noqa: E402
from ticket_runner import agents, markdown, notion, prompt, session, workspace  # noqa: E402
from ticket_runner.runner import Runner  # noqa: E402
from ticket_runner.__main__ import _names  # noqa: E402
from ticket_runner.runner import short_id, slugify  # noqa: E402
from ticket_runner.projects import _normalise  # noqa: E402

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
    assert config.notion.state("ready") == "Not started", "defaults survive a partial block"

    config = _config('[notion.status]\nfailed = "Draft"\nblocked = "Blocked"\n')
    assert config.notion.state("failed") == "Draft"
    assert config.notion.state("blocked") == "Blocked"

    config = _config("")
    assert config.notion.state("done") == "Done"
    assert config.notion.state("blocked") == "Draft"


@case
def the_interval_never_reaches_systemd_as_zero():
    assert _config("[runner]\ninterval_seconds = 0\n").runner.interval_seconds == 1
    assert _config("[runner]\ninterval_seconds = 10\n").runner.interval_seconds == 10
    assert _config("").runner.interval_seconds == 1800


@case
def optional_properties_have_names_even_when_absent():
    config = _config("")
    for key in ("status", "project", "agent", "pull_request", "session", "model",
                "priority", "cost", "duration"):
        assert config.notion.prop(key), key


@case
def a_workspace_is_named_once_and_the_rest_is_found():
    config = _config("")
    assert config.notion.page("tickets") == "Master Tickets"
    assert config.notion.page("context") == "Soul"
    renamed = _config('[notion.pages]\ncontext = "Qui je suis"\n')
    assert renamed.notion.page("context") == "Qui je suis"
    assert renamed.notion.page("tickets") == "Master Tickets", "defaults survive a partial block"


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
    values = {"token": "ntn_real", "workspace": "space", "pages": dict(C._DEFAULT_PAGES)}
    values.update(overrides)
    return C.Notion(**values)


@case
def the_rows_of_a_workspace_become_the_runners_databases():
    client = _FakeClient(
        {"Master Tickets": "p-tickets", "Master project": "p-projects", "Soul": "p-soul"},
        text="Je suis Salvador Cardona.",
    )
    space = workspace.resolve(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.projects == "db-of-p-projects"
    assert space.context == "Je suis Salvador Cardona."
    assert not space.warnings


@case
def a_row_is_found_however_its_title_is_capitalised():
    client = _FakeClient({"master tickets": "p-tickets", "SOUL": "p-soul"}, text="x")
    space = workspace.resolve(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.context == "x"


@case
def a_missing_context_page_warns_but_never_fails_a_run():
    client = _FakeClient({"Master Tickets": "p-tickets"})
    space = workspace.resolve(client, _settings())
    assert space.tickets == "db-of-p-tickets"
    assert space.context == "" and space.projects == ""
    assert any("Soul" in warning for warning in space.warnings)

    # Present but unreadable, and present but empty, are both worth saying too.
    unreadable = _FakeClient({"Master Tickets": "p-t", "Soul": "p-soul"}, broken={"p-soul"})
    assert any("unreadable" in warning for warning in workspace.resolve(unreadable, _settings()).warnings)
    empty = _FakeClient({"Master Tickets": "p-t", "Soul": "p-soul"}, text="   ")
    assert any("empty" in warning for warning in workspace.resolve(empty, _settings()).warnings)


@case
def a_missing_tickets_page_is_the_one_thing_that_fails():
    client = _FakeClient({"Soul": "p-soul", "Master project": "p-projects"})
    try:
        workspace.resolve(client, _settings())
    except notion.NotionError as error:
        assert "Master Tickets" in str(error)
        assert "Soul" in str(error), "the message lists what was actually found"
    else:
        raise AssertionError("a workspace without a tickets page must not resolve")


@case
def an_explicit_database_still_wins_over_the_workspace():
    client = _FakeClient({"Master Tickets": "p-tickets"})
    space = workspace.resolve(client, _settings(tickets_database="chosen"))
    assert space.tickets == "db-of-chosen"

    # And a configuration written before workspaces existed resolves the same.
    legacy = workspace.resolve(client, _settings(workspace="", tickets_database="chosen"))
    assert legacy.tickets == "db-of-chosen"
    assert legacy.rows == {} and not legacy.warnings


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


def _runner_reading(texts: list[str], error: str = "") -> tuple[Runner, list[str]]:
    """A Runner with its Notion replaced, and nothing else touched."""
    runner = Runner.__new__(Runner)
    runner.client = _CommentClient(texts, error)
    runner.agent_label = "ticket-runner@laptop"
    runner.quiet = True
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
