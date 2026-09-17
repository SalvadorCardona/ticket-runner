"""Everything between a ticket coming off the board and a session starting.

Locate the project, read the body, give the page a title if it has none, draw
the branch and the directory the work will happen in, and *claim* the ticket by
moving it to "in progress". What comes out is a `Job`: the ticket, plus every
decision a session needs taken before it can be started.

Claiming is why this happens in the pass's own thread and nowhere else — see
`Runner._work`. Two tickets prepared side by side would race over the same
repository index, and a ticket not claimed before it is worked on is a ticket
the next tick of the timer would happily pick up as well.

A ticket that cannot be used is failed here rather than carried further: no
project anybody can find, a body Notion will not hand over, a page with neither
title nor content. Each of them returns `None`, and the pass goes on to the
next ticket.
"""

from __future__ import annotations

import re
import shutil

from . import agents, git, naming, notion, session, state
from . import voice as voice_module
from .base import Base
from .config import state_dir
from .projects import Project
from .ticket import Job, Ticket, is_blank, short_id, slugify


# What a session identifier looks like — `session.new_id` draws a UUID4. Matched
# rather than trusted because the Session column is a column like any other: a
# cell somebody typed into must not become a `claude --resume` of its own.
_SESSION_ID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


class Preparation(Base):
    """A ticket turned into the job a session can be started on."""

    def prepare(self, ticket: Ticket) -> Job | None:
        """Locate the project and claim the ticket. None if it is unusable."""
        relation = notion.read(ticket.page, self.config.notion.prop("project")) or []
        if not relation:
            # No project at all is not an error: it is the plainest possible
            # document ticket. "Draft me an email", "summarise this" — there is
            # nothing to commit and nowhere to commit it, so the answer goes
            # back into the page, exactly as for a project without a repository.
            project = Project(name="", path=None)
        else:
            try:
                # The one caller allowed to fetch a repository that is declared
                # but not on this machine: a ticket about to run needs the
                # clone to exist, and a project created from its GitHub link
                # alone has never had one made. A dry run stays a dry run.
                project = self.resolver.resolve(
                    self.client, relation[0], clone=not self.dry_run
                )
            except (LookupError, notion.NotionError) as error:
                self._fail(ticket, self.voice.say("no-project"), str(error), blocked=True)
                return None

        short = short_id(ticket.id)
        try:
            body = self.client.blocks_text(ticket.page.id)
        except notion.NotionError as error:
            self._fail(ticket, self.voice.say("unreadable"), str(error))
            return None
        if is_blank(body):
            body = ""
            if not ticket.page.title.strip():
                self._fail(
                    ticket,
                    self.voice.say("empty-ticket"),
                    self.voice.say("empty-ticket-detail"),
                    blocked=True,
                )
                return None
        elif not ticket.page.title.strip() and not self.dry_run:
            # Named before the branch is drawn, since the branch is made of the
            # title. Only a page whose title is empty ever gets here, so the
            # common case costs nothing — and a dry run writes nowhere.
            self._name(ticket, body, short)

        stem = f"{slugify(project.name, 24)}-{short}"
        if project.is_code:
            base = self.config.runner.base_branch or git.default_branch(project.path)
            branch = f"{self.config.runner.branch_prefix}{slugify(ticket.title)}-{short}"
            workdir = state_dir() / "worktrees" / stem
        else:
            # No repository: an empty scratch directory, and the answer goes
            # back into the Notion page instead of into a pull request.
            base, branch = "", ""
            workdir = state_dir() / "scratch" / stem

        # Both are optional and neither can fail a ticket: a database with no
        # Agent column reads as no agent, and unreadable comments as none.
        role = notion.read(ticket.page, self.config.notion.prop("role")) or []
        agent = (
            agents.resolve(self.client, role[0], self.config.notion.prop("model"))
            if role
            else agents.Agent()
        )

        # A ticket coming back out of the waiting column already has a session,
        # stopped mid-sentence by a spent window rather than finished. Carrying
        # it on costs a message where starting over costs the whole ticket again
        # — and the session is what remembers the half of the work that is not
        # in a commit yet. Anything else gets a fresh identifier, as ever.
        carried = self._carried_session(ticket)
        job = Job(
            ticket,
            project,
            branch,
            base,
            workdir,
            body,
            session_id=carried or session.new_id(),
            resume=bool(carried),
            log=state.log_file(short),
            model=str(notion.read(ticket.page, self.config.notion.prop("model")) or ""),
            agent=agent,
            comments=self.discussion(ticket),
        )
        where = f"{project.path} · {branch}" if project.is_code else "document → Notion"
        said = f" · {len(job.comments)} comment(s)" if job.comments else ""
        role = f" · as {agent.name}" if agent else ""
        self.say(f"  → {ticket.title}\n    {project.name or 'no project'} · {where}{role}{said}")
        # `cloned` says the repository was not here until a minute ago — worth a
        # line, since the ticket is running on a folder nobody made by hand.
        # `note` says it was found by a way of last resort: the ticket runs, and
        # the ticket's comment says which declaration on the project page to
        # correct — or the page stays wrong for as long as the fallback works.
        for line in (project.cloned, project.note):
            if line:
                self.say("    · " + line)
                job.notes.append(line)
        if not self.dry_run:
            # The session identifier is written now, not at the end: a ticket
            # still in progress is exactly the one you want to look into, and
            # `claude --resume <id>` replays it even while it runs.
            self._set(
                ticket,
                **{
                    self.config.notion.prop("status"): self.config.notion.state("running"),
                    self.config.notion.prop("agent"): self.agent_label,
                    self.config.notion.prop("session"): self._session_value(
                        job.session_id, project.path
                    ),
                },
            )
        return job

    def _carried_session(self, ticket: Ticket) -> str:
        """The session to carry on for this ticket, when there is one to carry on.

        Only out of the waiting-for-credit column, and that narrowness is the
        point: everywhere else a ticket runs again, the Session column holds a
        conversation that *ended* — reported on, commented, answered — and
        resuming it would have the agent argue with its own verdict. A window
        that closed mid-sentence is the one case where the conversation is
        genuinely unfinished, and `park` empties the cell for the tickets in
        that column that were never started at all.

        Read back through whichever shape `_session_value` wrote: a deep link on
        a URL column, the bare identifier on a text one. Anything that is not an
        identifier — a link somebody pasted, an emptied cell — reads as none,
        and the ticket opens a session of its own.
        """
        column = self.config.notion.state("waiting")
        status = str(notion.read(ticket.page, self.config.notion.prop("status")) or "")
        if status != column or column == self.config.notion.state("ready"):
            return ""
        raw = str(notion.read(ticket.page, self.config.notion.prop("session")) or "").strip()
        if "://" in raw:
            raw = raw.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        return raw if _SESSION_ID.fullmatch(raw) else ""

    def _name(self, ticket: Ticket, body: str, short: str) -> None:
        """Give a nameless ticket a title, and write it on the page.

        Into Notion rather than into this run's memory alone: the board has to
        show it too, or the page stays anonymous for whoever reads it back. And
        the page is what the runner then works from, so the branch, the report
        and the pull request all carry the same name.

        Never a reason to fail a ticket. A session that will not start, an
        answer that says nothing, a Notion that refuses the write: each of them
        is one line in the journal, and the ticket runs under the default
        label as it did before. The title is only kept once Notion has taken
        it — a branch named after something the board does not show would be a
        worse outcome than a ticket with no name.
        """
        title = ""
        workdir = state_dir() / "scratch" / f"name-{short}"
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            outcome = session.run(
                naming.prompt(body),
                cwd=workdir,
                log=state.log_file(f"{short}-name"),
                model=self.config.runner.model,
                # It reads one page and answers one line: the mode a
                # conversation runs in is more than it needs.
                permission_mode=self.config.runner.reply_permission_mode,
                timeout_minutes=naming.TIMEOUT_MINUTES,
                environment=self.environment,
            )
            if outcome.ok:
                title = naming.clean(outcome.answer)
            if not title:
                self.say("  ! the naming session said nothing usable — reading the content")
        except (OSError, ValueError) as error:
            self.say(f"  ! the ticket could not be named by a session: {voice_module.line(error)}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        title = title or naming.fallback(body)
        if not title:
            return
        try:
            self.client.update(
                self.database,
                ticket.page.id,
                {self.client.title_property(self.database): title},
            )
        except notion.NotionError as error:
            self.say(f"  ! the title could not be written to Notion: {voice_module.line(error)}")
            return
        ticket.page.title = title
        self.say(f"  · named “{title}” — the ticket had none of its own")
