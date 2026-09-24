"""What a run writes down: on the ticket, on the board, on your phone.

A session does the work; this is everything said *about* it. The columns a
finished ticket fills in, the comment under it, the same words pushed to
Telegram or Slack, and the answer you type back there written onto the page as
an ordinary Notion comment — one road in, one road out, nothing kept in sync on
the side.

The two ways a run ends without a result live here too, and for the same
reason: both are made of what is written rather than of what was done. `_fail`
takes a ticket to failed — or to blocked, when the agent asked a question
rather than guessed — and `_requeue` puts it back in the column it was taken
from, which is the whole of what an exhausted quota has to say.

`voice.py` decides the words and the language; this decides what is worth
saying at all, and where.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

from . import channels, conversation, credits, session, state, store
from . import voice as voice_module
from .base import Base
from .ticket import Job, Ticket


# How much of a ticket's own history is worth carrying into the prompt.
COMMENT_LIMIT = 10
COMMENT_CHARS = 2000

# What a session identifier looks like — `session.new_id` draws a UUID4. Matched
# rather than trusted because the Session column is a column like any other: a
# cell somebody typed into must not become a `claude --resume` of its own.
_SESSION_ID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


class Reports(Base):
    """Everything a run says, and everywhere it says it."""

    # -- the ticket's own columns --------------------------------------------

    def _set(self, ticket: Ticket, **values: object) -> None:
        """Write ticket properties, the status above all.

        The status is what the board runs on: it says whether a ticket is taken,
        finished or waiting for someone. The others — who ran it, the session
        link, the cost — are commentary. So a write that Notion rejects is tried
        again with the status alone, rather than leaving a finished ticket stuck
        in "in progress" because an optional column disagreed about its type.
        """
        if self.dry_run:
            return
        try:
            self.client.update(self.database, ticket.page.id, values)
        except store.StoreError as error:
            status = self.config.notion.prop("status")
            if status not in values:
                raise
            self.say(f"    ! Notion refused some properties ({error}) — writing the status alone")
            self.client.update(self.database, ticket.page.id, {status: values[status]})

    def _measures(self, outcome: session.Outcome) -> dict[str, object]:
        """What the run cost, for the columns that want to know.

        Skipped silently when the database has no such columns — and `cost` is
        zero on a subscription, where the CLI reports none, so it is only
        written when there is something to write.
        """
        values: dict[str, object] = {
            self.config.notion.prop("duration"): round(outcome.seconds / 60, 1)
        }
        if outcome.cost_usd:
            values[self.config.notion.prop("cost")] = round(outcome.cost_usd, 3)
        return values

    def _session_value(self, session_id: str, home: Path | None) -> str:
        """A deep link if the Session property is a URL, the bare ID otherwise.

        The property's declared type decides: a URL column gets something
        clickable, a text column gets the identifier. Nobody has to configure
        which — changing the column type in Notion is the switch.
        """
        kind = self.client.schema(self.database).get(self.config.notion.prop("session"))
        if kind == "url":
            return session.deep_link(
                session_id,
                home or self.config.runner.workspace_root,
                self.config.runner.session_host,
            )
        return session_id

    def _carried_session(self, ticket: Ticket) -> str:
        """The session to carry on for this ticket, when there is one to carry on.

        Only for a ticket ticked as waiting for credit, and that narrowness is
        the point: everywhere else a ticket runs again, the Session column holds
        a conversation that *ended* — reported on, commented, answered — and
        resuming it would have the agent argue with its own verdict. A window
        that closed mid-sentence is the one case where the conversation is
        genuinely unfinished, and `park` empties the cell of the tickets it
        ticks that were never started at all.

        Read back through whichever shape `_session_value` wrote: a deep link on
        a URL column, the bare identifier on a text one. Anything that is not an
        identifier — a link somebody pasted, an emptied cell — reads as none,
        and the ticket opens a session of its own.
        """
        flag = self.waiting_flag()
        if not flag or not store.read(ticket.page, flag):
            return ""
        raw = str(store.read(ticket.page, self.config.notion.prop("session")) or "").strip()
        if "://" in raw:
            raw = raw.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        return raw if _SESSION_ID.fullmatch(raw) else ""

    # -- what is said on the page ---------------------------------------------

    def _comment(self, ticket: Ticket, text: str, discussion: str = "") -> None:
        """Say something on a ticket, and remember that we said it.

        Remembering matters: a comment does not change a page, so Notion offers
        no way of asking which tickets have been commented on since. The pages
        the runner has spoken on are the only affordable place to look for an
        answer — see `conversation.Ledger`.
        """
        if self.dry_run:
            return
        try:
            self.client.comment(ticket.page.id, text, discussion)
        except store.StoreError as error:
            hint = ""
            if "403" in str(error):
                hint = (
                    "\n      the integration lacks comment capability: "
                    "notion.so/my-integrations → your integration → Capabilities → "
                    "Insert comments"
                )
            self.say(f"    ! Notion refused the comment: {error}{hint}")
            return
        self.forget_comments(ticket.page.id)
        with self._ledger_lock:
            self.ledger.remember_page(ticket.page.id)
            self.ledger.save()

    def comments(self, page_id: str) -> list[store.Comment]:
        """The comments of a page, once per run, and never a reason to fail.

        An integration without the *Read comments* capability is the common
        case, not an accident: it is off by default. So a refusal is an empty
        discussion — said once, in `discussion` — rather than a lost ticket.
        """
        key = page_id.replace("-", "")
        if key not in self._comments:
            self._comments[key] = self.client.comments(page_id)
        return self._comments[key]

    def forget_comments(self, page_id: str) -> None:
        """We just wrote on that page; what we cached is one comment short."""
        self._comments.pop(page_id.replace("-", ""), None)

    @property
    def ledger(self) -> conversation.Ledger:
        if self._ledger is None:
            self._ledger = conversation.Ledger.load()
        return self._ledger

    def discussion(self, ticket: Ticket) -> list[str]:
        """What was said on the ticket, ready for the prompt, newest last.

        Bounded twice — the last few comments, and a character budget — because
        a ticket that has been round three times would otherwise spend more of
        the prompt on its own history than on the work.
        """
        try:
            comments = self.comments(ticket.page.id)
        except store.StoreError as error:
            hint = ""
            if "403" in str(error):
                hint = (
                    " — notion.so/my-integrations → your integration → "
                    "Capabilities → Read comments"
                )
            self.say(f"    ! comments not readable: {error}{hint}")
            return []

        me = self.myself()
        lines: list[str] = []
        budget = COMMENT_CHARS
        for comment in reversed(comments[-COMMENT_LIMIT:]):
            text = comment.text
            if conversation.ours(comment, me) and not voice_module.is_report(text):
                # Something the runner said in a thread rather than reported.
                # Attributing it to the ticket's author would have the next run
                # read its own words back as an instruction.
                text = " ".join(text.split())
                who = "answered in the comments, by us"
            elif voice_module.is_report(text):
                # Our own report. Its first two lines hold the verdict and the
                # sentence under it; anything after is a link and, on the
                # reports older runs wrote, the machinery they ended on.
                text = " ".join("\n".join(voice_module.plain(text).splitlines()[:2]).split())
                who = "a previous run"
            else:
                text = " ".join(text.split())
                who = "the ticket's author"
            line = f"{who}: {text}"
            budget -= len(line)
            if budget < 0:
                break
            lines.append(line)
        return list(reversed(lines))

    # -- what reaches you, wherever you are -----------------------------------

    def _tell(
        self,
        event: str,
        ticket: Ticket,
        verdict: str,
        body: str,
        *,
        urgent: bool = False,
        ask: bool = False,
    ) -> None:
        """One moment of a ticket, said everywhere it is worth saying.

        The screen of the machine the runner sits on, and the messaging app you
        actually have on you. Same words as the comment — the same verdict, the
        same sentence under it — because a Notion notification and a Telegram
        one are the same event reaching you twice, and telling it twice in two
        ways is how you end up reading both. One line longer in the second,
        because a message you can answer has to say so — and both carry the
        ticket's page, because a notification you then have to go and find is a
        notification you do not act on.

        `event` is which of them you asked to be told about — `notify.events` —
        and `verdict` is what is being said, which is not the same question: a
        merge and a pull request to read are both `done` to a setting, and *To
        review* and *Merged* to a reader.
        """
        said = self.voice
        headline = said.headline(verdict, ticket.title)
        self._notify(headline, body, urgent=urgent, link=ticket.url)
        settings = self.config.notify
        if self.dry_run or not settings.remote or not settings.wants(event):
            return
        invitation = "\n\n" + said.say("answer-here") if ask else ""
        channels.announce(
            settings,
            f"{voice_module.MARKS[verdict]} {headline}\n{body}{invitation}\n{ticket.url}",
            ticket=ticket.page.id,
            title=ticket.title,
            ask=ask,
        )

    def answers(self) -> int:
        """What you replied in Telegram or Slack, written onto its ticket.

        The bridge is deliberately one line long: an answer becomes a Notion
        comment, and a comment is *already* how a blocked ticket wakes up. A
        "yes" typed on a phone therefore travels the exact path a "yes" typed
        into Notion does — same waking rules, same prompt, nothing kept in sync
        on the side.

        First thing in a run, before the queue is read, so that a ticket
        answered thirty seconds ago is picked up by this very run.
        """
        settings = self.config.notify
        if self.dry_run or not settings.replies or not settings.remote:
            return 0

        answered = 0
        for channel in channels.open(settings):
            try:
                replies = channel.collect()
            except channels.ChannelError as error:
                self.say(f"  ! {channel.name} not readable: {error}")
                continue
            for reply in replies:
                if not reply.ticket:
                    # Silence for ordinary talk in the room — a bot answering
                    # every message is why nobody keeps one in a channel. A
                    # plain "yes" that landed nowhere is the exception: that one
                    # was meant for us and deserves to be told it missed.
                    if channels.decide(reply.text):
                        channel.acknowledge(reply, self.voice.say("nothing-waiting"))
                    continue
                try:
                    self.client.comment(reply.ticket, channels.answer(reply))
                except store.StoreError as error:
                    self.say(f"    ! the answer could not be written to Notion: {error}")
                    channel.acknowledge(reply, self.voice.say("notion-refused", error=error))
                    continue
                answered += 1
                label = reply.title or reply.ticket
                self.say(f"  ↩ {label} — answered from {channel.name}, back in the queue")
                channel.acknowledge(reply, self.voice.say("noted", title=label))
        return answered

    # -- the endings that are not a result -------------------------------------

    def _fail(
        self,
        ticket: Ticket,
        reason: str,
        detail: str = "",
        *,
        blocked: bool = False,
        question: str = "",
        note: str = "",
    ) -> dict:
        """A run that did not get there, said in as few lines as it takes.

        A blocked ticket opens on the **question**, because that is the thing
        somebody has to read and answer; a failed one opens on the reason, and
        says under it what the session said before it stopped. `note` is where
        the rest went — the folded block, usually, and the trace itself on a
        ticket that has no such block: see `_filed`.
        """
        outcome = "blocked" if blocked else "failed"
        said = self.voice
        self.say(f"    ✗ {ticket.title} — {reason}")
        asked = question.strip() if blocked and question.strip() else said.sentence(reason)
        # A blocked ticket is a question, and a question is the one thing worth
        # waking somebody for — so it travels with what the agent actually
        # asked, not with the runner's own summary of the situation.
        self._tell(
            outcome,
            ticket,
            outcome,
            said.brief(asked),
            urgent=not blocked,
            ask=blocked,
        )
        self._set(ticket, **{self.config.notion.prop("status"): self.config.notion.state(outcome)})
        # A blocked ticket has the invitation to answer under its question, and
        # the detail only when it says something the question does not — which
        # on most of these roads it does not, the question *being* the detail.
        under = said.brief(detail)
        if blocked:
            under = "" if under == said.brief(asked) else under
        self._comment(
            ticket,
            said.report(
                said.verdict(outcome, said.brief(asked)),
                under,
                said.say("answer-here") if blocked else "",
                note,
            ),
        )
        return {"ticket": ticket.title, "id": ticket.id, "status": outcome, "reason": reason}

    def _guarded(
        self, ticket: Ticket, work: Callable[..., dict | None], *arguments: object
    ) -> dict | None:
        """Run one ticket's work so that whatever it raises is that ticket's alone.

        A pass runs several tickets at once, and an exception from any of them
        used to come back out of `future.result()` and end the pass: the other
        sessions ran on with nobody left to report them, and the ticket that
        raised stayed "in progress" until a later run swept it back to ready —
        to fail the same way again. Here it fails *as a ticket*, on the board and
        in the history, with what it raised.

        And if even that cannot be written — Notion is the thing that is down —
        the pass is still not the one to pay: the result is recorded here, and
        the next run's sweep finds the ticket where it was left.
        """
        try:
            return work(*arguments)
        except Exception as error:  # noqa: BLE001 — the point is to catch it all
            detail = f"{type(error).__name__}: {voice_module.line(error)}"
            state.release(ticket.id)
            try:
                return self._fail(ticket, self.voice.say("crashed"), detail)
            except Exception as unwritten:  # noqa: BLE001
                self.say(
                    f"    ✗ {ticket.title} — {detail}, and the failure could not be "
                    f"written: {voice_module.line(unwritten)}"
                )
                return {"ticket": ticket.title, "id": ticket.id, "status": "failed", "reason": detail}

    def _filed(self, job: Job, outcome: session.Outcome, *rest: object) -> str:
        """The machinery of a failed run, put where it does not crowd the report.

        Inside the folded block the run already wrote its steps into, which is
        where somebody looking for it would open anyway — and the report then
        says so in one line. A ticket that has no such block, because the live
        report is off or Notion refused it, keeps the trace in the comment: a
        trace nobody can find is a trace nobody has.

        Nothing of this is said when a run went right. The command that resumes
        a finished session is not something anybody has ever needed to read.
        """
        said = self.voice.paragraphs(self._trace(job, outcome), *rest)
        if job.live and job.live.detail(said):
            return self.voice.say("trace-in-page")
        return said

    def _trace(self, job: Job, outcome: session.Outcome) -> str:
        """Where to look when the report was not enough — and only then.

        One sentence, and it no longer ends a report: it goes into the folded
        block of a run that failed, which is the only day anybody has wanted to
        read it. See `_filed`.
        """
        return self.voice.trace(outcome.resume_command, outcome.log, job.session_home)

    # -- nothing left to spend -------------------------------------------------

    def _out_of_credit(self, outcome: session.Outcome) -> bool:
        """Did this session die on the subscription's quota, and do we wait?

        The two halves of the same question: what happened, which `session.run`
        read off the CLI, and what the configuration says to do about it. With
        `wait_for_credits` off, an exhausted quota is a session failure like any
        other and is reported as one — which is what the runner always did.
        """
        return bool(outcome.exhausted and self.config.runner.wait_for_credits)

    def _hold_credits(self, outcome: session.Outcome) -> None:
        """Put the runner to sleep until the credits come back.

        On disk rather than in memory: a run is a process the timer starts, so
        the runs that follow only learn this by reading it — see credits.py.
        Said out loud here, once, because those runs are silent about it.
        """
        if not self._out_of_credit(outcome):
            return
        credits.hold(outcome.resets_at)
        when = credits.when(outcome.resets_at)
        self.say(f"  ⏸ out of credit — nothing is run until {when}")
        self._announce("ticket-runner is out of credit", f"Back to work at {when}.")

    def _requeue(
        self,
        ticket: Ticket,
        status: str,
        outcome: session.Outcome,
        note: str = "",
        home: Path | None = None,
    ) -> dict:
        """Put a ticket back in the column it came from, ticked, and say why.

        The one way out of a run that is neither a success nor a failure:
        nothing was wrong with the ticket, there was simply nothing left to work
        on it with. So no question is asked and nobody's phone rings — the tick
        is the whole of the message, and the first run with credit again picks
        the ticket up before anything that never started.

        The caller names the column because the two roads out of here come back
        by different doors. A *ticket* goes back to ready and is picked up by
        the queue. A *publication* goes back to validated and is picked up by
        `deliver`, which is the only thing that reads that column — the decision
        to publish has already been taken, and putting it anywhere else would
        both take that decision back and hand a delivery session to the queue as
        though it were work to do. Neither of them moves anywhere it had not
        already been: the attribute is what says that the credit, and not the
        board, is why the ticket is sitting there.
        """
        said = self.voice
        when = credits.when(outcome.resets_at)
        self.say(f"    ⏸ {ticket.title} — out of credit, back in “{status}” until {when}")
        # The session goes with it, because it is what the pass with credit
        # again picks the ticket back up by — and it may not be the one the
        # claim wrote, if the one the claim wrote could not be resumed.
        self._set(
            ticket,
            **{
                self.config.notion.prop("status"): status,
                self.config.notion.prop("waiting"): True,
                self.config.notion.prop("session"): self._session_value(
                    outcome.session_id, home
                ),
            },
        )
        self._comment(
            ticket,
            said.report(
                said.verdict("waiting", said.say("credits-out", status=status, when=when)),
                note,
            ),
        )
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "waiting",
            "reason": f"out of credit until {when}",
        }

    def under_reserve(self) -> float:
        """The moment the reserve lifts, or 0.0 while there is credit to spend.

        `credit_reserve_percent` is the share of the window this runner refuses
        to touch, so that a subscription the runner has been chewing on all
        afternoon still has something left for the terminal you open yourself.
        Past `100 - reserve`, no session is started — not a ticket's, not a
        publication's, not an answer in a thread. What *is* still done is
        everything that costs nothing: a validated pull request is merged, a
        merged one is closed, the board is swept.

        Asked again every time rather than once per run, and that is the point:
        a pass lasts as long as its longest session, and the sessions in flight
        are what fills the window. Reading it afresh at each free place is what
        makes the line hold *during* a pass rather than only at its top. What is
        said out loud is held to once — by the note, not by a flag, since a run
        is a process the timer starts and the pass after it must stay quiet.

        Three ways this is 0.0, and only one of them is "there is room": the
        setting belongs to a metered subscription, so a runner told not to wait
        for credits has no window to reserve a slice of; and a reading nobody
        could take is a warning, not a stop — see `credits.used`.
        """
        if not self.config.runner.wait_for_credits:
            return 0.0
        reading = credits.used()
        if reading is None:
            # Once per run, not once per free place: the cache is not going to
            # appear halfway through a pass, and a warning repeated every ten
            # seconds is a warning nobody reads.
            if not self._usage_warned:
                self._usage_warned = True
                self.say(
                    "  ! how much of the subscription is spent could not be read — "
                    "carrying on without the reserve"
                )
            return 0.0
        used, resets_at = reading
        reserve = self.config.runner.credit_reserve_percent
        if used < 100 - reserve:
            # Back under the line: said once, and only by the run that finds it,
            # exactly as the end of a spent window is.
            if credits.release(what="reserve"):
                self.say(f"  ▶ {used:.0f}% of the subscription spent — carrying on")
                self._announce(
                    "ticket-runner has credit again",
                    f"{used:.0f}% of the subscription spent — back to work.",
                )
            return 0.0
        # A window that names no moment still stops the runner; it simply stops
        # it for as long as a blind wait, and the next run asks the cache again.
        until = resets_at or time.time() + credits.BLIND_WAIT
        if not credits.held(what="reserve"):
            credits.hold(until, what="reserve")
            when = credits.when(until)
            self.say(
                f"  ⏸ {used:.0f}% of the subscription spent, {reserve}% reserved — "
                f"nothing new until {when}"
            )
            self._announce(
                "ticket-runner is leaving you the rest",
                f"{used:.0f}% of the subscription spent, {reserve}% reserved — "
                f"nothing new is started before {when}.",
            )
        return until

    def park(self, tickets: list[Ticket], until: float = 0.0) -> list[dict]:
        """Tick the tickets nothing could be started for, and leave them be.

        Said on the board rather than only in a journal nobody reads: a ready
        column that stays full while the in-progress one stays empty tells you
        the runner is broken, which is the one thing it is not. And said without
        moving anything, because nothing happened to these tickets — they are
        still ready, which is exactly what they were a second ago, and a column
        they had disappeared into would have claimed otherwise. Ticked once: a
        ticket already ticked is left alone, which is what keeps a wait of four
        hours from being four hours of Notion writes.

        Nothing here asks anything of anybody: no question, no phone. The
        notification for this went out once, when the line was reached.

        `until` is the moment being waited for; unnamed, it is read off whichever
        of the two waits is standing.
        """
        flag = self.waiting_flag()
        if not flag or self.dry_run:
            return []
        said = self.voice
        when = credits.when(until or self.under_reserve() or credits.held())
        parked: list[dict] = []
        for ticket in tickets:
            if store.read(ticket.page, flag):
                continue
            self.say(f"  ⏸ {ticket.title} — {said.say('credit-parked', when=when)}")
            # The Session cell is emptied on the way in, and that is what tells
            # this ticket from one `_requeue` ticked on its way out: nothing was
            # started for this one, so there is no conversation to carry on.
            # Whatever was in the cell belongs to a run that *finished* and was
            # reported on — resuming it would have the agent argue with its own
            # verdict. That is not a corner case here: a ticket woken by a
            # comment is queued from `failed`, and is ticked where it stands
            # like any other, so its old session is exactly what would be found.
            self._set(ticket, **{flag: True, self.config.notion.prop("session"): ""})
            self._comment(
                ticket,
                said.report(said.verdict("waiting", said.say("credit-parked", when=when))),
            )
            parked.append(
                {
                    "ticket": ticket.title,
                    "id": ticket.id,
                    "status": "waiting",
                    "reason": f"out of credit until {when}",
                }
            )
        return parked

    def waiting_for_credits(self) -> float:
        """The moment the credits come back, or 0.0 when there is nothing to wait for.

        Reading it is also what ends the wait: a note whose moment has passed is
        removed here, so the run that finds the credits back is the one that
        says so.
        """
        if not self.config.runner.wait_for_credits:
            return 0.0
        until = credits.held()
        if until:
            return until
        if credits.release():
            self.say("  ▶ the credits are back — carrying on")
        return 0.0
