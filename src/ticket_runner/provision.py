"""Building the Notion side of the runner from one page link.

Setting this up by hand means four databases, a dozen properties, two relations
and six status options spelled *exactly* as the configuration spells them. Get
one character wrong and the runner finds nothing, for ever, without saying why.
So the machine does it: you share one page with the integration, and everything
under it is created here.

Two constraints of the API shape everything below.

- **A `status` property cannot be created.** Notion only offers that type in its
  own interface, and neither creating one nor editing its options is possible
  from the API. So the board is given a `select` instead, which the runner has
  always read the same way: the filter is built from the declared type, and
  `_encode` writes both. The column looks slightly different in Notion, and
  nothing else changes.
- **A relation needs its target to exist.** Projects and Agents are therefore
  created before Tickets, which is the only ordering rule in this file.

Everything is *find or create*. Running `init` twice is not an error and does
not duplicate anything: the second run adds what a previous version did not
know how to create, which is what makes this the migration command too. A column
somebody retyped on purpose is never overruled — only what is missing is added.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import notion
from .config import PRIORITIES, Notion

# The board, left to right, and the colour that says what a column means.
_STATUS_COLOURS = {
    "ready": "blue",
    "running": "yellow",
    "review": "purple",
    "validated": "pink",
    "done": "green",
    "failed": "red",
    "blocked": "orange",
}

_PRIORITY_COLOURS = {"Urgent": "red", "High": "orange", "Normal": "default", "Low": "gray"}

# What `claude --model` accepts. A select rather than free text: the whole point
# of the column is to pick without remembering the spelling.
MODELS = ("opus", "sonnet", "haiku")

DIRECTORY = "ticket-runner"

CONTEXT_SEED = """Whatever is written here reaches **every** ticket, before the project's
brief and before the ticket itself. It is what makes an answer sound like you
rather than like nobody.

Worth writing down:

- who you are, and what the team does
- the stack, the conventions, the things never to do
- how you like things written — length, tone, language

Keep it to one screen. You pay for it on every single ticket.
"""

DEMO_TICKET = """This ticket was created by `ticket-runner init` so you can watch the
runner work once, without setting anything else up.

Move it to **{ready}** and wait for the next pass. It has no project, so it
takes the document path: no repository is touched, and the answer is written
back into this page, below this text.

**What to do:** introduce ticket-runner in a short paragraph, as if to someone
who has never heard of it.

