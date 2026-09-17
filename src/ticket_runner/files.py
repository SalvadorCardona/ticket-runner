"""The board as a directory of Markdown files.

A ticket is a page with properties and a body. Notion is one way of holding
that; a file with a frontmatter and some prose under it is another, and it is
the one that works on a plane, in a git repository, and without an integration
token. So the same board, written down:

    board/
      context.md                     the standing context, body only
      tickets/<slug>-<id>.md
      projects/<slug>-<id>.md
      agents/<slug>-<id>.md
      schedules/<slug>-<id>.md
      comments/<id>.md               one page's discussion, oldest first

Three decisions carry the rest of the module.

**The frontmatter is flat, and four keys are reserved.** `id`, `title`,
`created` and `edited` are the page itself; every other key is a property, under
the name the board spells it — `Status: Ready`, not `status: ready`. Flat and
under the real column names, because the whole point of files is that you open
one and change a word. Nested tables and a `properties:` level would have been
tidier for the parser and worse for the person.

**The types come from `provision.py`.** A property's kind — select, date,
checkbox, relation — is what `read` needs to hand back the right Python value,
and the shape of the board is already declared once, where the Notion databases
are built. Declaring it a second time here is how the two would drift.

**Nothing is ever deleted.** No method here removes a page, and `sync.py` never
asks for one: a board you edit with a text editor is a board where a file
disappears for a hundred reasons, and none of them should be echoed anywhere.

The YAML is a subset, written by hand for the same reason the rest of the core
has no dependencies: scalars, quoted strings, and `- item` lists. Anything this
cannot read comes back as the string it was written as, which is the one failure
mode that loses nothing.
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import Comment, Page, StoreError, read, written

# The collections a board is made of, and the file that is not one of them.
COLLECTIONS = ("tickets", "projects", "agents", "schedules")
CONTEXT = "context.md"

# The standing context is the one page that is not in a collection, so it has no
# identifier of its own. This is the name it answers to when a caller addresses
# it as a page — `blocks_text`, `append_markdown`, `replace_markdown`.
CONTEXT_PAGE = "context"

# A frontmatter starts and ends on this, alone on its line.
FENCE = "---"

# What a page carries about itself, as opposed to what the board carries about it.
RESERVED = ("id", "title", "created", "edited")


def now() -> str:
    """The moment a file was last written, to the microsecond.

    Not to the second, which is what a frontmatter would rather read: `edited`
    is what `sync.py` compares against the last reconciliation, and two writes
    in the same second would be one write as far as it could tell.
    """
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def new_id() -> str:
    """A page identifier the rest of the runner already knows how to read.

    Thirty-two hexadecimal characters, which is what `config.is_identifier`
    accepts and what `short_id` takes its last eight from — so a Markdown ticket
    gets a worktree, a log file and a branch named exactly as a Notion one does.
    """
    return uuid.uuid4().hex


def slug(text: str, limit: int = 48) -> str:
    """A filename somebody can find in a list, from a title somebody wrote."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:limit].rstrip("-") or "page"


# -- the frontmatter ---------------------------------------------------------


def _scalar(raw: str) -> Any:
    """One right-hand side, as the plainest Python value it can be.

    Quoted stays a string, always: a `Day: "1"` that came back as an integer
    would be a schedule whose day of the month is no longer a day of the month.
    """
    text = raw.strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return json.loads(text) if text[0] == '"' else text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    if text == "null":
        return None
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def _literal(value: Any) -> str:
    """One right-hand side, written so that `_scalar` reads it back.

    Quoted whenever the bare form would be read as something else — a number, a
    boolean, an empty cell — or would not survive the line at all.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = "" if value is None else str(value)
    if text != text.strip() or not text or text in ("true", "false", "null"):
        return json.dumps(text, ensure_ascii=False)
    if re.fullmatch(r"-?\d+(\.\d+)?", text) or text[0] in "\"'-[{#&*!|>%@`":
        return json.dumps(text, ensure_ascii=False)
    if "\n" in text or ": " in text or text.endswith(":"):
        return json.dumps(text, ensure_ascii=False)
    return text


def parse(text: str) -> tuple[dict[str, Any], str]:
    """A file, split into its frontmatter and its body.

    A file with no frontmatter is all body, which is what `context.md` is and
    what a page somebody wrote by hand before knowing about any of this is.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        return {}, text.strip()
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == FENCE)
    except StopIteration:
        return {}, text.strip()

    front: dict[str, Any] = {}
    key = ""
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- ") and key:
            # A list item belongs to the key above it, and a key whose value was
            # empty is the key a list hangs off.
            existing = front.get(key)
            item = _scalar(line.lstrip()[2:])
            front[key] = [*existing, item] if isinstance(existing, list) else [item]
            continue
        name, _, value = line.partition(":")
        key = name.strip()
        if not key:
            continue
        front[key] = _scalar(value) if value.strip() else []
    return front, "\n".join(lines[end + 1 :]).strip()


