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
from ticket_runner import markdown, notion, session  # noqa: E402
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


# -- runner ------------------------------------------------------------------


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
