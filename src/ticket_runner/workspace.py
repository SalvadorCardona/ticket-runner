"""Finding what the runner needs from one workspace.

Naming the tickets database works, but it means one configuration key per
database — and the day a second one matters, a third key, and a fourth. A Notion
workspace is already a directory: one database whose rows are the master pages,
each holding its own inline database. So the configuration names **the directory
once**, and everything else is found by the title of a row.

Two rules keep that from becoming brittle:

- **only the tickets database is required.** A workspace missing its context page
  runs exactly as before — the runner says so and carries on. Nothing here is
  worth failing a ticket over except the one database that decides what to work
  on;
- **an explicit `tickets_database` still wins.** The workspace is a convenience,
  not a migration: a configuration written before it exists keeps working
  untouched, and pointing at one database from a workspace you would rather not
  share whole stays possible.

All of which is *Notion's* shape, and that is why `from_notion` is named for it:
a Markdown board has no directory and no rows, it has four directories on disk.
`resolve` therefore asks the store, and each store answers in its own terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import notion
from .config import Notion


@dataclass
class Workspace:
    tickets: str = ""
    projects: str = ""
    agents: str = ""
    # What comes back on its own. Absent means nothing repeats here, which is
    # not a fault: the row is optional exactly as the other two are.
    schedules: str = ""
    context: str = ""
    # The page the context was read off, so that it can be written back: the
    # console edits it as a text area, and a text you can read but not save is
    # worse than one you cannot see. Empty where there is no such page.
    context_page: str = ""
    rows: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _index(client: notion.Client, database_id: str) -> dict[str, str]:
    """{row title: page id}, spelled the way Notion spells it.

    Kept as written rather than folded, because these titles are read back to
    you when a row is missing — and a list of what you actually have is only
    useful if it looks like what you see on the board.
    """
    index: dict[str, str] = {}
    for page in client.query(database_id):
        title = page.title.strip()
        if title:
            index.setdefault(title, page.id)
    return index


def resolve(backend, settings: Notion) -> Workspace:
    """The databases and the standing context, whichever store holds them.

    One line, and it is the seam: every caller used to reach for Notion's own
    layout, and now asks the board it was handed what it is made of.
    """
    return backend.workspace(settings)


def from_notion(client: notion.Client, settings: Notion) -> Workspace:
    """The databases and the standing context, from a Notion workspace.

    Raises NotionError when the tickets database cannot be reached: that one is
    what a run is made of, and continuing without it would only mean reporting
    "nothing to do" forever.
    """
    if not settings.workspace:
        return Workspace(tickets=client.resolve_database(settings.tickets_database))

    directory = client.resolve_database(settings.workspace)
    rows = _index(client, directory)
    space = Workspace(rows=rows)

    def row(key: str) -> str:
        """The page a configured name points at, a capital letter notwithstanding.

        The title is something you typed twice — once in Notion, once in the
        configuration — so a stray capital is not a reason to say the page does
        not exist. Names the runner used to ship with are tried after the
        current one, so a board built before they were settled still resolves.
        """
        for candidate in settings.page_aliases(key):
            wanted = candidate.strip().lower()
            page = next((page for title, page in rows.items() if title.lower() == wanted), "")
            if page:
                return page
        return ""

    if settings.tickets_database:
        space.tickets = client.resolve_database(settings.tickets_database)
    elif page := row("tickets"):
        space.tickets = client.resolve_database(page)
    else:
        found = ", ".join(f"“{title}”" for title in sorted(rows)) or "nothing"
        raise notion.NotionError(
            f"no page named “{settings.page('tickets')}” in the workspace — found: {found}\n"
            "  rename the row, or set notion.pages.tickets to what yours is called"
        )

    # From here on, a failure is a missing feature, never a failed run.
    for key in ("projects", "agents", "schedules"):
        if page := row(key):
            try:
                setattr(space, key, client.resolve_database(page))
            except notion.NotionError as error:
                space.warnings.append(f"{key} database unreadable: {_first_line(error)}")

    if page := row("context"):
        space.context_page = page
        try:
            space.context = client.blocks_text(page)
        except notion.NotionError as error:
            space.warnings.append(f"context page unreadable: {_first_line(error)}")
        else:
            if not space.context.strip():
                space.warnings.append(
                    f"the “{settings.page('context')}” page is empty — "
                    "nothing about you reaches the agent"
                )
    else:
        space.warnings.append(
            f"no “{settings.page('context')}” page in the workspace — "
            "the agent starts every ticket knowing nothing about you"
        )

    return space


def _first_line(error: Exception) -> str:
    return str(error).splitlines()[0]
