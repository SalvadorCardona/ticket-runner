"""The last column: carrying out the tickets you have validated.

With *Ready*, the only other place on the board where moving a ticket sets
something off. *In review* asks a question — is this what you wanted? — and
moving the ticket to *Validated* answers it: yes, and now do the last thing.
What that last thing is, the ticket already says: one that came back as a pull
request has a merge waiting, one that came back as a text has a publication
waiting. Which leaves the decision exactly where it was — nothing is merged or
published because a session felt sure of itself, only because you moved a
ticket one column to the right.

The two are not carried out the same way, and the asymmetry is the module.
A merge is two `gh` calls and is done in the pass's own thread — three and a
rebase when GitHub refuses it for being behind, which is what a repository
taking ten tickets a day does to a pull request opened this morning. A
publication is a Claude session, so publications run the way tickets run — side
by side, never more than `max_concurrent` at once — and are claimed before they
are done, because publishing twice is the one mistake this must not make.

And the column is read more than once. `deliver` settles it at the top of a
pass; `delivering` is the same reading, offered to a pass that is already
running, so that a ticket validated at 14:20 is merged at 14:20 rather than
when the two-hour session that began at 14:04 finally ends — see `_work`.
"""

from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import agents, git, notion, session, state
from . import prompt as prompt_module
from . import voice as voice_module
from .base import Base
from .config import state_dir
from .projects import Project
from .ticket import Job, Ticket, short_id


