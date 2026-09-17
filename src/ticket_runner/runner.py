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
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path

from . import agents, base, board, conversation, credits, delivery, notion
from . import execution, preparation, recurrence, reports
from . import prompt as prompt_module, session, state
from . import update as update_module
from . import voice as voice_module
from .ticket import Ticket, short_id


class Runner(
    board.Board,
    delivery.Delivery,
    execution.Execution,
    preparation.Preparation,
    recurrence.Recurrence,
    reports.Reports,
    base.Base,
):
    # -- talking rather than working -----------------------------------------

    def converse(self) -> list[dict]:
        """Answer the comments that are waiting for an answer.

        A pass, not a run: nothing is claimed, no status moves, no worktree is
        made. It reads the threads on the pages where a conversation could be —
        the tickets this run already looked at, and the pages the runner has
        spoken on before — and replies where it is being spoken to.

        Everything here gives way to the work. A ticket about to be handled is
        left alone, because the comment is already going into its prompt; the
        pass runs on a cadence of its own so a ten-second runner does not scan
        the board six times a minute; and no failure of it ever reaches a
        ticket.
        """
        if self.dry_run or not self.config.runner.reply:
            return []
        ledger = self.ledger
        if not ledger.due(self.config.runner.reply_interval_seconds):
            return []
        ledger.stamp()

        me = self.myself()
        if not me:
            # Without an identity there is no telling our own last word from
            # yours — and a runner answering itself would never stop. Said once,
            # then the tickets.
            reason = self._identity_error or "no user ID came back"
            self.say(f"  ! comments not answered: Notion would not say who we are ({reason})")
            ledger.save()
            return []

        pending = self._pending(me)
        if not pending:
            ledger.save()
            return []

        self.say(f"  ✎ {len(pending)} comment(s) waiting for an answer")
        workers = min(len(pending), max(1, self.config.runner.max_concurrent))
        if workers == 1:
            answers = [self._answer(me, *pending[0])]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                answers = list(pool.map(lambda pair: self._answer(me, *pair), pending))
        results = [answer for answer in answers if answer]
        for result in results:
            state.record(result)
        ledger.save()
        return results

    def _pending(self, me: str) -> list[tuple[str, conversation.Thread]]:
        """The threads to answer this pass, page by page.

        Two sources, and only one of them costs anything. The pages this run has
        already read are free — their comments are in hand. The rest are the
        pages the runner has spoken on, taken a window at a time so that a board
        it has been running against for months does not turn one pass into a
        hundred requests.
        """
        spellings = self.spellings()
        seen = list(self._comments)
        remembered = [page for page in self.ledger.known_pages() if page not in self._comments]
        window = self.ledger.rotate(remembered, self.config.runner.reply_scan)

        pending: list[tuple[str, conversation.Thread]] = []
        for page_id in [*seen, *window]:
            if page_id in self._claimed:
                continue
            try:
                comments = self.comments(page_id)
            except notion.NotionError:
                # Unreadable comments, or a page that has since been deleted.
                # Neither is this pass's business to report on.
                continue
            for thread in conversation.waiting(comments, me=me, spellings=spellings):
                if self.ledger.answered(thread.discussion) == thread.last.id:
                    # Already answered: Notion handed back a thread whose reply
                    # is still in flight.
                    continue
                pending.append((page_id, thread))
                break  # one answer per page per pass: a thread at a time
            if len(pending) >= conversation.ANSWERS:
                break
        return pending

    def _answer(self, me: str, page_id: str, thread: conversation.Thread) -> dict | None:
        """Answer one comment, in its thread. Never raises."""
        try:
            return self._answer_thread(me, page_id, thread)
        except notion.NotionError as error:
            self.say(f"    ! comment not answered: {voice_module.line(error)}")
        except (OSError, ValueError) as error:
            self.say(f"    ! comment not answered: {error}")
        return None

    def _answer_thread(self, me: str, page_id: str, thread: conversation.Thread) -> dict | None:
        ticket = Ticket(self.client.page(page_id))
        spellings = self.spellings()
        message = conversation.strip_mention(thread.last.text, spellings)
        self.say(f"  ✎ {ticket.title} — {' '.join(message.split())[:70]}")

        project = self._project_of(ticket)
        short = short_id(ticket.id)
        if project.is_code and project.path:
            workdir = project.path
            where = (
                f"Repository: {project.path} — read as much of it as you need. "
                "You are not changing it, and the permissions you are running under "
                "will not let you."
            )
        else:
            workdir = conversation.talk_dir(short)
            where = f"Working directory: {workdir} — this ticket has no repository."

        role = notion.read(ticket.page, self.config.notion.prop("role")) or []
        agent = (
            agents.resolve(self.client, role[0], self.config.notion.prop("model"))
            if role
            else agents.Agent()
        )
        text = prompt_module.conversation(
            prompt_module.CONVERSATION,
            project=project.name,
            title=ticket.title,
            body=self._body(ticket),
            where=where,
            url=ticket.url,
            message=message,
            thread=conversation.transcript(thread, me),
            brief=project.brief,
            context=self.workspace.context,
            agent_name=agent.name,
            agent_brief=agent.brief,
            comments=self.discussion(ticket),
            language=self.voice.instruction(reply=True),
        )

        discussion = thread.last.discussion_id
        resumed = self.ledger.session_of(discussion) if discussion else ""
        outcome = self._reply_session(
            text, workdir, short, agent, ticket, session_id=resumed or session.new_id(),
            resume=bool(resumed),
        )
        if not outcome.ok and resumed and not outcome.exhausted:
            # A session Claude Code no longer has — pruned, or filed on another
            # machine. The thread's history is in Notion, so a fresh one starts
            # from everything except the tone of the last exchange.
            self.say("    ↻ that conversation could not be resumed — starting a new one")
            with self._ledger_lock:
                self.ledger.forget_session(discussion)
            outcome = self._reply_session(
                text, workdir, short, agent, ticket, session_id=session.new_id(), resume=False
            )

        if self._out_of_credit(outcome):
            # An answer nobody could afford is not an answer to write down: the
            # thread is left as it was, unanswered, and the pass that runs once
            # the credits are back finds it exactly where it is.
            self.say("    ⏸ out of credit — this one is answered later")
            return None

        answer = conversation.trim(outcome.answer if outcome.ok else "")
        if not answer:
            said = self.voice
            answer = said.say(
                "no-reply",
                error=voice_module.line(outcome.error) or said.say("said-nothing"),
                log=outcome.log,
            )
        self._comment(ticket, answer, discussion)
        with self._ledger_lock:
            self.ledger.remember_thread(
                discussion, session=outcome.session_id, comment=thread.last.id
            )
            self.ledger.remember_page(page_id)
        cost = f" · ${outcome.cost_usd:.3f}" if outcome.cost_usd else ""
        self.say(f"    ↳ answered · {outcome.seconds / 60:.1f} min{cost}")
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "answered",
            "kind": "comment",
            "project": project.name,
            "session": outcome.session_id,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }

    def _reply_session(
        self,
        text: str,
        workdir: Path,
        short: str,
        agent: agents.Agent,
        ticket: Ticket,
        *,
        session_id: str,
        resume: bool,
    ) -> session.Outcome:
        """One turn of a conversation, in a permission mode that cannot write.

        `reply_permission_mode` is the guardrail; the prompt only explains it.
        A conversation runs in the repository itself rather than in a worktree —
        there is nothing to isolate when nothing can be changed, and a stable
        directory is what lets the next question land in the same session.
        """
        # A resumed session already carries the frame; what it has not seen is
        # the new message, which is the last section of the prompt we built.
        prompt_text = (
            prompt_module.follow_up(
                prompt_module.message_of(text), self.voice.instruction(reply=True)
            )
            if resume
            else text
        )
        chosen = (
            str(notion.read(ticket.page, self.config.notion.prop("model")) or "")
            or agent.model
            or self.config.runner.model
        )
        outcome = session.run(
            prompt_text,
            cwd=workdir,
            log=state.log_file(f"{short}-talk"),
            model=chosen,
            permission_mode=self.config.runner.reply_permission_mode,
            timeout_minutes=self.config.runner.reply_timeout_minutes,
            session_id=session_id,
            resume=resume,
            environment=self.environment,
        )
        self._hold_credits(outcome)
        return outcome

    # -- a full run ----------------------------------------------------------

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
