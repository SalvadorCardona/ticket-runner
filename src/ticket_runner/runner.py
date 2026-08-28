"""Un tour : prendre les tickets prêts, les faire, rendre compte dans Notion.

Le tour se déroule en deux temps, et l'ordre compte.

**D'abord, en série :** lire les tickets prêts, situer leur projet, et les
*réserver* en les passant à « en cours ». Réserver avant de travailler est ce
qui empêche le minuteur de relancer un ticket déjà pris — et le faire en série
évite que deux tickets se disputent le même index de dépôts.

**Ensuite, en parallèle :** chaque ticket réservé obtient son worktree, sa
session Claude, sa branche et sa PR. Un ticket qui échoue n'emporte que
lui-même : il retourne en « brouillon » avec la raison en commentaire, pendant
que les autres continuent.
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
        return self.page.title or "(ticket sans titre)"

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
        """L'ID de la base de tickets, résolu une fois pour toute la session."""
        if not self._database:
            self._database = self.client.resolve_database(self.config.notion.tickets_database)
        return self._database

    # -- sortie --------------------------------------------------------------

    def say(self, message: str) -> None:
        if not self.quiet:
            print(message, flush=True)

    # -- lecture -------------------------------------------------------------

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

    # -- écriture ------------------------------------------------------------

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
            self.say(f"    ! commentaire Notion refusé : {error}")

    def _fail(self, ticket: Ticket, reason: str, detail: str = "") -> dict:
        self.say(f"    ✗ {ticket.title} — {reason}")
        self._set(ticket, **{self.config.notion.prop("status"): self.config.notion.state("failed")})
        self._comment(
            ticket,
            f"{self.agent_label} — échec.\n{reason}" + (f"\n\n{detail}" if detail else ""),
        )
        return {"ticket": ticket.title, "id": ticket.id, "status": "failed", "reason": reason}

    # -- préparation ---------------------------------------------------------

    def prepare(self, ticket: Ticket) -> Job | None:
        """Situe le projet et réserve le ticket. None si le ticket est inexploitable."""
        relation = notion.read(ticket.page, self.config.notion.prop("project")) or []
        if not relation:
            self._fail(ticket, "aucun projet lié : le runner ne sait pas dans quel dépôt travailler")
            return None
        try:
            project = self.resolver.resolve(self.client, relation[0])
        except (LookupError, notion.NotionError) as error:
            self._fail(ticket, "projet non situé sur le disque", str(error))
            return None

        base = self.config.runner.base_branch or git.default_branch(project.path)
        branch = f"{self.config.runner.branch_prefix}{slugify(ticket.title)}-{ticket.id[:8]}"
        worktree = state_dir() / "worktrees" / f"{slugify(project.name, 24)}-{ticket.id[:8]}"

        try:
            body = self.client.blocks_text(ticket.page.id)
        except notion.NotionError as error:
            self._fail(ticket, "contenu du ticket illisible", str(error))
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

    # -- exécution -----------------------------------------------------------

    def execute(self, job: Job) -> dict:
        ticket, project = job.ticket, job.project
        if self.dry_run:
            self.say(f"    (simulation) {job.branch} depuis {job.base}")
            return {"ticket": ticket.title, "id": ticket.id, "status": "dry-run"}

        if self.config.runner.fetch:
            git.fetch(project.path)
        try:
            git.add_worktree(project.path, job.worktree, job.branch, job.base)
        except git.GitError as error:
            return self._fail(ticket, "worktree impossible à créer", str(error))

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
        self.say(f"    session Claude → {log}")

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
            return self._fail(ticket, "session Claude impossible à lancer", str(error))

        trace = (
            f"Session : `{outcome.session_id}` — reprendre avec `{outcome.resume_command}`\n"
            f"Journal : `{log}`"
        )

        if not outcome.ok:
            reason = "l'agent s'est arrêté sans trancher" if outcome.blocked else "la session a échoué"
            detail = (outcome.summary if outcome.blocked else outcome.error) or ""
            kept = ""
            if self.config.runner.keep_worktree_on_failure:
                kept = f"\nWorktree conservé : `{job.worktree}` (branche `{job.branch}`)"
            else:
                git.remove_worktree(project.path, job.worktree)
            return self._fail(ticket, reason, f"{detail}\n\n{trace}{kept}")

        commits = git.commits_ahead(job.worktree, job.base)
        if commits == 0:
            if not git.is_dirty(job.worktree):
                git.remove_worktree(project.path, job.worktree)
            return self._fail(
                ticket,
                "la session s'est déclarée terminée sans aucun commit",
                f"{outcome.summary}\n\n{trace}",
            )

        pull_request = ""
        if self.config.runner.push:
            pushed = git.push(job.worktree, job.branch)
            if not pushed.ok:
                return self._fail(
                    ticket,
                    "commits faits mais push refusé",
                    f"{pushed.err or pushed.out}\n\nBranche locale `{job.branch}` conservée.\n{trace}",
                )
            if self.config.runner.open_pull_request:
                body = (
                    f"{outcome.summary}\n\n"
                    f"---\nTicket Notion : {ticket.url}\n"
                    f"Session Claude Code : `{outcome.session_id}`\n"
                    f"Ouverte par ticket-runner ({commits} commit{'s' if commits > 1 else ''})."
                )
                try:
                    pull_request = git.open_pull_request(job.worktree, ticket.title, body, job.base)
                except git.GitError as error:
                    self.say(f"    ! pull request non ouverte : {error}")
                    job.notes.append(f"PR non ouverte : {error}")

        git.remove_worktree(project.path, job.worktree)

        values: dict[str, object] = {
            self.config.notion.prop("status"): self.config.notion.state("done"),
            self.config.notion.prop("agent"): self.agent_label,
        }
        if pull_request:
            values[self.config.notion.prop("pull_request")] = pull_request
        values[self.config.notion.prop("session")] = outcome.session_id
        self._set(ticket, **values)

        cost = f" · {outcome.cost_usd:.3f} $" if outcome.cost_usd else ""
        notes = ("\n" + "\n".join(job.notes)) if job.notes else ""
        self._comment(
            ticket,
            f"{self.agent_label} — terminé.\n{outcome.summary}\n\n"
            f"Branche `{job.branch}` · {commits} commit(s)"
            + (f" · {pull_request}" if pull_request else " · pas de pull request")
            + notes
            + f"\n{trace}\n{outcome.turns} tours · {outcome.seconds / 60:.1f} min{cost}",
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

    # -- tour complet --------------------------------------------------------

    def tick(self, *, limit: int | None = None, reference: str = "") -> list[dict]:
        if reference:
            tickets = [self.fetch_one(reference)]
            self.say(f"Ticket demandé : {tickets[0].title}")
        else:
            tickets = self.ready()
            if not tickets:
                self.say("Aucun ticket prêt.")
                return []
            self.say(f"{len(tickets)} ticket(s) prêt(s).")

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