class Delivery(Base):
    """What a validated ticket sets off, and how far it is taken."""

    def deliver(self) -> list[dict]:
        """Carry out the tickets you have validated.

        The last column, and with *Ready* one of the only two where moving a
        ticket sets something off. *In review* asks a question — is this what you
        wanted? — and moving the ticket to *Validated* answers it: yes, and now
        do the last thing. What that last thing is, the ticket already says. One
        that came back as a pull request has a merge waiting; one that came back
        as a text has a publication waiting — a post, an email, a page. The
        runner does it, and only then is the ticket done.

        Which leaves the decision exactly where it was: nothing is merged or
        published because a session felt sure of itself, only because you moved
        a ticket one column to the right.

        Optional, like the columns before it. A board whose status property does
        not offer the validated option has no such gesture and is never even
        queried — `ticket-runner init` adds the option to a board that predates
        it, and until then you merge by hand as before.

        A date on the ticket is honoured here too. `Scheduled` means "not before
        this moment" wherever it is written, so a validated ticket dated Thursday
        is left in its column until Thursday and carried out then — which is what
        turns the board into a calendar for work that is *finished*: the post is
        written, you have read it and said yes, and it still goes out at the hour
        you chose. Merges wait the same way, for the same reason: one column, one
        rule.

        Merges are two `gh` calls and are done one after another. A publication
        is a Claude session, so publications are run the way tickets are run:
        side by side, never more than `max_concurrent` at once. They still
        finish before the queue is looked at — a ticket you have accepted comes
        before a ticket nobody has read yet — but a board with four of them
        costs one session's wait rather than four.

        This is the reading a pass does at its top, on a board nothing is
        running against yet. The same column is read again while the pass runs,
        by `delivering`, which is where the sorting actually lives.
        """
        results, publishing = self.delivering()
        return results + self._publish_all(publishing)

    def delivering(
        self, taken: set[str] | None = None
    ) -> tuple[list[dict], list[tuple[Ticket, Project]]]:
        """Sort the validated column: what is settled here, what needs a session.

        Two kinds of work sit in that column, and only one of them costs a
        place. A merge is two `gh` calls, so it happens here and now, in the
        thread that asked — which is what lets a pass with every place taken
        still merge a pull request you validated while it ran. A publication is
        a Claude session, so it is only *named* here: the caller runs it, in the
        pool it already keeps, and `deliver` is the caller that runs them all at
        once at the top of a pass.

        `taken` is what this pass has already carried out. Notion may still be
        serving the status a publication in flight has just overwritten, and
        publishing twice is the one mistake this must not make — so a ticket the
        caller has already taken off the column is skipped rather than trusted
        to have moved.

        A board that will not answer leaves the column where it is: the next
        look asks again, and neither a pass in flight nor the sessions in it
        have any business failing over a reading of a column they are not in.
        """
        settings = self.config.notion
        taken = taken or set()
        results: list[dict] = []
        publishing: list[tuple[Ticket, Project]] = []
        held: list[tuple[Ticket, datetime]] = []
        now = datetime.now().astimezone()
        try:
            pages = self.validated()
        except notion.NotionError as error:
            self.say(f"  ! the validated column could not be read: {voice_module.line(error)}")
            return [], []
        for page in pages:
            ticket = Ticket(page)
            if ticket.id in taken:
                continue
            url = str(notion.read(page, settings.prop("pull_request")) or "")
            moment = self._moment(ticket)
            if moment and moment > now:
                # A date says "not before this moment", and it says it here as
                # much as in the ready column: the post accepted on Tuesday for
                # Thursday goes out on Thursday. Merges wait with publications —
                # validating asks one question, and the date answers *when*.
                held.append((ticket, moment))
                if not url.startswith("http"):
                    # Its comments travel into the publication when the moment
                    # comes, exactly as a scheduled ready ticket's do, so the
                    # runner does not also answer them in the meantime. A ticket
                    # with a pull request is left talkable-to: there, a comment
                    # is a conversation about work already done.
                    self._claimed.add(ticket.id)
                continue
            if self.dry_run:
                # A dry run says what it would do here as everywhere else. It
                # matters more here than anywhere: this is the only column whose
                # gesture cannot be taken back.
                what = f"merge {url}" if url.startswith("http") else "publish what it holds"
                self.say(f"  (dry run) {ticket.title} — validated: would {what}")
                results.append({"ticket": ticket.title, "id": ticket.id, "status": "dry-run"})
                continue
            if url.startswith("http"):
                done = self._merge(ticket, url)
                if done:
                    results.append(done)
                continue
            if self.under_reserve():
                # A publication is a session; a merge is two `gh` calls. So the
                # merges above happen and this one waits, left validated, for
                # the pass that has credit again — the decision to publish it is
                # not being reconsidered, only postponed.
                self._claimed.add(ticket.id)
                continue
            project = self._project_of(ticket)
            if project.is_code:
                # A ticket on a repository carries a pull request or it carries
                # nothing: there is no text on the page to publish, and starting
                # a session to look for one would be guessing.
                said = self.voice
                results.append(
                    self._fail(
                        ticket,
                        said.say("no-pull-request"),
                        said.say("no-pull-request-detail", project=project.name),
                        blocked=True,
                        question=said.say("no-pull-request-question"),
                    )
                )
                continue
            publishing.append((ticket, project))
        self._deferred = sorted(held, key=lambda pair: pair[1])
        return results, publishing

    def validated(self) -> list[notion.Page]:
        """The pages sitting in the validated column.

        None at all where the board has no such column: the gesture is opt-in,
        and a board that never offers it is never even queried.
        """
        settings = self.config.notion
        validated = settings.state("validated")
        if validated in (settings.state("review"), settings.state("done")):
            return []
        status_property = settings.prop("status")
        if validated not in self.client.options(self.database, status_property):
            return []
        kind = self.client.schema(self.database).get(status_property, "status")
        return self.client.query(
            self.database, {"property": status_property, kind: {"equals": validated}}
        )

    def scheduled(self) -> list[tuple[Ticket, datetime]]:
        """Validated tickets whose moment has not come, soonest first.

        What `deliver` will carry out later rather than now. Read for the sake
        of saying so — a post you accepted on Tuesday for Thursday is as much a
        thing waiting to happen as a ticket sitting in ready with a date on it,
        and `ticket-runner list` shows the whole calendar rather than half of it.
        """
        now = datetime.now().astimezone()
        held: list[tuple[Ticket, datetime]] = []
        for page in self.validated():
            ticket = Ticket(page)
            moment = self._moment(ticket)
            if moment and moment > now:
                held.append((ticket, moment))
        return sorted(held, key=lambda pair: pair[1])

    def _merge(self, ticket: Ticket, url: str) -> dict | None:
        """A validated pull request: merge it, and take the ticket to done."""
        state_of = git.pull_request_state(url, self.config.github)
        if not state_of:
            # The same rule as `close_merged`: a ticket is never moved on an
            # answer GitHub did not give. The next run asks again.
            self.say(f"  · {ticket.title} — GitHub did not answer about {url}, left validated")
            return None
        said = self.voice
        if state_of == "CLOSED":
            return self._fail(
                ticket,
                said.say("pull-request-closed"),
                said.say("pull-request-closed-detail", url=url),
                blocked=True,
                question=said.say("pull-request-closed-question", url=url),
            )
        method = self.config.runner.merge_method
        how = said.say("merged-before")
        notes: list[str] = []
        if state_of != "MERGED":
            try:
                git.merge_pull_request(url, method, self.config.github)
            except git.GitError as error:
                replayed = self._replay(ticket, url, error)
                if not replayed:
                    return self._fail(
                        ticket,
                        said.say("merge-refused"),
                        f"{url}\n\n{error}",
                        blocked=True,
                        question=said.say(
                            "merge-refused-question", error=voice_module.line(error)
                        ),
                    )
                notes.append(replayed)
                try:
                    git.merge_pull_request(url, method, self.config.github)
                except git.GitError as error:
                    return self._fail(
                        ticket,
                        said.say("merge-refused"),
                        f"{url}\n\n{replayed}\n\n{error}",
                        blocked=True,
                        question=said.say(
                            "merge-refused-question", error=voice_module.line(error)
                        ),
                    )
            how = said.say("merged-with", method=method)
        self.say(f"  ✓ {ticket.title} — pull request merged, moved to done")
        self._set(
            ticket,
            **{self.config.notion.prop("status"): self.config.notion.state("done")},
        )
        self._comment(
            ticket,
            said.report(said.verdict("merged", said.pull_request(url), how), url, *notes),
        )
        return {"ticket": ticket.title, "id": ticket.id, "status": "done", "merged": url}

    def _replay(self, ticket: Ticket, url: str, refusal: git.GitError) -> str:
        """Put the branch back on top of its base, when that is what was wrong.

        A pull request opened this morning is behind by noon on a repository
        that takes ten tickets a day: GitHub refuses the merge, and the refusal
        is about the *branch*, not about the work. So the branch is replayed
        onto its base and pushed again, and the merge is asked a second time —
        which is exactly the gesture you would make by hand, and the one nobody
        should have to make ten times a day.

        Only that refusal. A check still red and a review still missing are
        refusals a rebase does not answer, and pushing the branch again would
        only spend a CI run to be refused the same way. Says what was done, so
        that the report carries it; empty means nothing was — and the caller
        then reports the refusal as it came.
        """
        if not self.config.runner.rebase or not git.is_behind(refusal):
            return ""
        branch, base = git.pull_request_branches(url, self.config.github)
        project = self._project_of(ticket)
        if not branch or not project.is_code:
            return ""
        workdir = state_dir() / "scratch" / f"rebase-{short_id(ticket.id)}"
        self.say(f"  · {ticket.title} — merge refused, replaying {branch} onto {base}")
        failure = git.replay_pushed(
            project.path, branch, base, workdir, self.config.github
        )
        if failure:
            self.say(f"    ! {branch} not replayed: {failure}")
            return ""
        return self.voice.say("merge-rebased", branch=branch, base=base)

    def _publish_all(self, publishing: list[tuple[Ticket, Project]]) -> list[dict]:
        """Every validated publication of this pass, up to `max_concurrent` at once.

        A batch, unlike the ticket queue in `_work`, and deliberately so: the
        whole list is handed to `pool.map`, which starts the next publication as
        soon as a worker frees, so no place is ever left idle. What it does not
        do is look at the board again mid-list — and it has no reason to: this
        is the top of a pass, and a ticket validated a minute later is picked up
        by `_work`, which looks at that column for as long as the pass lasts.
        """
        if not publishing:
            return []
        if len(publishing) == 1:
            done = self._publish(*publishing[0])
            return [done] if done else []
        workers = min(len(publishing), max(1, self.config.runner.max_concurrent))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda pair: self._publish(*pair), publishing))
        return [done for done in results if done]

    def _publish(self, ticket: Ticket, project: Project) -> dict | None:
        """A validated ticket with no pull request: publish what it holds.

        The Instagram post drafted last week, the email written into the page,
        the announcement waiting on somebody to press send: work whose last step
        is not a commit. A session is given the page as it stands — the ask, and
        the answer a previous run wrote under it — and told to put it where the
        ticket says, changing nothing on the way.

        Claimed like any other work, by moving the ticket to "in progress":
        publishing twice is the one mistake this must not make, and two runners
        looking at the same board would otherwise both take it. The column it
        was claimed from is written down first — see `state.claim` — so that a
        run dying mid-publication comes back as a question rather than as a
        second post.
        """
        short = short_id(ticket.id)
        # The role, if the ticket names one: the account to post to and the
        # voice to post in are exactly the sort of thing an agent page carries.
        role = notion.read(ticket.page, self.config.notion.prop("role")) or []
        job = Job(
            ticket,
            project,
            branch="",
            base="",
            workdir=state_dir() / "scratch" / f"deliver-{short}",
            body=self._body(ticket),
            session_id=session.new_id(),
            log=state.log_file(short),
            model=str(notion.read(ticket.page, self.config.notion.prop("model")) or ""),
            agent=(
                agents.resolve(self.client, role[0], self.config.notion.prop("model"))
                if role
                else agents.Agent()
            ),
            comments=self.discussion(ticket),
        )
        self.say(f"  ▸ {ticket.title}\n    validated · publishing what the ticket holds")
        if self.dry_run:
            return None
        # A comment on a ticket being published is a conversation about the
        # work, not an instruction: the same rule as a ticket about to be run.
        self._claimed.add(ticket.id)
        state.claim(ticket.id, self.config.notion.state("validated"))
        self._set(
            ticket,
            **{
                self.config.notion.prop("status"): self.config.notion.state("running"),
                self.config.notion.prop("agent"): self.agent_label,
                # Unticked by the same write that claims it: the wait is over
                # the moment something is started, and a tick left behind would
                # have the next pass resume a session that is running.
                self.config.notion.prop("waiting"): False,
                self.config.notion.prop("session"): self._session_value(
                    job.session_id, project.path
                ),
            },
        )
        job.workdir.mkdir(parents=True, exist_ok=True)
        try:
            outcome = self._run_session(job, prompt_module.template(
                self.config.runner.delivery_prompt_file, prompt_module.DELIVERY
            ))
        except (OSError, FileNotFoundError) as error:
            state.release(ticket.id)
            return self._fail(ticket, self.voice.say("no-session"), str(error))
        # Every road from here writes a status that is not "in progress", so the
        # note about where it came from has done its work.
        state.release(ticket.id)
        said = self.voice
        if self._out_of_credit(outcome):
            # Back to validated, not to ready: the decision to publish it has
            # already been taken, and the wait does not take it back.
            return self._requeue(ticket, self.config.notion.state("validated"), outcome)

        if not outcome.ok:
            # Kept, always: a publication that half happened is exactly the log
            # somebody is going to want to read before trying again.
            return self._fail(
                ticket,
                said.say("not-published"),
                outcome.summary or outcome.error,
                blocked=outcome.blocked,
                question=outcome.summary,
                note=self._filed(job, outcome, said.say("workdir-kept", path=job.workdir)),
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
        facts = said.spent(outcome.seconds, outcome.cost_usd)
        brief = said.brief(outcome.summary)
        self._comment(ticket, said.report(said.verdict("published", *facts), brief))
        self.say(f"    ✓ {ticket.title} — published")
        self._tell("done", ticket, "published", said.report(said.facts(*facts), brief))
        return {
            "ticket": ticket.title,
            "id": ticket.id,
            "status": "done",
            "project": project.name,
            "kind": "delivery",
            "session": outcome.session_id,
            "seconds": round(outcome.seconds, 1),
            "cost_usd": outcome.cost_usd,
        }
