"""One run: take the ready tickets, do them, report back to Notion.

A run has two phases, and the order matters.

**First, sequentially:** read the ready tickets, locate their project, and
*claim* them by moving them to "in progress". Claiming before working is what
stops the timer from picking up a ticket already taken — and doing it
sequentially keeps two tickets from racing over the same repository index.

**Then, in parallel:** each claimed ticket gets its worktree, its Claude
session, its branch and its pull request. A ticket that fails takes only itself
down: it lands in "failed" — or in "blocked", when the agent asked a question
rather than guessed — with the reason in a comment, while the others carry on.

The two phases interleave, because the second one is long. `max_concurrent`
sessions run at a time, and every session that ends frees a place the board is
asked to fill straight away: a ticket made ready at 14:10 starts at 14:10, not
when the session that began at 14:04 is finally done. A pass therefore ends
when the ready column is empty and nothing is left in flight — see `_work`.

What is left in this module is that pass and nothing else. `tick` decides what
a run is made of and in which order; `_work` keeps `max_concurrent` places
filled until the board has nothing left to fill them with. Everything a pass
asks for on the way — reading the board, preparing a ticket, running its
session, carrying out a validated one, answering a comment — is a chapter of
its own in a module of its own, and `base.py` says why they are assembled the
way they are rather than held at arm's length.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

from . import base, board, credits, delivery, execution, notion, preparation
from . import recurrence, replies, reports, state
from . import update as update_module
from . import voice as voice_module
from .ticket import Ticket


class Runner(
    board.Board,
    delivery.Delivery,
    execution.Execution,
    preparation.Preparation,
    recurrence.Recurrence,
    replies.Replies,
    reports.Reports,
    base.Base,
):
    """One pass of the runner, over everything a pass is made of."""

    def update(self) -> None:
        """Once an hour, make sure the installed code is still the newest.

        Here rather than in a timer of its own: a run already wakes up on a
        schedule, and doing it at the top of one — under the run lock, before a
        single ticket is claimed — is what makes an update land between two
        sessions instead of underneath one. The new code takes over on the next
        pass.

        Nothing here can fail a run: an unreachable remote, an installation made
        from a copy, a refused write are all one line and then the tickets.
        """
        if not self.config.runner.auto_update or self.dry_run:
            return
        if not update_module.due(self.config.runner.update_interval_seconds):
            return
        status = update_module.check()
        if status.reason:
            self.say(f"  ! version not checked: {status.reason}")
            return
        if not status.stale:
            return
        short = f"{status.current[:8]} → {status.latest[:8]}"
        self.say(f"  ↑ a newer version is out ({short}) — updating")
        error = update_module.apply(status, self.config.runner.interval_seconds)
        if error:
            self.say(f"  ! update failed: {error}")
            return
        self.say("    updated — the next run uses it")
        self._notify("ticket-runner updated", short)

    def tick(self, *, limit: int | None = None, reference: str = "") -> list[dict]:
        self.update()
        # Nothing at all while the subscription is out: every session this pass
        # could start would die on the same sentence, and every ticket it
        # touched would come back as a failure of its own. The run that put the
        # wait there said so; these ones are quiet, because at a ten-second
        # cadence saying it again is six lines a minute for four hours.
        waiting = self.waiting_for_credits()
        if waiting:
            if self.announce_idle:
                self.say(f"Out of credit — nothing is run until {credits.when(waiting)}.")
            return []
        # The comments are read afresh: a run is where the board is looked at,
        # and a Runner kept alive by the console would otherwise answer a
        # question from an hour ago. Before `answers`, so that what you replied
        # on your phone is in the very cache the queue is about to read.
        self._comments.clear()
        self._claimed = set()
        self.answers()
        # What the board asked for before any new work: the tickets you
        # validated, merged or published on their way to done.
        delivered: list[dict] = []
        if reference:
            tickets = [self.fetch_one(reference)]
            self.say(f"Requested ticket: {tickets[0].title}")
        else:
            if not self.dry_run:
                self.sweep()
                self.close_merged()
            # `deliver` runs in a dry run too, where it only says what it would
            # do: the one gesture that cannot be taken back is the one worth
            # rehearsing.
            delivered = self.deliver()
            # Merged, published, or refused: as much a run of this ticket as a
            # session is, and `ticket-runner history` should say so.
            for done in delivered:
                if done.get("status") != "dry-run":
                    state.record(done)
            # Before the queue, so a ticket born at 09:00 is claimed by this
            # very pass rather than by the next one. A birth is an entry of its
            # own kind — `ticket-runner history` shows it as it shows a merge.
            for newborn in self.recur():
                if newborn.get("status") != "dry-run":
                    state.record(newborn)
                    delivered.append(newborn)
            tickets, waiting = self.queue()
            # Every ticket the queue wants, and not only the ones that will fit
            # in this pass: a ticket queued for the next run — or held until
            # Thursday — is still work, and the comment that queued it is going
            # into its prompt. Talking to it as well would be the runner
            # answering a question it is also about to act on.
            self._claimed |= {ticket.id for ticket in tickets} | {
                ticket.id for ticket, _ in waiting
            }
            # A ticket held in ready and one held in validated are both work
            # with an hour on it: counted together, so a pass says how much of
            # the board is waiting for a date rather than half of it.
            held = len(waiting) + len(self._deferred)
            if not tickets:
                replies = self.converse()
                if self.announce_idle and not replies and not delivered:
                    later = f", {held} waiting for their date" if held else ""
                    self.say(f"No ticket ready{later}.")
                return delivered + replies
            later = f", {held} scheduled for later" if held else ""
            self.say(f"{len(tickets)} ticket(s) ready{later}.")

        # Said here rather than on resolution: at a ten-second cadence, a run
        # with nothing to do would repeat them forever into the journal.
        for warning in self.workspace.warnings:
            self.say(f"  ! {warning}")

        replies = [] if reference else self.converse()
        # `--limit` caps the tickets this pass takes off the board, not how
        # many run at once: that is `max_concurrent`, and a queue that refills
        # itself would otherwise run the whole column on a `--limit 1`.
        # No refilling for a named ticket — the pass is about that one — nor for
        # a dry run, which claims nothing and would read the same column back.
        results = self._work(tickets, limit, refill=not reference and not self.dry_run)
        state.prune_logs(self.config.runner.log_retention_days)
        return delivered + replies + results

    def _work(self, ready: list[Ticket], ceiling: int | None, *, refill: bool) -> list[dict]:
        """Run the ready tickets, `max_concurrent` sessions in flight throughout.

        A queue rather than a batch. A pass used to prepare the first
        `max_concurrent` tickets, wait for every one of them, and only then end
        — so a ticket made ready while a two-hour session was running waited for
        that session, then for the timer, however many places were free. The run
        lock and the timer see no change: it is the *pass* that became
        continuous, not the number of runs.

        Here a completion is a place, and a place is filled from the board as it
        is **now**: `queue()` is asked again, which is what keeps the priority
        order honest — an urgent ticket written during the pass goes before a
        normal one that was ready when it started. Tickets already begun are
        held out by hand, because Notion may still be serving the status this
        very pass wrote.

        A completion is not the *only* place, and that was the second half of
        the same fault: a place standing empty while one session runs is a place
        the board could fill straight away, and waiting for that session to end
        before looking made `max_concurrent = 2` behave like one. Nobody else
        can look either — the run lock belongs to this pass for as long as it
        lasts, and the timer meets it and leaves. So the pass looks on its own,
        at the timer's cadence (`interval_seconds`): exactly as often as the
        board would have been read had nothing been running, and not one request
        more.

        Results are recorded one by one rather than at the end, so
        `ticket-runner history` shows a ticket that finished in four minutes
        without waiting on the one that will take two hours.
        """
        width = max(1, self.config.runner.max_concurrent)
        if ceiling is not None:
            width = max(1, min(width, ceiling))
        remaining = ceiling  # None: as many tickets as the board offers
        results: list[dict] = []
        started: set[str] = set()
        queued = list(ready)
        flight: set[Future] = set()
        stalled = False  # the credits ran out: nothing more is begun

        with ThreadPoolExecutor(max_workers=width) as pool:
            while True:
                while queued and len(flight) < width and (remaining is None or remaining > 0):
                    ticket = queued.pop(0)
                    if ticket.id in started:
                        continue
                    started.add(ticket.id)
                    if remaining is not None:
                        remaining -= 1
                    # Claimed here, in the one thread that does it, so that two
                    # tickets never race over the same repository index.
                    job = self.prepare(ticket)
                    if job:
                        flight.add(pool.submit(self.execute, job))
                if not flight:
                    return results
                # An empty place is a reason to come back before a session ends;
                # a full pool is not, and waits for one exactly as it did.
                empty = (
                    refill
                    and not stalled
                    and len(flight) < width
                    and (remaining is None or remaining > 0)
                )
                done, flight = wait(
                    flight,
                    timeout=self.config.runner.interval_seconds if empty else None,
                    return_when=FIRST_COMPLETED,
                )
                for future in done:
                    result = future.result()
                    results.append(result)
                    state.record(result)
                stalled = bool(self.waiting_for_credits())
                if stalled:
                    # A session died on the quota while this pass was running.
                    # Every one it could still start would die on the same
                    # sentence, so nothing more is begun — what is in flight is
                    # left to finish, and the first pass after the wait picks
                    # the board up where it was.
                    queued = []
                    continue
                if (done or empty) and refill and (remaining is None or remaining > 0):
                    queued = self._again(started)

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
        except notion.NotionError as error:
            self.say(f"  ! the board could not be read again: {voice_module.line(error)}")
            return []
        fresh = [ticket for ticket in tickets if ticket.id not in started]
        # Queued or held for later, both are work about to happen: `converse`
        # leaves them alone, because their comments are going into a prompt.
        self._claimed |= {ticket.id for ticket in fresh} | {ticket.id for ticket, _ in waiting}
        if fresh:
            self.say(f"  ↺ {len(fresh)} ticket(s) ready since — filling the free place(s).")
        return fresh
