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

The validated column is read on that same cadence, and for the same reason: a
merge you asked for at 14:20 has nothing to do with the session that began at
14:04, and waiting for it is the one thing it should never do.

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

from . import base, board, credits, delivery, execution, preparation
from . import recurrence, replies, reports, state
from . import update as update_module
from .projects import Project
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

    def tick(self, *, limit: int | None = None, reference: str = "") -> list[dict]:
        # At the top, under the run lock, before a single ticket is claimed:
        # what makes an update land between two sessions — see update.py.
        if not self.dry_run:
            update_module.between_runs(self.config.runner, say=self.say, notify=self._notify)
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
        self._usage_warned = False
        # Before the answers and before the queue: what somebody wrote in a file
        # this morning is part of the board this pass is about to read.
        self.reconcile()
        self.answers()
        # The softer of the two lines, and it stops less: the window is not
        # spent, it is down to the share you asked to keep. Nothing is *started*
        # past it — no ticket, no publication, no answer in a thread — while
        # everything that costs no credit carries on, so a pull request you
        # validated this morning is still merged this afternoon.
        reserved = self.under_reserve()
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
            # Both before the queue, and both recorded as they happen: see
            # `delivered` and `born`.
            delivered = self.delivered() + self.born()
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
            if reserved:
                # The board says it rather than the journal: a ready column
                # that stays full while nothing runs reads as a broken runner,
                # which is the one thing this is not. Said once — the column is
                # empty by the next pass, and a ticket already in it is skipped.
                parked = state.record_all(self.park(tickets))
                if self.announce_idle and not parked and not delivered:
                    self.say(f"Nothing new started until {credits.when(reserved)}.")
                return delivered + parked
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

        **The validated column is looked at on that same cadence**, full pool or
        not, and that is the third half of the same fault. A merge costs no
        place at all — it is two `gh` calls in this very thread — and a
        publication costs one like any session; yet both used to be settled at
        the top of a pass and never again, so a ticket you validated at 14:20
        sat there until the two-hour session that began at 14:04 was over, with
        nothing whatsoever to do with it. Now it is carried out at 14:20, and
        what is in progress goes on being in progress.

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
        # The validated tickets this pass has taken off their column, kept apart
        # from `started`: a ticket run by this very pass and validated while it
        # was still running is delivered by it too, not held over to the next.
        carried: set[str] = set()
        queued = list(ready)
        publishing: list[tuple[Ticket, Project]] = []
        flight: set[Future] = set()
        stalled = False  # the credits ran out: nothing more is begun

        with ThreadPoolExecutor(max_workers=width) as pool:
            while True:
                # The reserve, asked again at every free place rather than once
                # at the top: the sessions in flight are what fills the window,
                # so a pass that started under the line can cross it halfway
                # through. What is running is left to finish — killing a session
                # to save credit would spend what it has already cost.
                if not stalled and self.under_reserve():
                    stalled = True
                    results += state.record_all(self.park(queued))
                    queued = []
                    publishing = []
                # Publications first: a validated ticket is one gesture from
                # done, and a place is better spent finishing work you have
                # accepted than beginning work nobody has read yet. `--limit`
                # does not count them — it caps what is taken off the ready
                # column, and this was taken off another one.
                while publishing and not stalled and len(flight) < width:
                    ticket, project = publishing.pop(0)
                    flight.add(pool.submit(self._guarded, ticket, self._publish, ticket, project))
                while (
                    queued
                    and not stalled
                    and len(flight) < width
                    and (remaining is None or remaining > 0)
                ):
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
                        # Guarded: a ticket that raises lands in failed with
                        # what it raised, and the rest of the pass carries on.
                        flight.add(pool.submit(self._guarded, ticket, self.execute, job))
                if not flight:
                    return results
                # An empty place is a reason to come back before a session ends,
                # and so is the validated column, which needs none: a pass that
                # refills therefore wakes on the timer's cadence even with every
                # place taken. A pass that does not refill waits for a session
                # exactly as it did.
                empty = (
                    not stalled and len(flight) < width and (remaining is None or remaining > 0)
                )
                looking = refill and not stalled
                done, flight = wait(
                    flight,
                    timeout=self.config.runner.interval_seconds if looking else None,
                    return_when=FIRST_COMPLETED,
                )
                results += state.record_all(future.result() for future in done)
                spent = 0.0 if stalled else self.waiting_for_credits()
                if spent:
                    # A session died on the quota while this pass was running.
                    # Every one it could still start would die on the same
                    # sentence, so nothing more is begun — what is in flight is
                    # left to finish, and what was queued says on the board why
                    # it did not start, exactly as the reserve's tickets do.
                    # Publications are sessions too.
                    stalled = True
                    results += state.record_all(self.park(queued, spent))
                    queued = []
                    publishing = []
                if stalled:
                    continue
                if not refill:
                    continue
                # The validated column, whether or not a place is free: its
                # merges happen right here, and its publications take the next
                # place. Both are held out of the next reading by hand, for the
                # same reason tickets are — Notion may still be serving the
                # status that was just written over.
                settled, fresh = self.delivering(carried)
                results += state.record_all(settled)
                carried |= {entry["id"] for entry in settled} | {
                    ticket.id for ticket, _ in fresh
                }
                publishing += fresh
                if fresh:
                    self.say(
                        f"  ↺ {len(fresh)} ticket(s) validated since — "
                        "publishing at the next free place."
                    )
                if (done or empty) and (remaining is None or remaining > 0):
                    queued = self._again(started)
