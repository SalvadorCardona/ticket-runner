"""Reading the board, and the tidyings a pass does before reading it.

Everything a pass wants to know before it starts working: which tickets are to
be run now, which are waiting for their date, which have been answered since
the last run, and which are still marked as taken by a run that is no longer
alive.

One rule holds the module together: **a date on a ticket means "not before
this moment", wherever it is written.** `_moment` is the single reading of it,
and the ready column, the validated column and the calendar all ask that one
question — two readings of a date that drifted apart would be a bug nobody
would ever find.

`reconcile`, `sweep` and `close_merged` write, and belong here anyway: they say
what the board *should* have said, from what the other board, this board and
GitHub already know, and a pass runs them at its top precisely so that what it
reads next is true.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import conversation, git, state, store
from . import voice as voice_module
from .base import Base
from .config import PRIORITIES
from .projects import Project
# The one reading of a Notion date in the project. It lives beside the calendar
# because a date on a ticket and a date on a schedule mean the same thing, and
# two readings of them that drift apart is a bug nobody would ever find.
from .schedules import scheduled_for
from .ticket import Ticket


class Board(Base):
    """What a run knows of the board before it works on it."""

    def _moment(self, ticket: Ticket) -> datetime | None:
        """When this ticket may be acted on, or `None` if it carries no date.

        The one reading of the date property. Two columns honour it — ready,
        where it holds the work back, and validated, where it holds back the
        merge or the publication — and they must not drift apart on what a date
        means.
        """
        return scheduled_for(store.read(ticket.page, self.config.notion.prop("due")))

    def queue(self) -> tuple[list[Ticket], list[tuple[Ticket, datetime]]]:
        """The tickets to run now, and those waiting for their date.

        Two ways in: the ready column, and a ticket the runner already handled
        that has been commented on since (see `woken`). Both are ranked and
        held back by their date the same way — once a ticket is to be run,
        what put it there changes nothing.

        A ticket carrying a date is **scheduled**, not merely deadlined: it is
        left alone until that moment comes. Which is the only reading that means
        anything here — a ticket without a date starts within seconds of being
        made ready, so a date can only be there to say "not yet".

        Among the tickets that may run, order settles who goes first when more
        are ready than `max_concurrent` allows: what the credit interrupted
        before what was never begun, then priority, then the one whose date
        passed longest ago, then age. Interrupted first because it is the one
        already half done — its branch carries commits, its session can be
        picked back up, and leaving it behind a fresh ticket is how a board
        spends the returning credit on starting things rather than on finishing
        them. Age last, so that nothing is starved by a steady trickle of newer
        work.
        """
        tickets = [Ticket(page) for page in self.client.query(self.database, self._ready_filter())]
        tickets += self.woken()
        interrupted = self.parked(tickets)
        priorities = {name: index for index, name in enumerate(PRIORITIES)}
        default = priorities.get("Normal", len(PRIORITIES))
        now = datetime.now().astimezone()

        eligible: list[Ticket] = []
        waiting: list[tuple[Ticket, datetime]] = []
        moments: dict[str, float] = {}
        for ticket in tickets:
            moment = self._moment(ticket)
            if moment and moment > now:
                waiting.append((ticket, moment))
                continue
            moments[ticket.id] = moment.timestamp() if moment else float("inf")
            eligible.append(ticket)

        def rank(ticket: Ticket) -> tuple[int, int, float, str]:
            value = store.read(ticket.page, self.config.notion.prop("priority"))
            return (
                0 if ticket.id in interrupted else 1,
                priorities.get(str(value), default),
                moments[ticket.id],
                ticket.page.raw.get("created_time", ""),
            )

        return sorted(eligible, key=rank), sorted(waiting, key=lambda pair: pair[1])

    def ready(self) -> list[Ticket]:
        return self.queue()[0]

    def _ready_filter(self) -> dict:
        status_property = self.config.notion.prop("status")
        kind = self.client.schema(self.database).get(status_property, "status")
        return {"property": status_property, kind: {"equals": self.config.notion.state("ready")}}

    def _woken_filter(self) -> dict:
        """Every status but the ones that already speak for a ticket.

        Ready is on its way, running is in flight, in review is waiting on a
        merge, validated is about to be carried out, and done is done: a comment
        on a ticket that came back with its pull request is a conversation about
        the work, not a request to do it again. What is left is where a run
        leaves a ticket it could not finish — which is precisely where an answer
        is expected.
        """
        status_property = self.config.notion.prop("status")
        kind = self.client.schema(self.database).get(status_property, "status")
        settled = {
            self.config.notion.state(key)
            for key in ("done", "review", "validated", "ready", "running")
        }
        return {
            "and": [
                {"property": status_property, kind: {"does_not_equal": value}}
                for value in sorted(settled)
            ]
        }

    def waiting_flag(self) -> str:
        """The checkbox a ticket waits for credit under, or "" without one.

        Optional, like every column past the first few, and asked of the schema
        rather than assumed: a board built before it has no such property, and
        the credit then stops the runner exactly as it did before — silently,
        with the tickets left where they were and nothing on the board to say
        why. Which is the whole argument for a property over a status option: an
        attribute *can* be added to an existing database through the API, so
        running `init` again is enough, where an eighth column would have had to
        be typed into Notion by hand.

        The type is checked too. A "Waiting for credit" that somebody made a
        text column is not this: writing `True` into it would read as the word
        "True" on the board, and querying it would fail the whole pass.
        """
        name = self.config.notion.prop("waiting")
        try:
            return name if self.client.schema(self.database).get(name) == "checkbox" else ""
        except store.StoreError:
            return ""

    def parked(self, tickets: list[Ticket]) -> set[str]:
        """Which of these the credit stopped, rather than never started.

        Read off the tickets already in hand instead of by a query of its own:
        a parked ticket never left its column, so the ready one brought it back
        like any other. That is the attribute earning its keep — an eighth column
        meant a second query per pass, and a board where a ticket disappeared
        from under you between two passes.
        """
        flag = self.waiting_flag()
        if not flag:
            return set()
        held = {ticket.id for ticket in tickets if store.read(ticket.page, flag)}
        # Said only by a pass that can act on it. A wait lasts hours, and a pass
        # that will start nothing announcing what it is not starting would be
        # the whole of the journal by the time the window rolls over.
        if held and not self.under_reserve():
            self.say(f"  ▶ {len(held)} ticket(s) waiting for credit — picked up first")
        return held

    def woken(self) -> list[Ticket]:
        """Tickets this runner has already reported on, and answered since.

        A comment is how a ticket is answered: a run that ends `blocked` leaves
        its question on the page, and the reply lands underneath. That reply is
        now the whole gesture — no need to also move the ticket back to the
        ready column. It rejoins the queue and is claimed like any other, so it
        goes to "in progress" for as long as the new run lasts.

        Narrow on purpose, because not every comment is an instruction. A
        ticket wakes only if this runner reported on it and someone else has
        had the last word since: a ticket it never touched belongs to a
        conversation of yours, and one handled by another host is that host's
        to pick up. The report the next run posts is also what closes the
        ticket again — without it, the same comment would wake it forever.
        """
        woken: list[Ticket] = []
        for page in self.client.query(self.database, self._woken_filter()):
            ticket = Ticket(page)
            if not self._answered(ticket):
                continue
            self.say(f"  ↻ {ticket.title} — answered in a comment, picked up again")
            woken.append(ticket)
        return woken

    def _answered(self, ticket: Ticket) -> bool:
        """Did someone have the last word on a ticket this runner reported on?

        Two kinds of comment are not that last word. What the runner itself said
        in the thread since — an answer it gave is not an instruction it was
        given. And a comment that *names* it: naming it is how you ask it to
        speak rather than to work, and `converse` is what picks that up.
        Everything else under a report is still an answer to a question a run
        asked, and still puts the ticket back in the queue — an answer relayed
        from Telegram or Slack included, which wears the runner's token and is
        nonetheless yours.

        Which machine reported is read off the board's Agent column rather than
        off the comment: reports open on a verdict now, not on a host, and the
        column is where the host was always written down anyway.
        """
        agent = str(store.read(ticket.page, self.config.notion.prop("agent")) or "")
        if agent and agent != self.agent_label:
            return False
        try:
            comments = self.comments(ticket.page.id)
        except store.StoreError:
            # Comments the integration cannot read already cost a ticket its
            # discussion; they are not going to become a reason to run it again.
            # `discussion` is where that is said out loud, once per ticket.
            return False
        reports = [
            index
            for index, comment in enumerate(comments)
            if voice_module.is_report(comment.text)
        ]
        if not reports:
            return False
        me = self.myself()
        # What the runner has said in the comments since its report is not an
        # answer to it — that is the whole point of being able to talk here.
        since = [
            comment
            for comment in comments[reports[-1] + 1 :]
            if not conversation.ours(comment, me)
        ]
        if not since:
            return False
        return not conversation.addressed(since[-1].text, self.spellings())

    def myself(self) -> str:
        """The integration's own user ID, or "" if Notion would not say.

        Asked once per run, and never a reason to fail one: without it the
        runner falls back on recognising its own signature, which is enough to
        tell a report from an answer and not enough to answer comments — see
        `converse`.
        """
        if self._me is None:
            try:
                self._me = self.client.me()
            except store.StoreError as error:
                self._me = ""
                self._identity_error = voice_module.line(error)
        return self._me

    def spellings(self) -> tuple[str, ...]:
        """Every way of naming the runner in a comment, resolved once per run.

        The integration's own name comes from Notion and a run must not fail for
        want of it: without it, the configured word and the built-in aliases are
        still every name anybody types.
        """
        if self._spellings is None:
            try:
                integration = self.client.my_name()
            except store.StoreError:
                integration = ""
            self._spellings = conversation.names(self.config.notion.mention, integration)
        return self._spellings

    def _project_of(self, ticket: Ticket) -> Project:
        """The ticket's project, or none at all. Never a failure: a conversation
        about a ticket whose repository has moved is still a conversation."""
        relation = store.read(ticket.page, self.config.notion.prop("project")) or []
        if not relation:
            return Project(name="", path=None)
        try:
            return self.resolver.resolve(self.client, relation[0])
        except (LookupError, store.StoreError):
            return Project(name="", path=None)

    def _body(self, ticket: Ticket) -> str:
        try:
            return self.client.blocks_text(ticket.page.id)
        except store.StoreError:
            return ""

    def fetch_one(self, reference: str) -> Ticket:
        page_id = reference.strip()
        if "://" in page_id:
            page_id = page_id.split("?")[0].rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[-1]
        return Ticket(self.client.page(page_id.replace("-", "")))

    def reconcile(self) -> None:
        """Carry across whatever changed on the other board. Only in `both` mode.

        At the top of a pass, before anything is read: a ticket you dragged in
        Notion and a ticket you edited in a file have to be the same ticket by
        the time the queue is built, or the pass would act on half the truth.

        Never a reason to fail a pass. A Notion that will not answer, a
        directory that will not be written to: both are one line, and the run
        goes on against the board it *can* read — which is Notion, since that is
        what a mirror reads from.
        """
        from . import sync as sync_module

        if not isinstance(self.client, sync_module.Mirror):
            return
        if self.dry_run or not self.config.storage.on_every_pass:
            return
        report = self.client.synchronise(self.config.notion)
        for problem in report.problems:
            self.say(f"  ! sync: {problem}")
        for entry in report.conflicts:
            self.say(f"  ⇄ {entry.title or entry.page} — {entry.detail}")
        for entry in report.deletions:
            self.say(f"  ⌫ {entry.title or entry.page} — {entry.detail}")
        if carried := report.carried:
            self.say(f"  ⇄ {len(carried)} page(s) carried across")

    def sweep(self) -> int:
        """Put back tickets a dead runner left claimed.

        A run holds an exclusive lock, so at the start of a run no other run of
        ours can be in flight — any ticket still marked "in progress" under this
        host's name was therefore abandoned, by a reboot, a `systemctl stop`, or
        a crash. It goes back to ready rather than staying stuck for good.

        Back to ready, but **not** when it was claimed for a publication. A
        ticket taken from the validated column was work somebody had already
        accepted; re-doing it is not recovery, and re-publishing it is the one
        mistake this must not make — the post may well have gone out just before
        the machine died. So it goes to blocked with the question spelled out,
        and moving it back to validated is a click if it never went out.
        Where it was taken from is remembered locally, which is enough: only
        this host's own claims are ever recovered here.

        A two-minute grace covers clock skew, and a ticket claimed by another
        machine is left alone: only this host can know its own runs are over.
        """
        status_property = self.config.notion.prop("status")
        kind = self.client.schema(self.database).get(status_property, "status")
        running = self.client.query(
            self.database,
            {"property": status_property, kind: {"equals": self.config.notion.state("running")}},
        )
        recovered = 0
        for page in running:
            if store.read(page, self.config.notion.prop("agent")) != self.agent_label:
                continue
            edited = page.raw.get("last_edited_time", "")
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(edited)
            except ValueError:
                age = timedelta(days=1)
            if age < timedelta(minutes=2):
                continue
            ticket = Ticket(page)
            origin = state.claims().get(ticket.id, "")
            said = self.voice
            stopped = said.say("abandoned", minutes=said.minutes(age.total_seconds()))
            if origin and origin != self.config.notion.state("ready"):
                self.say(
                    f"  ↺ {ticket.title} — publication interrupted, asking rather than redoing"
                )
                interrupted = said.say("publication-interrupted", origin=origin)
                self._set(ticket, **{status_property: self.config.notion.state("blocked")})
                self._comment(
                    ticket,
                    said.report(
                        said.verdict("blocked", interrupted), said.say("answer-here")
                    ),
                )
                self._tell("blocked", ticket, "blocked", said.sentence(interrupted), ask=True)
                state.release(ticket.id)
                recovered += 1
                continue
            self.say(f"  ↺ {ticket.title} — claimed but no run alive, put back")
            self._set(ticket, **{status_property: self.config.notion.state("ready")})
            self._comment(
                ticket,
                said.report(
                    said.verdict("requeued", stopped), said.say("abandoned-requeued")
                ),
            )
            state.release(ticket.id)
            recovered += 1
        return recovered

    def close_merged(self) -> int:
        """Close the tickets whose pull request has been merged.

        A pull request is not the end of a ticket: it is a question asked of
        you. The ticket waits in "in review" until you answer it by merging —
        and merging is the answer, so nobody should have to move the ticket by
        hand afterwards.

        Asked at the start of every run rather than by a watcher of its own: the
        runner already wakes up on a timer, and a second one would only be a
        second thing to install, to enable and to forget. `interval_seconds` is
        the cadence of this too.

        A board whose `review` and `done` are the same status has nowhere for a
        ticket to wait, so there is nothing to look at.
        """
        review = self.config.notion.state("review")
        if review == self.config.notion.state("done"):
            return 0
        status_property = self.config.notion.prop("status")
        kind = self.client.schema(self.database).get(status_property, "status")
        pages = self.client.query(
            self.database, {"property": status_property, kind: {"equals": review}}
        )
        closed = 0
        for page in pages:
            url = str(store.read(page, self.config.notion.prop("pull_request")) or "")
            if (
                not url.startswith("http")
                or git.pull_request_state(url, self.config.github) != "MERGED"
            ):
                continue
            ticket = Ticket(page)
            said = self.voice
            self.say(f"  ✓ {ticket.title} — pull request merged, moved to done")
            self._set(ticket, **{status_property: self.config.notion.state("done")})
            self._comment(
                ticket, said.report(said.verdict("merged", said.pull_request(url)), url)
            )
            closed += 1
        return closed

    def _again(self, started: set[str]) -> list[Ticket]:
        """The tickets a freed place can be filled with, board read afresh.

        Read afresh on purpose: a pass that lasts hours must not run on the
        board it saw at the top of the hour. The comments are dropped so that a
        ticket answered mid-pass wakes up (see `woken`), and the answers typed
        in Telegram or Slack are written onto their tickets first, so a "yes"
        sent five minutes ago is in that very reading.

        `converse` is *not* called here, and that is deliberate rather than
        forgotten: answering a comment starts a session of its own, and doing it
        alongside a full pool would put more sessions in flight than
        `max_concurrent` allows. A question asked during a long pass is
        therefore still answered by the next pass — which is one ticket's worth
        of work away, not the whole board's, now that a place is filled as soon
        as it frees.

        And a Notion that will not answer leaves the place empty rather than
        failing the pass: the sessions in flight are hours of work, and a
        refusal here is the next completion's problem.
        """
        self._comments.clear()
        self.answers()
        try:
            tickets, waiting = self.queue()
        except store.StoreError as error:
            self.say(f"  ! the board could not be read again: {voice_module.line(error)}")
            return []
        fresh = [ticket for ticket in tickets if ticket.id not in started]
        # Queued or held for later, both are work about to happen: `converse`
        # leaves them alone, because their comments are going into a prompt.
        self._claimed |= {ticket.id for ticket in fresh} | {ticket.id for ticket, _ in waiting}
        if fresh:
            self.say(f"  ↺ {len(fresh)} ticket(s) ready since — filling the free place(s).")
        return fresh