def render(front: dict[str, Any], body: str) -> str:
    """The file, from the two halves `parse` gives back.

    Reserved keys first and in their order, then the properties sorted by name:
    a file rewritten by the runner and a file rewritten by the sync have to come
    out byte for byte the same, or every pass would look like a change.
    """
    lines = [FENCE]
    keys = [key for key in RESERVED if key in front]
    keys += sorted(key for key in front if key not in RESERVED)
    for key in keys:
        value = front[key]
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}:")
            lines += [f"  - {_literal(item)}" for item in value]
        else:
            lines.append(f"{key}: {_literal(value)}")
    lines.append(FENCE)
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


# -- the shape of the board --------------------------------------------------


def schemas(settings) -> dict[str, dict[str, str]]:
    """{collection: {property: kind}}, from the one place the board is declared.

    `provision.py` builds the Notion databases from these very shapes, so a
    column added there is a column a Markdown board reads the same day. The
    relation targets are named after the collections rather than after database
    IDs, since here that is what a relation points at.
    """
    from . import provision

    def kinds(schema: dict) -> dict[str, str]:
        return {name: next(iter(shape)) for name, shape in schema.items()}

    return {
        "tickets": kinds(provision.tickets_schema(settings, "projects", "agents")),
        "projects": kinds(provision.projects_schema()),
        "agents": kinds(provision.agents_schema(settings)),
        "schedules": kinds(provision.schedules_schema(settings, "tickets", "projects")),
    }


def _matches(page: Page, filter_: dict | None) -> bool:
    """Does this page satisfy one of the filters the runner builds?

    Three shapes and no more, because three is all there are: an `and` of
    clauses, an `equals`, and a `does_not_equal`. Anything else matches
    everything — a filter this cannot read must not silently empty the board.
    """
    if not filter_:
        return True
    if "and" in filter_:
        return all(_matches(page, clause) for clause in filter_["and"])
    if "or" in filter_:
        return any(_matches(page, clause) for clause in filter_["or"])
    name = filter_.get("property")
    if not name:
        return True
    for kind, test in filter_.items():
        if kind == "property" or not isinstance(test, dict):
            continue
        value = read(page, name)
        if "equals" in test:
            return value == test["equals"]
        if "does_not_equal" in test:
            return value != test["does_not_equal"]
    return True


