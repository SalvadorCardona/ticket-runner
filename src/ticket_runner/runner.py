"""One run: take the ready tickets, do them, report back to Notion.

A run has two phases, and the order matters.

**First, sequentially:** read the ready tickets, locate their project, and
*claim* them by moving them to "in progress". Claiming before working is what
stops the timer from picking up a ticket already taken — and doing it
sequentially keeps two tickets from racing over the same repository index.

**Then, in parallel:** each claimed ticket gets its worktree, its Claude
session, its branch and its pull request. A ticket that fails takes only itself
down: it goes back to "draft" with the reason in a comment, while the others
carry on.
"""

from __future__ import annotations

import re
import shutil
import socket
import unicodedata
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import git, notion, notify, prompt as prompt_module, session, state
from .config import PRIORITIES, Config, state_dir
from .projects import Project, Resolver


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
    notes: list[str] = field(default_factory=list)


def short_id(page_id: str) -> str:
    """Eight characters that actually tell two tickets apart.

    Notion page IDs are time-ordered: two tickets created the same day share a
    long *prefix*. Taking the first eight gave both of the first two tickets
    written for this tool the same short id — which would have had them fight
    over one scratch directory. The tail is where the entropy is.
    """
    return page_id.replace("-", "")[-8:]


def slugify(text: str, limit: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:limit].rstrip("-")) or "ticket"


