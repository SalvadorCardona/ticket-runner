"""Talking rather than working: the comments that are waiting for an answer.

A pass, not a run. Nothing is claimed, no status moves, no worktree is made,
and the session it starts runs under `reply_permission_mode` — the guardrail
that cannot write, in the repository itself rather than in a copy of it, since
there is nothing to isolate when nothing can be changed.

Everything here gives way to the work. A ticket this pass is about to handle is
left alone, because the comment is already going into its prompt; the pass runs
on a cadence of its own so that a ten-second runner does not scan the board six
times a minute; and no failure of it ever reaches a ticket.

`conversation.py` reads the threads and decides which are being spoken to; this
is what is done about them — one thread per page per pass, answered in the
thread it was asked in, and the session kept so the next question lands in the
same conversation rather than in a stranger.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import agents, conversation, notion, session, state
from . import prompt as prompt_module
from . import voice as voice_module
from .base import Base
from .ticket import Ticket, short_id


class Replies(Base):
    """The runner answering, in the thread it was spoken to in."""

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
