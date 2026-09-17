"""Where the board lives, whoever holds it.

The runner was written against Notion, and against nothing else: `notion.Client`
was passed around as *the* way to read a ticket, to write a status, to say
something on a page. That was true for as long as there was one place a board
could be — and it stopped being true the day the answer to "can this run without
Notion?" had to be yes.

So this module is the seam. Three things live here and nothing else:

- **the vocabulary.** `Page`, `Comment`, and `read` — a property reduced to a
  plain Python value. Their shape is Notion's, deliberately: a `Page` carries
  its properties the way the API writes them, and every backend produces that
  same shape rather than a dialect of its own. Which is why `read` is here and
  not in `notion.py` — it decodes what *any* store hands over, and a second
  decoder per backend is the bug nobody would find;
- **the interface.** `Store` says what the rest of the runner may ask of a
  board. It is a `Protocol` rather than a base class, because the fakes the test
  suite is made of are duck-typed and were never going to inherit from anything;
- **the choice.** `open()` reads `[storage]` and hands back the one the
  configuration asked for: Notion as before, Markdown files on disk, or the two
  kept in step. Nothing above this module knows which it got.

What is *not* here is provisioning: creating a database, widening a select,
adding a property. That is Notion's own shape being built, it only ever happens
through `ticket-runner init`, and a Markdown board has none of it — the
directories are made the first time something is written into them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# The three modes of `storage.mode`, and the whole of them.
MODES = ("notion", "markdown", "both")

# How a page edited on both sides at once is settled. One rule, named, because
# the day there is a second one the configuration has to be able to say which.
CONFLICTS = ("newest",)


class StoreError(Exception):
    """The board could not be read or written.

    One class for every backend: the callers that catch this are asking "did the
    board answer?", and the answer is no whether that was a 502 from Notion or a
    directory this user cannot write to.
    """


@dataclass
class Comment:
    """One comment, and what it takes to answer it where it was written.

    `discussion_id` is the thread it belongs to: Notion groups comments into
    discussions, and answering *into* one is the whole difference between a
    conversation and a page covered in unrelated remarks. `created_by` is who
    wrote it — which is how the runner tells its own words from yours without
    having to recognise its own signature in a string.
    """

    text: str
    created_time: str = ""
    id: str = ""
    discussion_id: str = ""
    created_by: str = ""


@dataclass
class Page:
    id: str
    url: str
    title: str
    properties: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def read(page: Page, name: str) -> Any:
    """A property's value, reduced to a plain Python type."""
    prop = page.properties.get(name)
    if not prop:
        return None
    kind = prop.get("type")
    if kind in ("rich_text", "title"):
        return "".join(part.get("plain_text", "") for part in prop.get(kind, [])).strip()
    if kind == "status":
        return (prop.get("status") or {}).get("name")
    if kind == "select":
        return (prop.get("select") or {}).get("name")
    if kind == "url":
        return prop.get("url")
    if kind == "relation":
        return [item.get("id") for item in prop.get("relation", [])]
    if kind == "people":
        return [item.get("id") for item in prop.get("people", [])]
    if kind == "checkbox":
        return prop.get("checkbox")
    if kind == "number":
        return prop.get("number")
    if kind == "date":
        # A Notion date may be a range. The deadline is where it ends.
        value = prop.get("date") or {}
        return value.get("end") or value.get("start")
    if kind == "formula":
        inner = prop.get("formula") or {}
        return inner.get(inner.get("type", ""), None)
    return prop.get(kind)


def written(kind: str | None, value: Any) -> dict | None:
    """One property, in the shape a `Page` carries it. The inverse of `read`.

    Type tag included, which is what tells this apart from `notion._encode`:
    that one builds the body of a `PATCH`, this one builds what `read` will be
    handed back. A store that keeps its pages on disk needs the second.
    """
    if kind is None or value is None:
        return None
    if kind in ("status", "select"):
        return {"type": kind, kind: {"name": str(value)}}
    if kind == "url":
        return {"type": "url", "url": str(value) or None}
    if kind in ("rich_text", "title"):
        return {"type": kind, kind: [{"plain_text": str(value), "type": "text"}]}
    if kind == "checkbox":
        return {"type": "checkbox", "checkbox": bool(value)}
    if kind == "number":
        return {"type": "number", "number": value}
    if kind == "date":
        return {"type": "date", "date": {"start": str(value), "end": None}}
    if kind == "relation":
        ids = value if isinstance(value, (list, tuple)) else [value]
        return {"type": "relation", "relation": [{"id": str(one)} for one in ids if one]}
    return None


@runtime_checkable
class Store(Protocol):
    """Everything the runner and the console ask of a board.

    Deliberately the surface `notion.Client` already had, rather than a smaller
    ideal one: the runner is written against it, and an interface that forced
    every call site to be rewritten would have been a rewrite pretending to be
    an abstraction. What changed is that it is now *named*, and that two other
    things implement it.
    """

    # -- reading -------------------------------------------------------------

    def resolve_database(self, identifier: str) -> str: ...

    def schema(self, database_id: str) -> dict[str, str]: ...

    def options(self, database_id: str, name: str) -> list[str]: ...

    def title_property(self, database_id: str) -> str: ...

    def forget_database(self, database_id: str) -> None: ...

    def query(self, database_id: str, filter_: dict | None = None) -> list[Page]: ...

    def page(self, page_id: str) -> Page: ...

    def blocks_text(self, block_id: str, depth: int = 0) -> str: ...

    def comments(self, page_id: str) -> list[Comment]: ...

    # -- writing -------------------------------------------------------------

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None: ...

    def create_row(self, database_id: str, title: str, values: dict | None = None) -> str: ...

    def append_markdown(self, page_id: str, markdown: str) -> int: ...

    def replace_markdown(self, page_id: str, markdown: str) -> int: ...

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None: ...

    # -- who we are ----------------------------------------------------------

    def me(self) -> str: ...

    def my_name(self) -> str: ...

    # -- the board's own shape -----------------------------------------------

    def workspace(self, settings: Any) -> Any:
        """The databases and the standing context. See `workspace.Workspace`."""
        ...


def open(config) -> Store:  # noqa: A001 — it opens a store, and nothing else does
    """The store the configuration asks for.

    `notion` is the default and the whole of the old behaviour. `markdown` never
    reaches the network: a token is not even read. `both` is the two of them,
    reconciled before every pass — see `sync.py`.

    Imported here rather than at the top, so that a Markdown-only installation
    never loads a module whose only job is to talk to an API it will not use.
    """
    mode = config.storage.mode
    # `config.notion` is handed over whichever mode this is, and that is not a
    # contradiction: the `[notion]` table is two things at once — the token and
    # the workspace, which only Notion uses, and the *names* of the columns and
    # the columns' values, which are the board's whoever holds it.
    if mode == "markdown":
        from .files import Board

        return Board(config.storage.path, config.notion)
    if mode == "both":
        from .files import Board
        from .notion import Client
        from .sync import Mirror

        return Mirror(
            Client(config.notion.token),
            Board(config.storage.path, config.notion),
            conflict=config.storage.conflict,
        )
    from .notion import Client

    return Client(config.notion.token)