class Runner:
    def __init__(self, config: Config, *, dry_run: bool = False, quiet: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run or config.runner.dry_run
        self.quiet = quiet
        self.client = notion.Client(config.notion.token)
        self.resolver = Resolver(config.runner.workspace_root, config.projects)
        self.agent_label = f"ticket-runner@{socket.gethostname()}"
        self._database = ""

    @property
    def database(self) -> str:
        """The tickets database ID, resolved once for the whole session."""
        if not self._database:
            self._database = self.client.resolve_database(self.config.notion.tickets_database)
        return self._database

    # -- output --------------------------------------------------------------

    def say(self, message: str) -> None:
        if not self.quiet:
            print(message, flush=True)

    def _notify(self, title: str, body: str, *, urgent: bool = False) -> None:
        if self.config.runner.notify and not self.dry_run:
            notify.send(title, body, urgent=urgent)

    # -- reading -------------------------------------------------------------

    def ready(self) -> list[Ticket]:
        """Ready tickets, most urgent first, then oldest first.

        Order matters as soon as more tickets are ready than `max_concurrent`
        allows: without it, which ticket runs is whatever Notion returned first.
        Age breaks ties so that nothing can be starved by a steady trickle of
        newer work.
        """
        tickets = [Ticket(page) for page in self.client.query(self.database, self._ready_filter())]
        priorities = {name: index for index, name in enumerate(PRIORITIES)}
        default = priorities.get("Normal", len(PRIORITIES))

        def rank(ticket: Ticket) -> tuple[int, str]:
            value = notion.read(ticket.page, self.config.notion.prop("priority"))
            return (priorities.get(str(value), default), ticket.page.raw.get("created_time", ""))

        return sorted(tickets, key=rank)

    def _ready_filter(self) -> dict:
        status_property = self.config.notion.prop("status")
        kind = self.client.schema(self.database).get(status_property, "status")
        return {"property": status_property, kind: {"equals": self.config.notion.state("ready")}}

    def sweep(self) -> int:
        """Put back tickets a dead runner left claimed.

        A run holds an exclusive lock, so at the start of a run no other run of
        ours can be in flight — any ticket still marked "in progress" under this
        host's name was therefore abandoned, by a reboot, a `systemctl stop`, or
        a crash. It goes back to ready rather than staying stuck for good.

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
            if notion.read(page, self.config.notion.prop("agent")) != self.agent_label:
                continue
            edited = page.raw.get("last_edited_time", "")
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(edited)
            except ValueError:
                age = timedelta(days=1)
            if age < timedelta(minutes=2):
                continue
            ticket = Ticket(page)
            self.say(f"  ↺ {ticket.title} — claimed but no run alive, put back")
            self._set(ticket, **{status_property: self.config.notion.state("ready")})
            self._comment(
                ticket,
                f"{self.agent_label} — put back in the queue.\n"
                f"This ticket was still claimed while no run was in flight, "
                f"{age.total_seconds() / 60:.0f} min after it was last touched: "
                "its runner was stopped or died mid-session. It will be picked up again.",
            )
            recovered += 1
        return recovered

    def fetch_one(self, reference: str) -> Ticket:
        page_id = reference.strip()
        if "://" in page_id:
            page_id = page_id.split("?")[0].rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[-1]
        return Ticket(self.client.page(page_id.replace("-", "")))

    # -- writing -------------------------------------------------------------

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
        except notion.NotionError as error:
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
            return session.deep_link(session_id, home or self.config.runner.workspace_root)
        return session_id

    def _comment(self, ticket: Ticket, text: str) -> None:
        if self.dry_run:
            return
        try:
            self.client.comment(ticket.page.id, text)
        except notion.NotionError as error:
            hint = ""
            if "403" in str(error):
                hint = (
                    "\n      the integration lacks comment capability: "
                    "notion.so/my-integrations → your integration → Capabilities → "
                    "Insert comments"
                )
            self.say(f"    ! Notion refused the comment: {error}{hint}")

    def _fail(
        self, ticket: Ticket, reason: str, detail: str = "", *, blocked: bool = False
    ) -> dict:
        outcome = "blocked" if blocked else "failed"
        self.say(f"    ✗ {ticket.title} — {reason}")
        self._notify(
            f"{'Blocked' if blocked else 'Failed'} · {ticket.title}", reason, urgent=not blocked
        )
        self._set(ticket, **{self.config.notion.prop("status"): self.config.notion.state(outcome)})
        self._comment(
            ticket,
            f"{self.agent_label} — {outcome}.\n{reason}" + (f"\n\n{detail}" if detail else ""),
        )
        return {"ticket": ticket.title, "id": ticket.id, "status": outcome, "reason": reason}

    # -- preparation ---------------------------------------------------------

    def prepare(self, ticket: Ticket) -> Job | None:
        """Locate the project and claim the ticket. None if it is unusable."""
        relation = notion.read(ticket.page, self.config.notion.prop("project")) or []
        if not relation:
            self._fail(
                ticket,
                "no project linked: the runner has no repository to work in",
                blocked=True,
            )
            return None
        try:
            project = self.resolver.resolve(self.client, relation[0])
        except (LookupError, notion.NotionError) as error:
            self._fail(ticket, "project not found on disk", str(error), blocked=True)
            return None

        short = short_id(ticket.id)
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

        try:
            body = self.client.blocks_text(ticket.page.id)
        except notion.NotionError as error:
            self._fail(ticket, "ticket content unreadable", str(error))
            return None

        job = Job(
            ticket,
            project,
            branch,
            base,
            workdir,
            body,
            session_id=session.new_id(),
            log=state.log_file(short),
            model=str(notion.read(ticket.page, self.config.notion.prop("model")) or ""),
        )
        where = f"{project.path} · {branch}" if project.is_code else "document → Notion"
        self.say(f"  → {ticket.title}\n    {project.name} · {where}")
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

    # -- execution -----------------------------------------------------------

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
        )
        log = job.log or state.log_file(short_id(job.ticket.id))
        chosen = job.model or self.config.runner.model
        self.say(f"    Claude session {job.session_id}{' · ' + chosen if chosen else ''} → {log}")
        outcome = session.run(
            text,
            cwd=job.workdir,
            log=log,
            model=job.model or self.config.runner.model,
            permission_mode=self.config.runner.permission_mode,
            timeout_minutes=self.config.runner.timeout_minutes,
            session_id=job.session_id,
        )
        if self.config.runner.attach_sessions:
            # The session ran in a directory that is about to be deleted. Filed
            # under the project instead, it shows up in `claude --resume` there,
            # next to the sessions you started yourself.
            home = job.project.path or self.config.runner.workspace_root
            if session.relocate(outcome.session_id, home):
                job.session_home = home
                self.say(f"    session filed under {home}")
        return outcome

    def _trace(self, job: Job, outcome: session.Outcome) -> str:
        picker = f", or pick it from `claude` in `{job.session_home}`" if job.session_home else ""
        return (
            f"Session: `{outcome.session_id}` — `{outcome.resume_command}`{picker}\n"
            f"Log: `{outcome.log}`"
        )

    def _execute_document(self, job: Job) -> dict:
        """A ticket with no repository: the deliverable is the Notion page."""
        ticket = job.ticket
        job.workdir.mkdir(parents=True, exist_ok=True)
        try:
            outcome = self._run_session(job, prompt_module.template(
                self.config.runner.document_prompt_file, prompt_module.DOCUMENT
            ))
        except (OSError, FileNotFoundError) as error:
            return self._fail(ticket, "Claude session could not be started", str(error))

        trace = self._trace(job, outcome)
        answer_file = job.workdir / "ANSWER.md"
        content = ""
        if answer_file.exists():
            content = answer_file.read_text(encoding="utf-8", errors="replace").strip()

        if not outcome.ok or not content:
            reason = (
                "the agent stopped without answering"
                if outcome.blocked or not content
                else "the session failed"
            )
            detail = (outcome.summary if outcome.blocked else outcome.error) or ""
            if not content and outcome.ok:
                detail = f"{outcome.summary}\n\nNo ANSWER.md was written."
            kept = ""
            if self.config.runner.keep_worktree_on_failure:
                kept = f"\nWorking directory kept: `{job.workdir}`"
            else:
                shutil.rmtree(job.workdir, ignore_errors=True)
            return self._fail(
                ticket, reason, f"{detail}\n\n{trace}{kept}", blocked=outcome.blocked or not content
            )

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        try:
            blocks = self.client.append_markdown(
                ticket.page.id,
                f"\n---\n{content}\n\n*ticket-runner · {stamp} · session `{outcome.session_id}`*",
            )
        except notion.NotionError as error:
            return self._fail(
                ticket,
                "the answer could not be written to the ticket",
                f"{error}\n\nIt is still on disk: `{answer_file}`\n{trace}",
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
        cost = f" · ${outcome.cost_usd:.3f}" if outcome.cost_usd else ""
        self._comment(
            ticket,
            f"{self.agent_label} — done.\n{outcome.summary}\n\n"
            f"Written into this page: {blocks} block(s).\n{trace}\n"
            f"{outcome.turns} turns · {outcome.seconds / 60:.1f} min{cost}",
        )
        self.say(f"    ✓ {ticket.title} — {blocks} block(s) written to the ticket")
        self._notify(f"Ready to review · {ticket.title}", f"Written into the Notion ticket.")
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

    def _execute_code(self, job: Job) -> dict:
        ticket, project = job.ticket, job.project

        if self.config.runner.fetch:
            git.fetch(project.path)
        try:
            git.add_worktree(project.path, job.workdir, job.branch, job.base)
        except git.GitError as error:
            return self._fail(ticket, "worktree could not be created", str(error))

        try:
            outcome = self._run_session(
                job, prompt_module.template(self.config.runner.prompt_file)
            )
        except (OSError, FileNotFoundError) as error:
            git.remove_worktree(project.path, job.workdir)
            return self._fail(ticket, "Claude session could not be started", str(error))

        trace = self._trace(job, outcome)

        if not outcome.ok:
            reason = "the agent stopped without deciding" if outcome.blocked else "the session failed"
            # An agent that asked a question is waiting for you; a session that
            # crashed is waiting for someone to look at the log. Different rows
            # on the board, when the board has somewhere to put them.
            detail = (outcome.summary if outcome.blocked else outcome.error) or ""
            kept = ""
            if self.config.runner.keep_worktree_on_failure:
                kept = f"\nWorktree kept: `{job.workdir}` (branch `{job.branch}`)"
            else:
                git.remove_worktree(project.path, job.workdir)
            return self._fail(ticket, reason, f"{detail}\n\n{trace}{kept}", blocked=outcome.blocked)

        commits = git.commits_ahead(job.workdir, job.base)
        if commits == 0:
            if not git.is_dirty(job.workdir):
                git.remove_worktree(project.path, job.workdir)
            return self._fail(
                ticket,
                "the session declared itself done without a single commit",
                f"{outcome.summary}\n\n{trace}",
                blocked=True,
            )

        pull_request = ""
        if self.config.runner.push:
            pushed = git.push(job.workdir, job.branch)
            if not pushed.ok:
                return self._fail(
                    ticket,
                    "commits made but the push was refused",
                    f"{pushed.err or pushed.out}\n\nLocal branch `{job.branch}` kept.\n{trace}",
                )
            if self.config.runner.open_pull_request:
                body = (
                    f"{outcome.summary}\n\n"
                    f"---\nNotion ticket: {ticket.url}\n"
                    f"Claude Code session: `{outcome.session_id}`\n"
                    f"Opened by ticket-runner ({commits} commit{'s' if commits > 1 else ''})."
                )
                try:
                    pull_request = git.open_pull_request(job.workdir, ticket.title, body, job.base)
                except git.GitError as error:
                    self.say(f"    ! pull request not opened: {error}")
                    job.notes.append(f"Pull request not opened: {error}")

        git.remove_worktree(project.path, job.workdir)

        values: dict[str, object] = {
            self.config.notion.prop("status"): self.config.notion.state("done"),
            self.config.notion.prop("agent"): self.agent_label,
        }
        if pull_request:
            values[self.config.notion.prop("pull_request")] = pull_request
        values[self.config.notion.prop("session")] = self._session_value(
            outcome.session_id, job.session_home or project.path
        )
        values.update(self._measures(outcome))
        self._set(ticket, **values)

        cost = f" · ${outcome.cost_usd:.3f}" if outcome.cost_usd else ""
        notes = ("\n" + "\n".join(job.notes)) if job.notes else ""
        self._comment(
            ticket,
            f"{self.agent_label} — done.\n{outcome.summary}\n\n"
            f"Branch `{job.branch}` · {commits} commit(s)"
            + (f" · {pull_request}" if pull_request else " · no pull request")
            + notes
            + f"\n{trace}\n{outcome.turns} turns · {outcome.seconds / 60:.1f} min{cost}",
        )
        self.say(f"    ✓ {ticket.title} — {pull_request or job.branch}")
        self._notify(
            f"Ready to review · {ticket.title}",
            pull_request or f"Branch {job.branch}, {commits} commit(s)",
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

    # -- a full run ----------------------------------------------------------

    def tick(self, *, limit: int | None = None, reference: str = "") -> list[dict]:
        if reference:
            tickets = [self.fetch_one(reference)]
            self.say(f"Requested ticket: {tickets[0].title}")
        else:
            if not self.dry_run:
                self.sweep()
            tickets = self.ready()
            if not tickets:
                self.say("No ticket ready.")
                return []
            self.say(f"{len(tickets)} ticket(s) ready.")

        ceiling = limit if limit is not None else self.config.runner.max_concurrent
        jobs = [job for job in (self.prepare(ticket) for ticket in tickets[:ceiling]) if job]
        if not jobs:
            return []

        if len(jobs) == 1:
            results = [self.execute(jobs[0])]
        else:
            with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
                results = list(pool.map(self.execute, jobs))

        for result in results:
            state.record(result)
        state.prune_logs(self.config.runner.log_retention_days)
        return results