class Board:
    """A board kept in files. One implementation of `store.Store`.

    Stateless on purpose: every read goes to the disk. There is no rate limit to
    spare here, a directory of a hundred tickets is read in milliseconds, and a
    cache would only be a second copy to keep true — which is the whole problem
    this store exists to avoid having twice.
    """

    def __init__(self, root: Path, settings=None) -> None:
        self._root = Path(root).expanduser()
        self._settings = settings
        self._schemas: dict[str, dict[str, str]] | None = None

    # -- where things are ----------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    def settings(self):
        """The naming settings the board is read under.

        Read from the configuration the first time it is wanted rather than
        required at construction: `store.open` builds this from a path, and a
        board read with the default column names is the overwhelming case.
        """
        if self._settings is None:
            from .config import Notion

            self._settings = Notion()
        return self._settings

    def directory(self, collection: str) -> Path:
        if collection not in COLLECTIONS:
            raise StoreError(f"no such collection: {collection}")
        return self._root / collection

    def context_file(self) -> Path:
        return self._root / CONTEXT

    def comments_file(self, page_id: str) -> Path:
        return self._root / "comments" / f"{_bare(page_id)}.md"

    def _files(self, collection: str) -> list[Path]:
        directory = self.directory(collection)
        if not directory.is_dir():
            return []
        return sorted(path for path in directory.glob("*.md") if path.is_file())

    def _find(self, page_id: str) -> tuple[str, Path]:
        """The collection and the file of a page, from its identifier alone.

        The runner addresses a page by ID and nothing else — `client.page(id)` —
        so the board has to be able to answer without being told where to look.
        Four directories of text files is a cheap enough search, and the
        alternative is an index file that can be wrong.
        """
        bare = _bare(page_id)
        if not bare:
            raise StoreError(f"no page id to look for in {self._root}")
        # The filename carries the last eight characters of the identifier, so
        # the name answers first and the file is only opened when it might be
        # the one. Without that, reading a single ticket would parse the whole
        # board — and the runner reads a page per ticket, several times a pass.
        tail = bare[-8:]
        for collection in COLLECTIONS:
            for path in self._files(collection):
                if not path.stem.endswith(tail):
                    continue
                if _bare(parse(_text(path))[0].get("id", "")) in (bare, ""):
                    return collection, path
        raise StoreError(f"no such page in {self._root}: {page_id}")

    # -- reading -------------------------------------------------------------

    def resolve_database(self, identifier: str) -> str:
        """A collection name, from whatever the caller had in hand.

        Notion's identifiers mean nothing here, so a configuration that names a
        Notion database — a leftover from before the switch — resolves to the
        tickets collection rather than to an error nobody could act on.
        """
        name = str(identifier or "").strip().lower()
        return name if name in COLLECTIONS else "tickets"

    def forget_database(self, database_id: str) -> None:
        """Nothing is cached, so there is nothing to forget."""

    def schema(self, database_id: str) -> dict[str, str]:
        if self._schemas is None:
            self._schemas = schemas(self.settings())
        return self._schemas.get(self.resolve_database(database_id), {})

    def options(self, database_id: str, name: str) -> list[str]:
        """Every value that column carries, plus the ones the board declares.

        A Markdown board has no select to constrain it: anything you type into
        `Status:` is a status. What the runner asks this for is "does the board
        offer the validated column?", and the honest answer is what the
        configuration names plus whatever is actually written down.
        """
        from .config import _DEFAULT_STATUS

        settings = self.settings()
        declared: list[str] = []
        if name == settings.prop("status"):
            declared = [settings.state(key) for key in _DEFAULT_STATUS]
        seen = list(dict.fromkeys(declared))
        for page in self.query(database_id):
            value = read(page, name)
            if isinstance(value, str) and value and value not in seen:
                seen.append(value)
        return seen

    def title_property(self, database_id: str) -> str:
        return "Name"

    def query(self, database_id: str, filter_: dict | None = None) -> list[Page]:
        collection = self.resolve_database(database_id)
        pages = [self._page_of(collection, path) for path in self._files(collection)]
        return [page for page in pages if _matches(page, filter_)]

    def page(self, page_id: str) -> Page:
        collection, path = self._find(page_id)
        return self._page_of(collection, path)

    def blocks_text(self, block_id: str, depth: int = 0) -> str:
        """A page's body. Already Markdown, so already what an agent reads."""
        if _bare(block_id) == CONTEXT_PAGE:
            return _text(self.context_file()).strip()
        _, path = self._find(block_id)
        return parse(_text(path))[1]

    def comments(self, page_id: str) -> list[Comment]:
        """The discussion of one page, oldest first.

        One file per page rather than one per comment: a discussion is read
        whole, every time, and forty files to open for a ticket that has been
        round three times would be forty files to open. The separator is a
        fence, so a comment may hold blank lines without ending itself.
        """
        text = _text(self.comments_file(page_id))
        found: list[Comment] = []
        for block in text.split("\n---comment---\n"):
            front, body = parse(block.strip())
            if not body.strip():
                continue
            found.append(
                Comment(
                    body.strip(),
                    str(front.get("at", "")),
                    id=str(front.get("id", "")),
                    discussion_id=str(front.get("discussion", "")),
                    created_by=str(front.get("by", "")),
                )
            )
        return found

    def workspace(self, settings):
        """Four directories and a file — which is all a Markdown board is.

        No resolution, no warnings about a page that is not shared: the one
        thing worth saying is that the standing context is empty, because that
        costs every ticket the same thing it costs on a Notion board.
        """
        from .workspace import Workspace

        # The naming settings decide what every column is called, so a board
        # resolved under new ones is a board whose schema has to be read again.
        if settings is not self._settings:
            self._settings, self._schemas = settings, None
        space = Workspace(
            tickets="tickets",
            projects="projects",
            agents="agents",
            schedules="schedules",
            rows={name: name for name in COLLECTIONS},
            context_page=CONTEXT_PAGE,
        )
        space.context = _text(self.context_file()).strip()
        if not space.context:
            space.warnings.append(
                f"{self.context_file()} is empty — nothing about you reaches the agent"
            )
        return space

    def _page_of(self, collection: str, path: Path) -> Page:
        front, body = parse(_text(path))
        schema = self.schema(collection)
        identifier = _bare(str(front.get("id") or path.stem.rsplit("-", 1)[-1]))
        title = str(front.get("title") or "")
        properties: dict[str, Any] = {
            "Name": {"type": "title", "title": [{"plain_text": title, "type": "text"}]}
        }
        for name, value in front.items():
            if name in RESERVED:
                continue
            # A column the board does not declare is still a column somebody
            # typed: read as text, which is what every unknown Notion property
            # reduces to anyway.
            shape = written(schema.get(name, "rich_text"), value)
            if shape is not None:
                properties[name] = shape
        return Page(
            id=identifier,
            url=path.as_uri(),
            title=title.strip(),
            properties=properties,
            raw={
                "created_time": str(front.get("created", "")),
                "last_edited_time": str(front.get("edited", "")),
                "collection": collection,
                "path": str(path),
                "body": body,
            },
        )

    # -- writing -------------------------------------------------------------

    def create_row(
        self, database_id: str, title: str, values: dict | None = None, page_id: str = ""
    ) -> str:
        """A new page in a collection, and its identifier.

        `page_id` is for the mirror and for nobody else: a page that exists on
        both sides has to wear the same name on both, and the side that created
        it first is the one that chose it.
        """
        collection = self.resolve_database(database_id)
        identifier = _bare(page_id) or new_id()
        stamp = now()
        front: dict[str, Any] = {
            "id": identifier,
            "title": title.strip(),
            "created": stamp,
            "edited": stamp,
        }
        front.update(self._values(collection, values or {}))
        path = self.directory(collection) / f"{slug(title)}-{identifier[-8:]}.md"
        _write(path, render(front, ""))
        return identifier

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        """Write properties by name. The title is a property like the others here."""
        if not values:
            return
        collection, path = self._find(page_id)
        front, body = parse(_text(path))
        title_property = self.title_property(collection)
        for name, value in self._values(collection, values).items():
            if name == title_property:
                front["title"] = value
            else:
                front[name] = value
        front["edited"] = now()
        _write(path, render(front, body))

    def rename(self, collection: str, page_id: str, fresh: str) -> None:
        """Give a page another identifier, file and all.

        One caller, and one reason: a page born on this side and mirrored into
        Notion has to take Notion's identifier, because that is what its URL, its
        relations and every report about it will carry from then on. Not a
        general gesture — nothing else here ever renames a page.
        """
        _, path = self._find(page_id)
        front, body = parse(_text(path))
        front["id"] = _bare(fresh)
        front["edited"] = now()
        target = self.directory(collection) / f"{slug(str(front.get('title', '')))}-{_bare(fresh)[-8:]}.md"
        _write(target, render(front, body))
        if target != path:
            try:
                path.unlink()
            except OSError as error:
                raise StoreError(f"{path}: {error}") from error
        # The discussion travels with the page; a thread filed under a name
        # nothing points at any more is a thread nobody can find.
        old_comments = self.comments_file(page_id)
        if old_comments.is_file():
            _write(self.comments_file(fresh), _text(old_comments))
            old_comments.unlink(missing_ok=True)

    def append_markdown(self, page_id: str, markdown: str) -> int:
        """Add to a page's body. Returns a block count, for what says so."""
        if _bare(page_id) == CONTEXT_PAGE:
            text = _text(self.context_file())
            _write(self.context_file(), f"{text.rstrip()}\n\n{markdown.strip()}\n".lstrip())
            return _blocks(markdown)
        _, path = self._find(page_id)
        front, body = parse(_text(path))
        front["edited"] = now()
        _write(path, render(front, f"{body}\n\n{markdown.strip()}".strip()))
        return _blocks(markdown)

    def replace_markdown(self, page_id: str, markdown: str) -> int:
        """Make a page's body say this and nothing else. See the Notion client."""
        if _bare(page_id) == CONTEXT_PAGE:
            _write(self.context_file(), markdown.strip() + "\n")
            return _blocks(markdown)
        _, path = self._find(page_id)
        front, body = parse(_text(path))
        if body.strip() == markdown.strip():
            return _blocks(markdown)
        front["edited"] = now()
        _write(path, render(front, markdown))
        return _blocks(markdown)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        """Say something on a page, into a thread or opening one."""
        identifier = new_id()
        block = render(
            {
                "id": identifier,
                "at": now(),
                "by": self.me(),
                "discussion": discussion_id or identifier,
            },
            text,
        )
        existing = _text(self.comments_file(page_id))
        joined = f"{existing.rstrip()}\n---comment---\n{block}" if existing.strip() else block
        _write(self.comments_file(page_id), joined)

    def append_blocks(self, block_id: str, blocks: list[dict]) -> list[str]:
        """Notion blocks, flattened back into the Markdown they came from.

        Nothing in a file is addressable below the page, so a block's
        "identifier" is the page's: the live report opens a folded block, is
        handed the page back, and goes on appending its steps to the same file.
        Which is the right shape here — a text file has no fold to hide them in,
        and a ticket that ends on the story of its own session reads fine.

        What is lost is the toggle's title being kept current, since there is no
        line to rewrite. `update_block` says so by doing nothing.
        """
        from . import markdown as converter

        text = "\n".join(converter.plain(block) for block in blocks).strip()
        if text:
            self.append_markdown(block_id, text)
        return [_bare(block_id)] * len(blocks)

    def update_block(self, block_id: str, payload: dict) -> None:
        """Nothing here is addressable below the page. See `append_blocks`."""

    # -- who we are ----------------------------------------------------------

    def me(self) -> str:
        """The name the runner's own words are signed with.

        A constant rather than an account: there is no API to ask, and the one
        question this answers — "did we write this comment?" — has a stable
        answer on a board only this machine writes to.
        """
        return "ticket-runner"

    def my_name(self) -> str:
        return "ticket-runner"

    # -- the standing context, as the console edits it -----------------------

    def context(self) -> str:
        return _text(self.context_file()).strip()

    def set_context(self, text: str) -> None:
        _write(self.context_file(), text.strip() + "\n")

    def _values(self, collection: str, values: dict[str, Any]) -> dict[str, Any]:
        """Property values, reduced to what a frontmatter line can hold.

        A relation arrives as a list of IDs and stays one; a date arrives as a
        `datetime` and is written ISO, which is how it is read back. Everything
        else is a scalar already.
        """
        schema = self.schema(collection)
        written_values: dict[str, Any] = {}
        for name, value in values.items():
            kind = schema.get(name, "rich_text")
            if value is None:
                continue
            if isinstance(value, datetime):
                written_values[name] = value.isoformat()
            elif kind == "relation":
                written_values[name] = [
                    _bare(str(one)) for one in (value if isinstance(value, (list, tuple)) else [value]) if one
                ]
            elif kind == "checkbox":
                written_values[name] = bool(value)
            else:
                written_values[name] = value
        return written_values


def _bare(identifier: str) -> str:
    return str(identifier or "").replace("-", "").strip()


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    except OSError as error:
        raise StoreError(f"{path}: {error}") from error


def _write(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as error:
        raise StoreError(f"{path}: {error}") from error


def _blocks(markdown: str) -> int:
    """How many blocks that text would have been, for the reports that count them."""
    from . import markdown as converter

    return len(converter.to_blocks(markdown))
