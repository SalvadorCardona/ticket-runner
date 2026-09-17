"""Running the session, and the two ways a ticket comes back from one.

`prepare` decided everything; here it happens. One function starts the session
and closes the live block whatever becomes of it — `_run_session` — and two
say what a finished session was worth, depending on what the ticket had to
begin with.

**A ticket on a repository** works in a worktree of its own, cut from the
project's default branch, and comes back as commits, a push and a pull request.
The branch is replayed onto its base between the commits and the push, because
a session takes an hour and a base branch does not wait for it: what opens is a
pull request on top of what the repository holds now. Nothing is written into
the project itself, ever: the worktree is the isolation, and it is removed on
the way out — kept only when a run failed and the configuration asked for it.

**A ticket with no repository** works in an empty scratch directory and comes
back as `ANSWER.md`, appended to the Notion page it came from. Same session,
same prompt machinery, same reports; what differs is where the deliverable
lands, and that is the whole of the difference.

Both share the rule that a session ending badly is not the same thing as a
session that asked a question: one goes to failed with its trace, the other to
blocked with the question, and an exhausted quota goes to neither — see
`Reports._requeue`.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import git, progress, session, state, store
from . import prompt as prompt_module
from . import voice as voice_module
from .base import Base
from .ticket import Job, short_id


class Execution(Base):
    """A session started, and what its outcome makes of the ticket."""

    def execute(self, job: Job) -> dict:
        if self.dry_run:
            target = f"{job.branch} from {job.base}" if job.project.is_code else "document"
            self.say(f"    (dry run) {target}")
            return {"ticket": job.ticket.title, "id": job.ticket.id, "status": "dry-run"}
        return self._execute_code(job) if job.project.is_code else self._execute_document(job)

    def _run_session(self, job: Job, template: str) -> session.Outcome:
        text = prompt_module.build(
            template,
            project=job.project.name,
            title=job.ticket.title,
            body=job.body,
            repo=str(job.project.path or job.workdir),
            branch=job.branch,
            base=job.base,
            url=job.ticket.url,
            brief=job.project.brief,
            context=self.workspace.context,
            agent_name=job.agent.name,
            agent_brief=job.agent.brief,
            comments=job.comments,
            language=self.voice.instruction(),
            # A branch picked up from an earlier attempt: the session is told,
            # because a worktree that opens on somebody's half-done work and
            # reads as empty is how the same thing gets written twice.
            resumed=(
                f"- This ticket has run before, and its branch already carries what that "
                f"session committed, replayed on top of `{job.base}`. Read "
                f"`git log {job.base}..HEAD` and its diff first: you are continuing that "
                f"work, not starting it again.\n"
                if job.resumed
                else ""
            ),
        )
        log = job.log or state.log_file(short_id(job.ticket.id))
        # The ticket first, then its agent, then the runner: the narrower the
        # choice, the more deliberate it was.
        chosen = job.model or job.agent.model or self.config.runner.model
        live = job.live = self._live(job)
        try:
            outcome = self._session(job, text, log, chosen, live)
            if job.resume and session.lost(outcome):
                # A session Claude Code no longer has — pruned, filed on another
                # machine, or a worktree it cannot be resumed from. The ticket
                # and its branch are still here, so a fresh session starts from
                # everything except the thread of the interrupted one.
                #
                # Only *that* failure. A resumed session that asked a question,
                # timed out or crashed did so on its own account, and would do
                # it again: redoing it costs a second full session — under a
                # reserve whose whole point is to save credit — and throws away
                # what the first one had to say.
                self.say("    ↻ that session could not be picked up — starting a new one")
                job.session_id, job.resume = session.new_id(), False
                # Its own log, or the second attempt would open the first one's
                # with "w" and truncate the very transcript that explains it.
                log = log.with_name(f"{log.stem}-again{log.suffix}")
                outcome = self._session(job, text, log, chosen, live)
        except BaseException:
            # A session that dies still leaves a ticket saying “⏳ Live” and a
            # column stuck on whatever it was doing. Closing here is what makes
            # the page tell the truth on the way out too.
            if live:
                live.close(self.voice.say("live-interrupted"), ok=False)
            raise
        if self.config.runner.attach_sessions:
            # The session ran in a directory that is about to be deleted. Filed
            # under the project instead, it shows up in `claude --resume` there,
            # next to the sessions you started yourself.
            home = job.project.path or self.config.runner.workspace_root
            if session.relocate(outcome.session_id, home):
                job.session_home = home
                self.say(f"    session filed under {home}")
        if live:
            # The block's last word: what the session achieved, or which of the
            # ways of not achieving it this was. After the session has been
            # filed, because a run that went wrong puts the way back into it in
            # this very block — see `_filed` — and that sentence names where the
            # session now lives.
            said = self.voice
            if self._out_of_credit(outcome):
                closing, ended_well = said.say("live-waiting"), True
            elif outcome.ok:
                closing, ended_well = said.brief(outcome.summary, 120), True
            else:
                closing = said.say("live-blocked" if outcome.blocked else "live-stopped")
                ended_well = False
            live.close(closing, ok=ended_well)
        self._hold_credits(outcome)
        return outcome

    def _session(
        self,
        job: Job,
        text: str,
        log: Path,
        model: str,
        live: progress.Live | None,
    ) -> session.Outcome:
        """One attempt at this job's session, opened or carried on.

        A carried one is sent the short message instead of the frame: it has the
        ticket, the brief and the context already, and resending them would cost
        on every resumption what they cost once. See `prompt.CARRY_ON`.
        """
        if job.resume:
            text = prompt_module.carry_on(self.voice.instruction())
        opening = "picking session" if job.resume else "Claude session"
        self.say(f"    {opening} {job.session_id}{' · ' + model if model else ''} → {log}")
        return session.run(
            text,
            cwd=job.workdir,
            log=log,
            model=model,
            permission_mode=self.config.runner.permission_mode,
            timeout_minutes=self.config.runner.timeout_minutes,
            session_id=job.session_id,
            resume=job.resume,
            environment=self.environment,
            on_event=live.event if live else None,
        )

    def _live(self, job: Job) -> progress.Live | None:
        """The ticket's live report, or None when it is not wanted.

        Off in a dry run, since a dry run writes nothing anywhere, and off when
        `runner.progress` says so. Everything else it needs — the page, the
        board and the column — it already has.
        """
        if self.dry_run or not self.config.runner.progress:
            return None
        return progress.Live(
            self.client,
            job.ticket.page.id,
            database=self.database,
            property_name=self.config.notion.prop("progress"),
            interval=self.config.runner.progress_interval_seconds,
            words=self.voice,
            say=self.say,
        )

    # -- a ticket on a repository ----------------------------------------------

    def _execute_code(self, job: Job) -> dict:
        ticket, project = job.ticket, job.project

        if self.config.runner.fetch:
            git.fetch(project.path)
        try:
            worktree = git.add_worktree(project.path, job.workdir, job.branch, job.base)
        except git.GitError as error:
            return self._fail(ticket, self.voice.say("no-worktree"), str(error))
        if worktree.note:
            # A ticket that has run before: said out loud, because the session
            # about to start is continuing somebody's work rather than opening
            # on an empty branch, and the comment should carry that too.
            self.say("    · " + worktree.note.replace("`", ""))
            job.notes.append(worktree.note)
            job.resumed = worktree.reused

        try:
            outcome = self._run_session(
                job, prompt_module.template(self.config.runner.prompt_file)
            )
        except (OSError, FileNotFoundError) as error:
            git.remove_worktree(project.path, job.workdir)
            return self._fail(ticket, self.voice.say("no-session"), str(error))

        said = self.voice

        if self._out_of_credit(outcome):
            # Not a failure: there was nothing to work with. The worktree stays
            # where it is whatever `keep_worktree_on_failure` says — the branch
            # is what the next attempt picks up, commits and all, and throwing
            # it away would make the wait cost the work that came before it.
            return self._requeue(
                ticket,
                self.config.notion.state("ready"),
                outcome,
                said.say("credit-spent-kept", branch=job.branch)
                if git.commits_ahead(job.workdir, job.base)
                else "",
                home=job.session_home or job.project.path,
            )

        if not outcome.ok:
            reason = said.say("asked-something" if outcome.blocked else "session-failed")
            # An agent that asked a question is waiting for you; a session that
            # crashed is waiting for someone to look at the log. Different rows
            # on the board, when the board has somewhere to put them.
            detail = (outcome.summary if outcome.blocked else outcome.error) or ""
            kept = ""
            if self.config.runner.keep_worktree_on_failure:
                kept = said.say("worktree-kept", path=job.workdir, branch=job.branch)
            else:
                git.remove_worktree(project.path, job.workdir)
            return self._fail(
                ticket,
                reason,
                detail,
                blocked=outcome.blocked,
                question=detail if outcome.blocked else "",
                note=self._filed(job, outcome, kept),
            )

        commits = git.commits_ahead(job.workdir, job.base)
        if commits == 0:
            if not git.is_dirty(job.workdir):
                git.remove_worktree(project.path, job.workdir)
            return self._fail(
                ticket,
                said.say("nothing-committed"),
                outcome.summary,
                blocked=True,
                question=outcome.summary,
                note=self._filed(job, outcome),
            )

        pull_request = ""
        replayed = False
        if self.config.runner.push and self.config.runner.rebase:
            # The base has moved under this session: the ticket started on the
            # `main` of an hour ago, and one of the other nine tickets aimed at
            # this repository has been merged since. Replaying the branch now is
            # what makes the pull request open on top of what the repository
            # actually holds rather than as a conflict somebody has to come and
            # sort out by hand.
            #
            # A rebase that cannot be done is not a reason to keep the work
            # here: `git.rebase` puts the branch back as it was, the pull
            # request opens all the same, and the conflict is said on the ticket
            # — which is the one place a person will look at it.
            if self.config.runner.fetch:
                git.fetch(project.path)
            start = (
                f"origin/{job.base}"
                if git.has_ref(project.path, f"origin/{job.base}")
                else job.base
            )
            was = git.head(job.workdir)
            if failure := git.rebase(job.workdir, start):
                self.say(f"    ! not replayed onto {start}: {failure}")
                job.notes.append(said.say("rebase-refused", base=start, error=failure))
            elif git.head(job.workdir) != was:
                replayed = True
                self.say(f"    · replayed onto {start}")
                job.notes.append(said.say("rebased-onto", base=start))
        if self.config.runner.push:
            pushed = git.push(
                job.workdir,
                job.branch,
                force=worktree.reused or replayed,
                accounts=self.config.github,
            )
            if not pushed.ok:
                return self._fail(
                    ticket,
                    said.say("push-refused"),
                    pushed.err or pushed.out,
                    note=self._filed(
                        job, outcome, said.say("push-refused-detail", branch=job.branch)
                    ),
                )
            if self.config.runner.open_pull_request:
                body = (
                    f"{outcome.summary}\n\n"
                    f"---\nNotion ticket: {ticket.url}\n"
                    f"Claude Code session: `{outcome.session_id}`\n"
                    f"Opened by ticket-runner ({commits} commit{'s' if commits > 1 else ''})."
                )
                try:
                    pull_request = git.open_pull_request(
                        job.workdir, ticket.title, body, job.base, accounts=self.config.github
                    )
                except git.GitError as error:
                    self.say(f"    ! pull request not opened: {error}")
                    job.notes.append(said.say("no-pull-request-opened", error=error))

        git.remove_worktree(project.path, job.workdir)

        # With a pull request the ticket is not finished, it is waiting for you:
        # it goes to "in review", and `close_merged` takes it to done once you
        # have merged. Without one there is nothing to wait for — and on a board
        # with no review column, `review` is `done` and nothing changes.
        values: dict[str, object] = {
            self.config.notion.prop("status"): self.config.notion.state(
                "review" if pull_request else "done"
            ),
            self.config.notion.prop("agent"): self.agent_label,
        }
        if pull_request:
            values[self.config.notion.prop("pull_request")] = pull_request
        values[self.config.notion.prop("session")] = self._session_value(
            outcome.session_id, job.session_home or project.path
        )
        values.update(self._measures(outcome))
        self._set(ticket, **values)

        # Where the work is comes first, because it is what you act on: the
        # pull request when there is one, and the branch when there is not.
        facts = (
            said.pull_request(pull_request) or said.say("on-branch", branch=job.branch),
            said.count(commits, "commit"),
            *said.spent(outcome.seconds, outcome.cost_usd),
        )
        brief = said.brief(outcome.summary)
        self._comment(
            ticket,
            said.report(
                said.verdict("review", *facts),
                brief,
                pull_request,
                *(said.brief(note) for note in job.notes),
            ),
        )
        self.say(f"    ✓ {ticket.title} — {pull_request or job.branch}")
        self._tell(
            "done",
            ticket,
            "review",
            said.report(said.facts(*facts), brief, pull_request),
        )
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "done",
            "project": project.name,
            "branch": job.branch,
            "pull_request": pull_request,
            "session": outcome.session_id,
            "commits": commits,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }

    # -- a ticket that has none -------------------------------------------------

    def _execute_document(self, job: Job) -> dict:
        """A ticket with no repository: the deliverable is the ticket's own page."""
        ticket = job.ticket
        job.workdir.mkdir(parents=True, exist_ok=True)
        try:
            outcome = self._run_session(job, prompt_module.template(
                self.config.runner.document_prompt_file, prompt_module.DOCUMENT
            ))
        except (OSError, FileNotFoundError) as error:
            return self._fail(ticket, self.voice.say("no-session"), str(error))

        said = self.voice
        if self._out_of_credit(outcome):
            # The working directory is left as it is: whatever the session had
            # written into ANSWER.md before the quota ran out is what the next
            # attempt opens on.
            return self._requeue(
                ticket,
                self.config.notion.state("ready"),
                outcome,
                home=job.session_home,
            )

        answer_file = job.workdir / "ANSWER.md"
        content = ""
        if answer_file.exists():
            content = answer_file.read_text(encoding="utf-8", errors="replace").strip()

        if not outcome.ok or not content:
            reason = said.say(
                "no-answer" if outcome.blocked or not content else "session-failed"
            )
            detail = (outcome.summary if outcome.blocked else outcome.error) or ""
            if not content and outcome.ok:
                detail = said.say("no-answer-detail", summary=outcome.summary)
            kept = ""
            if self.config.runner.keep_worktree_on_failure:
                kept = said.say("workdir-kept", path=job.workdir)
            else:
                shutil.rmtree(job.workdir, ignore_errors=True)
            return self._fail(
                ticket,
                reason,
                detail,
                blocked=outcome.blocked or not content,
                question=detail,
                note=self._filed(job, outcome, kept),
            )

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        try:
            blocks = self.client.append_markdown(
                ticket.page.id,
                f"\n---\n{content}\n\n*ticket-runner · {stamp} · session `{outcome.session_id}`*",
            )
        except store.StoreError as error:
            return self._fail(
                ticket,
                said.say("answer-not-written"),
                voice_module.line(error),
                note=self._filed(
                    job, outcome, said.say("answer-on-disk", path=answer_file)
                ),
            )

        shutil.rmtree(job.workdir, ignore_errors=True)
        self._set(
            ticket,
            **{
                self.config.notion.prop("status"): self.config.notion.state("done"),
                self.config.notion.prop("agent"): self.agent_label,
                self.config.notion.prop("session"): self._session_value(
                    outcome.session_id, job.session_home
                ),
                **self._measures(outcome),
            },
        )
        facts = (
            said.say("in-the-page"),
            said.count(blocks, "block"),
            *said.spent(outcome.seconds, outcome.cost_usd),
        )
        brief = said.brief(outcome.summary)
        self._comment(ticket, said.report(said.verdict("read", *facts), brief))
        self.say(f"    ✓ {ticket.title} — {blocks} block(s) written to the ticket")
        self._tell("done", ticket, "read", said.report(said.facts(*facts), brief))
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "done",
            "project": job.project.name,
            "kind": "document",
            "blocks": blocks,
            "session": outcome.session_id,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }
