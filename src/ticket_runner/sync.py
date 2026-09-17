"""Keeping a Notion board and a Markdown board saying the same thing.

`storage.mode = "both"` is not "write twice". Writing twice is easy and wrong:
the moment somebody drags a ticket in Notion, or fixes a typo in a file, the two
copies part ways and nothing notices. So the mirror does two separate things.

**A pass reconciles first.** Before any ticket is read, `synchronise()` walks
both sides page by page and carries every change across. Which side changed is
decided against a stamp of the last reconciliation — `edited` on each side,
against what it was when they last agreed — so a page nobody has touched costs
one comparison and no write at all.

**Then the mirror is a store like any other.** Reads go to Notion, which is the
side a person is most likely to be looking at; writes go to both, so the run's
own work does not have to wait for the next reconciliation to be visible on
disk. The Markdown side is addressed under the *Notion* page ID throughout,
which is what makes the two halves of a page findable from either.

Three rules decide everything else, and they are the ones worth arguing about:

- **the newest wins, and the loser is written down.** A page edited on both
  sides since the last pass is a conflict; `storage.conflict = "newest"` settles
  it by `last_edited_time`, and the version that lost goes into the journal with
  both timestamps. Nothing is ever silently overwritten without a line saying so;
- **nothing is deleted, ever.** A page that was on both sides and is now on one
  is journalled as a deletion and left alone on the side that still has it. A
  board is not a filesystem replica: a ticket somebody archived in Notion is not
  a reason to throw away the file they may have been editing;
- **a page that never existed on the other side is created there.** Which is
  what makes `storage.mode = "both"` work from a board that is already full: the
  first pass copies everything across, in whichever direction it is missing.

The journal is `sync.jsonl` under the state directory, one JSON object per line,
and it is what `ticket-runner sync --journal` prints.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .files import COLLECTIONS, Board
from .store import Page, StoreError, read

# What the reconciliation walks, and the order it walks it in: a ticket's
# relations point at projects and agents, so those exist on both sides first.
ORDER = ("projects", "agents", "tickets", "schedules")

# The standing context is a page rather than a collection, and is reconciled on
# its body alone — it has no properties and no identity beyond being itself.
CONTEXT = "context"


def journal_path() -> Path:
    from .config import state_dir

    return state_dir() / "sync.jsonl"


@dataclass
class Entry:
    """One thing the reconciliation did, or refused to do.

    `what` is one of: `notion→markdown`, `markdown→notion`, `conflict`,
    `deleted-in-notion`, `deleted-in-markdown`, `created-in-notion`,
    `created-in-markdown`.
    """

    what: str
    collection: str
    page: str
    title: str = ""
    detail: str = ""
    at: str = ""

    def line(self) -> str:
        return json.dumps(
            {
                "at": self.at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "what": self.what,
                "collection": self.collection,
                "page": self.page,
                "title": self.title,
                "detail": self.detail,
            },
            ensure_ascii=False,
        )


@dataclass
class Report:
    """What one reconciliation amounted to, for whoever asked for it."""

    entries: list[Entry] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def note(self, what: str, collection: str, page: str, title: str = "", detail: str = "") -> None:
        self.entries.append(Entry(what, collection, page, title, detail))

    def of(self, *kinds: str) -> list[Entry]:
        return [entry for entry in self.entries if entry.what in kinds]

    @property
    def conflicts(self) -> list[Entry]:
        return self.of("conflict")

    @property
    def deletions(self) -> list[Entry]:
        return self.of("deleted-in-notion", "deleted-in-markdown")

    @property
    def carried(self) -> list[Entry]:
        return self.of(
            "notion→markdown", "markdown→notion", "created-in-notion", "created-in-markdown"
        )

    def __bool__(self) -> bool:
        return bool(self.entries)


def write_journal(report: Report, path: Path | None = None) -> None:
    """Append what happened, and never fail a pass for want of writing it down."""
    if not report.entries:
        return
    target = path or journal_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            for entry in report.entries:
                handle.write(entry.line() + "\n")
    except OSError:
        report.problems.append(f"the journal could not be written: {target}")


def journal(limit: int = 50, path: Path | None = None) -> list[dict]:
    """The last entries of the journal, oldest first."""
    target = path or journal_path()
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    found: list[dict] = []
    for line in lines[-limit:]:
        try:
            found.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return found


# -- what the two sides agreed on last time ----------------------------------


class Stamps:
    """When each page last agreed with itself across the two boards.

    Without this there is no telling a change from a difference: two pages that
    differ tell you nothing about *who* moved. `{page id: [notion edited,
    markdown edited]}`, written after every reconciliation, and a page it has
    never heard of is a page that has never been reconciled — which is what
    makes "created" and "deleted" distinguishable at all.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._known: dict[str, list[str]] = {}
        try:
            self._known = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._known = {}

    def seen(self, page_id: str) -> bool:
        return page_id in self._known

    def notion(self, page_id: str) -> str:
        return (self._known.get(page_id) or ["", ""])[0]

    def markdown(self, page_id: str) -> str:
        return (self._known.get(page_id) or ["", ""])[1]

    def agreed(self, page_id: str, notion_at: str, markdown_at: str) -> None:
        self._known[page_id] = [notion_at, markdown_at]

    def forget_nothing(self) -> None:
        """Deliberately not a method: a page is never dropped from the stamps.

        Dropping one would turn the next pass's "deleted on one side" back into
        "created on the other", and re-create what somebody removed.
        """

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._known, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            pass


