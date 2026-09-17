"""A ticket, and the work it becomes once a run has taken it on.

Two nouns and three readings of them, and nothing that does anything: this is
the bottom of the runner. Every module that does a piece of a run — claiming,
executing, delivering, answering — passes a `Ticket` or a `Job` to the next
one, so they have to live somewhere that none of those modules owns, or the
first one to import the second would be importing the whole run back.

`Ticket` is a Notion page read the way a run reads it; `Job` is that ticket
once a run has decided where it will happen — which branch, which worktree,
which session, in whose voice — and is filled in as the run learns the rest.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import agents, notion, progress
from .projects import Project


@dataclass
class Ticket:
    page: notion.Page

    @property
    def id(self) -> str:
        return self.page.id.replace("-", "")

    @property
    def title(self) -> str:
        return self.page.title or "(untitled ticket)"

    @property
    def url(self) -> str:
        return self.page.url


@dataclass
class Job:
    ticket: Ticket
    project: Project
    branch: str
    base: str
    workdir: Path
    body: str = ""
    session_id: str = ""
    log: Path | None = None
    session_home: Path | None = None
    model: str = ""
    agent: agents.Agent = field(default_factory=agents.Agent)
    comments: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    resumed: bool = False
    # The folded block this job's session wrote its steps into, once it has one.
    # Kept on the job because what goes in it is decided after the session ends:
    # a run that failed files its trace there rather than in the report.
    live: progress.Live | None = None


def short_id(page_id: str) -> str:
    """Eight characters that actually tell two tickets apart.

    Notion page IDs are time-ordered: two tickets created the same day share a
    long *prefix*. Taking the first eight gave both of the first two tickets
    written for this tool the same short id — which would have had them fight
    over one scratch directory. The tail is where the entropy is.
    """
    return page_id.replace("-", "")[-8:]


def is_blank(body: str) -> bool:
    """A ticket body that says nothing, template headings included.

    A database template fills a new page with empty headings. They are not
    blank text, so they would travel into the prompt as noise and — worse —
    stop the "everything is in the title" fallback from firing on a ticket
    whose whole content is its title.
    """
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and set(stripped) != {"-"}:
            return False
    return True


def slugify(text: str, limit: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:limit].rstrip("-")) or "ticket"