Delete this page whenever you like.
"""


@dataclass
class Report:
    """What the run did, in the order it did it — printed back to the user."""

    workspace: str = ""
    tickets: str = ""
    steps: list[tuple[str, str]] = field(default_factory=list)

    def note(self, verb: str, what: str) -> None:
        self.steps.append((verb, what))

    @property
    def created(self) -> int:
        return sum(1 for verb, _ in self.steps if verb == "created")


# -- the shapes --------------------------------------------------------------


def _select(options, colours: dict[str, str] | None = None) -> dict:
    return {
        "select": {
            "options": [
                {"name": name, "color": (colours or {}).get(name, "default")}
                for name in options
            ]
        }
    }


def status_options(settings: Notion) -> list[dict]:
    """The status column's options, in board order, without duplicates.

    A configuration is free to point two states at one column — `failed` and
    `blocked` on a single "Needs you", `review` and `done` on a single "Done" —
    and Notion refuses a select that lists the same option twice. A file that
    names its columns without naming `validated` is one of those: it points at
    `review`, and the board simply has no validated column.
    """
    seen: dict[str, str] = {}
    for key in ("ready", "running", "review", "validated", "done", "failed", "blocked"):
        name = settings.state(key).strip()
        if name and name not in seen:
            seen[name] = _STATUS_COLOURS[key]
    return [{"name": name, "color": colour} for name, colour in seen.items()]


def projects_schema() -> dict:
    """A project is a name, and where its code lives — if it has any.

    A project with neither Repository nor Path is not a mistake: its tickets
    produce documents, written back into Notion.
    """
    return {
        "Name": {"title": {}},
        "Repository": {"rich_text": {}},
        "Path": {"rich_text": {}},
    }


def agents_schema(settings: Notion) -> dict:
    """An agent is a page — its body is the role. The columns are the exceptions."""
    return {
        "Name": {"title": {}},
        settings.prop("model"): _select(MODELS),
    }


def tickets_schema(settings: Notion, projects: str = "", agents: str = "") -> dict:
    schema: dict = {
        "Name": {"title": {}},
        settings.prop("status"): {"select": {"options": status_options(settings)}},
        settings.prop("agent"): {"rich_text": {}},
        # What the session is doing right now. Written every few seconds while
        # the ticket runs, cleared when it ends — a board column that moves.
        settings.prop("progress"): {"rich_text": {}},
        settings.prop("session"): {"url": {}},
        settings.prop("pull_request"): {"url": {}},
        settings.prop("model"): _select(MODELS),
        settings.prop("priority"): _select(PRIORITIES, _PRIORITY_COLOURS),
        settings.prop("cost"): {"number": {"format": "dollar"}},
        settings.prop("duration"): {"number": {"format": "number"}},
        settings.prop("due"): {"date": {}},
    }
    # Single-property relations: the ticket points at its project, and the
    # projects database is not given a back-reference it would never read.
    if projects:
        schema[settings.prop("project")] = {
            "relation": {"database_id": projects, "type": "single_property"}
        }
    if agents:
        schema[settings.prop("role")] = {
            "relation": {"database_id": agents, "type": "single_property"}
        }
    return schema


def missing_properties(existing: dict[str, str], wanted: dict) -> dict:
    """What `wanted` declares that the database does not have yet.

    By name only. A property that exists under a type nobody expected is left
    exactly as it is — `doctor` is what says so, and overwriting a column
    somebody built on is not provisioning, it is damage.
    """
    return {name: shape for name, shape in wanted.items() if name not in existing}


def offered(database: dict, name: str) -> set[str]:
    """The options a select or status column already carries."""
    prop = (database.get("properties") or {}).get(name) or {}
    kind = prop.get("type", "")
    return {option.get("name") for option in (prop.get(kind) or {}).get("options", [])}


def missing_options(database: dict, name: str, wanted: list[dict]) -> dict:
    """The select options a column is missing, merged onto the ones it has.

    Notion replaces the whole option list on a PATCH, so the existing ones are
    sent back with it — otherwise adding "Blocked" to a board would silently
    delete every other column.
    """
    prop = (database.get("properties") or {}).get(name) or {}
    if prop.get("type") != "select":
        return {}
    current = (prop.get("select") or {}).get("options") or []
    known = {option.get("name") for option in current}
    absent = [option for option in wanted if option["name"] not in known]
    if not absent:
        return {}
    kept = [
        {"name": option.get("name"), "color": option.get("color", "default")}
        for option in current
    ]
    return {name: {"select": {"options": kept + absent}}}


# -- doing it ----------------------------------------------------------------


def _database_in(
    client: notion.Client, page: str, title: str, schema: dict, report: Report
) -> str:
    """The database of a workspace row, created or completed. Returns its ID."""
    # Any database in the row, not only one under the expected title: that is
    # what `resolve_database` will hand the runner at read time, so completing a
    # different one would leave the board with two and the runner reading the
    # one this never touched.
    existing = client.child_databases(page)
    database = existing.get(title) or next(iter(existing.values()), "")
    if not database:
        database = client.create_database(page, title, schema)
        report.note("created", f"“{title}” database, {len(schema)} properties")
        return database

    absent = missing_properties(client.schema(database), schema)
    if absent:
        client.add_properties(database, absent)
        report.note("completed", f"“{title}” — added {', '.join(sorted(absent))}")
    else:
        report.note("kept", f"“{title}” database")
    return database


def _row(client: notion.Client, directory: str, settings: Notion, key: str, report: Report) -> str:
    """The workspace row for `key`, by any name it has ever had, else created."""
    rows = {page.title.strip().lower(): page.id for page in client.query(directory)}
    for candidate in settings.page_aliases(key):
        page = rows.get(candidate.strip().lower())
        if page:
            return page
    title = settings.page(key)
    page = client.create_row(directory, title)
    report.note("created", f"“{title}” page")
    return page


def provision(
    client: notion.Client,
    settings: Notion,
    page_id: str,
    *,
    directory: str = DIRECTORY,
    demo: bool = True,
) -> Report:
    """Create everything the runner needs under `page_id`, and say what was done.

    The page must already be shared with the integration — that is the one step
    no API can take, since an integration cannot grant itself access. Everything
    created below inherits that access, which is also what makes the relations
    legal: a relation's target has to be reachable by the same integration.
    """
    report = Report()

    databases = client.child_databases(page_id)
    workspace = databases.get(directory)
    if workspace:
        report.note("kept", f"“{directory}” workspace")
    else:
        workspace = client.create_database(page_id, directory, {"Name": {"title": {}}})
        report.note("created", f"“{directory}” workspace")
    report.workspace = workspace

    # Order matters exactly once: a relation cannot name a database that does
    # not exist yet, so the two targets are built before the tickets.
    projects = _database_in(
        client, _row(client, workspace, settings, "projects", report),
        settings.page("projects"), projects_schema(), report,
    )
    agents = _database_in(
        client, _row(client, workspace, settings, "agents", report),
        settings.page("agents"), agents_schema(settings), report,
    )
    tickets = _database_in(
        client, _row(client, workspace, settings, "tickets", report),
        settings.page("tickets"), tickets_schema(settings, projects, agents), report,
    )
    report.tickets = tickets

    # A board that predates a status gets it added rather than being told to go
    # and type it in — the one place where an existing column is widened.
    board = client.database(tickets)
    widened = missing_options(board, settings.prop("status"), status_options(settings))
    if widened:
        client.add_properties(tickets, widened)
        names = [option["name"] for option in widened[settings.prop("status")]["select"]["options"]]
        report.note("completed", f"“{settings.prop('status')}” — options: {', '.join(names)}")
    else:
        # A real `status` property is the blind spot: its options cannot be
        # added from the API at all. Saying so here beats letting the user
        # discover it at the end of the first ticket that tries to write one.
        absent = {option["name"] for option in status_options(settings)} - offered(
            board, settings.prop("status")
        )
        if absent:
            report.note(
                "by hand",
                f"“{settings.prop('status')}” cannot be widened through the API — "
                f"add in Notion: {', '.join(sorted(absent))}",
            )

    context = _row(client, workspace, settings, "context", report)
    if not client.blocks_text(context).strip():
        client.append_markdown(context, CONTEXT_SEED)
        report.note("created", f"“{settings.page('context')}” — a starting point to rewrite")

    if demo and not client.query(tickets):
        # Deliberately left with no status: the runner picks up nothing, and the
        # first Claude session of a fresh install is one the user asked for.
        ticket = client.create_row(tickets, "Introduce ticket-runner")
        client.append_markdown(ticket, DEMO_TICKET.format(ready=settings.state("ready")))
        report.note("created", "a demonstration ticket, waiting for you to start it")

    return report