def stamps_path() -> Path:
    from .config import state_dir

    return state_dir() / "sync.json"


# -- the mirror --------------------------------------------------------------


def _edited(page: Page) -> str:
    return str(page.raw.get("last_edited_time") or page.raw.get("created_time") or "")


def _moment(stamp: str) -> datetime:
    """An ISO timestamp, comparable. Anything unreadable is the beginning of time."""
    try:
        moment = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _newer(left: str, right: str) -> bool:
    return _moment(left) > _moment(right)


class Mirror:
    """Both boards, as one store. See the module docstring.

    Every read is Notion's answer, so a mirrored installation behaves exactly as
    a Notion one does — the console, the queue, the comments, all unchanged.
    What is added is that every write lands on disk too, and that a pass begins
    by carrying across whatever was changed elsewhere.
    """

    def __init__(self, primary, mirror: Board, *, conflict: str = "newest") -> None:
        self.primary = primary
        self.mirror = mirror
        self.conflict = conflict
        self._collections: dict[str, str] = {}

    # -- reading: Notion answers ---------------------------------------------

    def resolve_database(self, identifier: str) -> str:
        return self.primary.resolve_database(identifier)

    def forget_database(self, database_id: str) -> None:
        self.primary.forget_database(database_id)

    def schema(self, database_id: str) -> dict[str, str]:
        return self.primary.schema(database_id)

    def options(self, database_id: str, name: str) -> list[str]:
        return self.primary.options(database_id, name)

    def title_property(self, database_id: str) -> str:
        return self.primary.title_property(database_id)

    def query(self, database_id: str, filter_: dict | None = None) -> list[Page]:
        return self.primary.query(database_id, filter_)

    def page(self, page_id: str) -> Page:
        return self.primary.page(page_id)

    def blocks_text(self, block_id: str, depth: int = 0) -> str:
        return self.primary.blocks_text(block_id, depth)

    def comments(self, page_id: str):
        return self.primary.comments(page_id)

    def me(self) -> str:
        return self.primary.me()

    def my_name(self) -> str:
        return self.primary.my_name()

    def workspace(self, settings):
        """Notion's own, and the collection names it maps onto on disk.

        Remembered as it is resolved, because every write below has to know
        which directory a Notion database ID corresponds to — and the only place
        that correspondence is ever established is here.
        """
        space = self.primary.workspace(settings)
        self.mirror.workspace(settings)
        self._collections = {
            getattr(space, name): name for name in COLLECTIONS if getattr(space, name, "")
        }
        return space

    # -- writing: both, Notion first -----------------------------------------

    def _collection(self, database_id: str) -> str:
        """Which directory a Notion database ID is mirrored in.

        Tickets when nothing says otherwise: the tickets database is the one the
        runner writes to without ever having resolved the workspace — a
        configuration that names `tickets_database` and nothing else.
        """
        return self._collections.get(database_id, "tickets")

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        self.primary.update(database_id, page_id, values)
        self._mirror_update(self._collection(database_id), page_id, values)

    def create_row(self, database_id: str, title: str, values: dict | None = None) -> str:
        page_id = self.primary.create_row(database_id, title, values)
        try:
            self.mirror.create_row(
                self._collection(database_id), title, values, page_id=page_id
            )
        except StoreError:
            # The Notion page exists and is what the runner will work from. A
            # disk that would not take its twin is the next pass's problem, and
            # the next reconciliation makes the file.
            pass
        return page_id

    def append_markdown(self, page_id: str, markdown: str) -> int:
        count = self.primary.append_markdown(page_id, markdown)
        try:
            self.mirror.append_markdown(page_id, markdown)
        except StoreError:
            pass
        return count

    def replace_markdown(self, page_id: str, markdown: str) -> int:
        count = self.primary.replace_markdown(page_id, markdown)
        try:
            self.mirror.replace_markdown(page_id, markdown)
        except StoreError:
            pass
        return count

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        self.primary.comment(page_id, text, discussion_id)
        try:
            self.mirror.comment(page_id, text, discussion_id)
        except StoreError:
            pass

    def append_blocks(self, block_id: str, blocks: list[dict]) -> list[str]:
        # Only Notion's IDs come back, and only Notion has anything to hand
        # back: a block is not addressable in a file. See `files.append_blocks`.
        return self.primary.append_blocks(block_id, blocks)

    def update_block(self, block_id: str, payload: dict) -> None:
        self.primary.update_block(block_id, payload)

    def _mirror_update(self, collection: str, page_id: str, values: dict[str, Any]) -> None:
        """Write the same properties on disk, making the file if it is not there.

        A page written before the mirror was turned on has no file yet, and the
        write that discovers it is the one that creates it — with what Notion
        says it holds, not with the half-dozen values this particular write
        happened to carry.
        """
        try:
            self.mirror.update(collection, page_id, values)
        except StoreError:
            try:
                page = self.primary.page(page_id)
            except StoreError:
                return
            try:
                self._write_file(collection, page)
            except StoreError:
                pass

    # -- the reconciliation ---------------------------------------------------

    def synchronise(self, settings, *, stamps: Stamps | None = None) -> Report:
        """Carry every change across, both ways, and say what happened.

        Never raises for one page: a ticket Notion refuses is one line in
        `report.problems` and the rest of the board is still reconciled. The one
        thing that does stop it is a workspace that cannot be resolved, because
        then there is nothing to walk.
        """
        report = Report()
        marks = stamps if stamps is not None else Stamps(stamps_path())
        try:
            space = self.workspace(settings)
        except StoreError as error:
            report.problems.append(str(error).splitlines()[0])
            return report

        for collection in ORDER:
            database = getattr(space, collection, "")
            if not database:
                continue
            try:
                self._reconcile(collection, database, settings, marks, report)
            except StoreError as error:
                report.problems.append(f"{collection}: {str(error).splitlines()[0]}")

        self._reconcile_context(space, settings, marks, report)
        marks.save()
        write_journal(report)
        return report

    def _reconcile(
        self, collection: str, database: str, settings, marks: Stamps, report: Report
    ) -> None:
        here = {_bare(page.id): page for page in self.primary.query(database)}
        there = {_bare(page.id): page for page in self.mirror.query(collection)}

        for page_id in sorted(set(here) | set(there)):
            left, right = here.get(page_id), there.get(page_id)
            if left is not None and right is not None:
                self._settle(collection, database, page_id, left, right, marks, report)
            elif left is not None:
                if marks.seen(page_id):
                    # It was on both sides and the file is gone. Nothing is
                    # deleted in Notion over that — a file disappears for a
                    # hundred reasons and none of them is a decision.
                    report.note(
                        "deleted-in-markdown", collection, page_id, left.title,
                        "the file is gone; the Notion page is left as it is",
                    )
                    continue
                self._write_file(collection, left)
                marks.agreed(page_id, _edited(left), _now())
                report.note("created-in-markdown", collection, page_id, left.title)
            else:
                assert right is not None
                if marks.seen(page_id):
                    report.note(
                        "deleted-in-notion", collection, page_id, right.title,
                        "the Notion page is gone; the file is left as it is",
                    )
                    continue
                created = self._write_page(collection, database, right)
                if created:
                    marks.agreed(created, _now(), _now())
                    report.note("created-in-notion", collection, created, right.title)

    def _settle(
        self,
        collection: str,
        database: str,
        page_id: str,
        left: Page,
        right: Page,
        marks: Stamps,
        report: Report,
    ) -> None:
        """One page that exists on both sides. Who moved, and what to do about it."""
        notion_at, markdown_at = _edited(left), _edited(right)
        moved_notion = _newer(notion_at, marks.notion(page_id)) if marks.seen(page_id) else True
        moved_markdown = (
            _newer(markdown_at, marks.markdown(page_id)) if marks.seen(page_id) else False
        )

        if moved_notion and moved_markdown:
            # `storage.conflict` names the rule; "newest" is the only one there
            # is, and the whole of it is which timestamp is bigger.
            wins_notion = not _newer(markdown_at, notion_at)
            report.note(
                "conflict",
                collection,
                page_id,
                left.title or right.title,
                f"both moved — Notion {notion_at or '?'}, Markdown {markdown_at or '?'}; "
                f"{'Notion' if wins_notion else 'Markdown'} wins ({self.conflict})",
            )
        elif moved_notion:
            wins_notion = True
        elif moved_markdown:
            wins_notion = False
        else:
            return

        if wins_notion:
            self._write_file(collection, left)
            report.note("notion→markdown", collection, page_id, left.title)
            marks.agreed(page_id, notion_at, _now())
        else:
            self._push(collection, database, page_id, right, report)
            marks.agreed(page_id, _now(), markdown_at)

    @staticmethod
    def _carried(page: Page, schema: dict[str, str]) -> dict[str, Any]:
        """The properties of a page that are worth writing on the other side.

        Those the target's schema declares, and only those: a column one board
        has and the other does not is not a value to invent, and an empty cell
        is not a value to carry — writing it would turn "this side says nothing"
        into "this side says nothing, on purpose".
        """
        values: dict[str, Any] = {}
        for name in schema:
            value = read(page, name)
            if value not in (None, "", []):
                values[name] = value
        return values

    def _write_file(self, collection: str, page: Page) -> None:
        """One Notion page, written down as the file that mirrors it."""
        page_id = _bare(page.id)
        values = self._carried(page, self.mirror.schema(collection))
        values[self.mirror.title_property(collection)] = page.title
        try:
            self.mirror.page(page_id)
        except StoreError:
            self.mirror.create_row(collection, page.title, values, page_id=page_id)
        else:
            self.mirror.update(collection, page_id, values)
        self.mirror.replace_markdown(page_id, self.primary.blocks_text(page.id))

    def _write_page(self, collection: str, database: str, page: Page) -> str:
        """One file, created as the Notion page that mirrors it. Returns its ID.

        The file then takes the identifier Notion chose. Notion's is the one
        that has to win: it is what a URL, a relation and every previous report
        already carry, whereas the file's own was drawn by this machine and is
        pointed at by nothing.
        """
        created = self.primary.create_row(
            database, page.title, self._carried(page, self.primary.schema(database))
        )
        body = self.mirror.blocks_text(_bare(page.id))
        if body.strip():
            self.primary.append_markdown(created, body)
        self.mirror.rename(collection, _bare(page.id), _bare(created))
        return _bare(created)

    def _push(
        self, collection: str, database: str, page_id: str, page: Page, report: Report
    ) -> None:
        """One file, carried onto the Notion page it mirrors."""
        values = self._carried(page, self.primary.schema(database))
        values[self.primary.title_property(database)] = page.title
        self.primary.update(database, page_id, values)
        body = self.mirror.blocks_text(page_id)
        if body.strip() != self.primary.blocks_text(page_id).strip():
            self.primary.replace_markdown(page_id, body)
        report.note("markdown→notion", collection, page_id, page.title)

    def _reconcile_context(self, space, settings, marks: Stamps, report: Report) -> None:
        """The standing context: one body, on both sides, no properties at all.

        Its Notion page is a row of the workspace rather than a row of a
        database, so it has no place in the walk above — and a file has no
        `edited` of its own once its frontmatter is gone, which `context.md` has
        no reason to carry. So the rule is the one that needs no timestamps: the
        side whose text is no longer what was agreed last time is the side that
        changed, and Notion wins when both did.
        """
        here = space.context.strip()
        there = self.mirror.context()
        if here == there:
            marks.agreed(CONTEXT, here, there)
            return
        moved_notion = not marks.seen(CONTEXT) or here != marks.notion(CONTEXT)
        moved_markdown = marks.seen(CONTEXT) and there != marks.markdown(CONTEXT)
        if moved_notion and moved_markdown:
            report.note(
                "conflict", CONTEXT, CONTEXT, "the standing context",
                f"both were rewritten; Notion wins ({self.conflict})",
            )
        if moved_notion:
            self.mirror.set_context(here)
            report.note("notion→markdown", CONTEXT, CONTEXT, "the standing context")
            marks.agreed(CONTEXT, here, here)
            return
        if space.context_page:
            self.primary.replace_markdown(space.context_page, there)
            report.note("markdown→notion", CONTEXT, CONTEXT, "the standing context")
        marks.agreed(CONTEXT, there, there)


def _bare(identifier: str) -> str:
    return str(identifier or "").replace("-", "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
