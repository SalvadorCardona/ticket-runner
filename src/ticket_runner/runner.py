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
import socket
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import git, notion, prompt as prompt_module, session, state
from .config import Config, state_dir
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
    worktree: Path
    body: str = ""
    notes: list[str] = field(default_factory=list)


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

    # -- reading -------------------------------------------------------------

    def ready(self) -> list[Ticket]:
        database = self.database
        status_property = self.config.notion.prop("status")
        kind = self.client.schema(database).get(status_property, "status")
        wanted = self.config.notion.state("ready")
        filter_ = {"property": status_property, kind: {"equals": wanted}}
        return [Ticket(page) for page in self.client.query(database, filter_)]

    def fetch_one(self, reference: str) -> Ticket:
        page_id = reference.strip()
        if "://" in page_id:
            page_id = page_id.split("?")[0].rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[-1]
        return Ticket(self.client.page(page_id.replace("-", "")))

    # -- writing -------------------------------------------------------------

    def _set(self, ticket: Ticket, **values: object) -> None:
        if self.dry_run:
            return
        self.client.update(self.database, ticket.page.id, values)

    def _comment(self, ticket: Ticket, text: str) -> None:
        if self.dry_run:
            return
        try:
            self.client.comment(ticket.page.id, text)
        except notion.NotionError as error:
            self.say(f"    ! Notion refused the comment: {error}")

    def _fail(self, ticket: Ticket, reason: str, detail: str = "") -> dict:
        self.say(f"    ✗ {ticket.title} — {reason}")
        self._set(ticket, **{self.config.notion.prop("status"): self.config.notion.state("failed")})
        self._comment(
            ticket,
            f"{self.agent_label} — failed.\n{reason}" + (f"\n\n{detail}" if detail else ""),
        )
        return {"ticket": ticket.title, "id": ticket.id, "status": "failed", "reason": reason}

    # -- preparation ---------------------------------------------------------

    def prepare(self, ticket: Ticket) -> Job | None:
        """Locate the project and claim the ticket. None if it is unusable."""
        relation = notion.read(ticket.page, self.config.notion.prop("project")) or []
        if not relation:
            self._fail(ticket, "no project linked: the runner has no repository to work in")
            return None
        try:
            project = self.resolver.resolve(self.client, relation[0])
        except (LookupError, notion.NotionError) as error:
            self._fail(ticket, "project not found on disk", str(error))
            return None

        base = self.config.runner.base_branch or git.default_branch(project.path)
        branch = f"{self.config.runner.branch_prefix}{slugify(ticket.title)}-{ticket.id[:8]}"
        worktree = state_dir() / "worktrees" / f"{slugify(project.name, 24)}-{ticket.id[:8]}"

        try:
            body = self.client.blocks_text(ticket.page.id)
        except notion.NotionError as error:
            self._fail(ticket, "ticket content unreadable", str(error))
            return None

        job = Job(ticket, project, branch, base, worktree, body)
        self.say(f"  → {ticket.title}\n    {project.name} · {project.path} · {branch}")
        if not self.dry_run:
            self._set(
                ticket,
                **{
                    self.config.notion.prop("status"): self.config.notion.state("running"),
                    self.config.notion.prop("agent"): self.agent_label,
                },
            )
        return job

    # -- execution -----------------------------------------------------------

    def execute(self, job: Job) -> dict:
        ticket, project = job.ticket, job.project
        if self.dry_run:
            self.say(f"    (dry run) {job.branch} from {job.base}")
            return {"ticket": ticket.title, "id": ticket.id, "status": "dry-run"}

        if self.config.runner.fetch:
            git.fetch(project.path)
        try:
            git.add_worktree(project.path, job.worktree, job.branch, job.base)
        except git.GitError as error:
            return self._fail(ticket, "worktree could not be created", str(error))

        text = prompt_module.build(
            prompt_module.template(self.config.runner.prompt_file),
            project=project.name,
            title=ticket.title,
            body=job.body,
            repo=str(project.path),
            branch=job.branch,
            base=job.base,
            url=ticket.url,
        )
        log = state.log_file(ticket.id)
        self.say(f"    Claude session → {log}")

        try:
            outcome = session.run(
                text,
                cwd=job.worktree,
                log=log,
                model=self.config.runner.model,
                permission_mode=self.config.runner.permission_mode,
                timeout_minutes=self.config.runner.timeout_minutes,
            )
        except (OSError, FileNotFoundError) as error:
            git.remove_worktree(project.path, job.worktree)
            return self._fail(ticket, "Claude session could not be started", str(error))

        trace = (
            f"Session: `{outcome.session_id}` — resume with `{outcome.resume_command}`\n"
            f"Log: `{log}`"
        )

        if not outcome.ok:
            reason = "the agent stopped without deciding" if outcome.blocked else "the session failed"
            detail = (outcome.summary if outcome.blocked else outcome.error) or ""
            kept = ""
            if self.config.runner.keep_worktree_on_failure:
                kept = f"\nWorktree kept: `{job.worktree}` (branch `{job.branch}`)"
            else:
                git.remove_worktree(project.path, job.worktree)
            return self._fail(ticket, reason, f"{detail}\n\n{trace}{kept}")

        commits = git.commits_ahead(job.worktree, job.base)
        if commits == 0:
            if not git.is_dirty(job.worktree):
                git.remove_worktree(project.path, job.worktree)
            return self._fail(
                ticket,
                "the session declared itself done without a single commit",
                f"{outcome.summary}\n\n{trace}",
            )

        pull_request = ""
        if self.config.runner.push:
            pushed = git.push(job.worktree, job.branch)
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
                    pull_request = git.open_pull_request(job.worktree, ticket.title, body, job.base)
                except git.GitError as error:
                    self.say(f"    ! pull request not opened: {error}")
                    job.notes.append(f"Pull request not opened: {error}")

        git.remove_worktree(project.path, job.worktree)

        values: dict[str, object] = {
            self.config.notion.prop("status"): self.config.notion.state("done"),
            self.config.notion.prop("agent"): self.agent_label,
        }
        if pull_request:
            values[self.config.notion.prop("pull_request")] = pull_request
        values[self.config.notion.prop("session")] = outcome.session_id
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
        return results
