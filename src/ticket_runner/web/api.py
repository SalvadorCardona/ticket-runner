"""What the console can ask for, and what it is allowed to change.

The board stays Notion's. Nothing here is a second database: a ticket read is a
ticket read from Notion, a ticket moved is a `PATCH` on the same page you would
have dragged with your thumb. The console adds what Notion cannot do — the live
steps of a running session, the CLI, and a conversation about the whole
workspace — and duplicates nothing it already does well.

Three reads are cached, because a page left open in a tab must not turn into a
full-time reader of your workspace: the configuration (reloaded when its file
changes), the project index, and the tickets database ID.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import config as config_module
from .. import conversation, credits, session, state, store, systemd, voice
from .. import schedules as schedules_module
from .. import update as update_module
from ..config import Config
from ..runner import Runner
from ..schedules import scheduled_for
from ..ticket import short_id
from . import console, live
from . import settings as settings_module

# The project index is read from one database query, not one page fetch per
# project — and kept, because projects are renamed about as often as they are
# created. Ten minutes is short enough that a new project appears on its own.
PROJECT_TTL = 600

# And the board's own shape on the same cadence, for the same reason: the Notion
# client caches a database for its lifetime, which for the console is days. A
# column added in Notion — the validated one, most of all — has to appear
# without anyone restarting anything.
SCHEMA_TTL = 600

# The columns, in the order they are meant to be read. Anything the board
# carries that is none of them lands in "other" rather than being hidden.
COLUMNS = ("ready", "running", "review", "validated", "blocked", "failed", "done")


class Api:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._stamp = _mtime(config.path)
        self._runner: Runner | None = None
        self._projects: dict[str, dict] = {}
        self._projects_at = 0.0
        self._schema_at = 0.0
        self.hub = live.Hub()
        self.commands = console.Commands(self.hub.publish, _subcommands())
        self.chat = console.Chat(config, self.hub.publish, self.brief)
        self.watch = live.Watch(self.hub, self.board, interval=config.web.poll_seconds)

    # -- the pieces underneath ------------------------------------------------

    @property
    def config(self) -> Config:
        """The configuration, reread when the file on disk has changed.

        `ticket-runner config` edits the same file the console is running on,
        and a console that had to be restarted to notice would be a console
        people restart all day.
        """
        stamp = _mtime(self._config.path)
        if stamp != self._stamp:
            try:
                fresh = config_module.load(self._config.path)
            except config_module.ConfigError:
                return self._config  # a half-saved file: keep what works
            self._stamp = stamp
            self._config = fresh
            self._runner = None
            self._projects = {}
            self.chat.config = fresh
        return self._config

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            self._runner = Runner(self.config, quiet=True)
        return self._runner

    def forget(self) -> None:
        """Drop the caches. What a failed Notion call earns, so the next retries."""
        self._runner = None
        self._projects = {}
        self._projects_at = 0.0
        self._schema_at = 0.0

    # -- reading --------------------------------------------------------------

    def board(self) -> dict:
        """Every ticket, grouped the way the board groups them."""
        settings = self.config.notion
        try:
            if time.time() - self._schema_at > SCHEMA_TTL:
                self.runner.client.forget_database(self.runner.database)
                self._schema_at = time.time()
            pages = self.runner.client.query(self.runner.database)
        except store.StoreError:
            self.forget()
            raise
        names = {settings.state(key): key for key in COLUMNS}
        projects = self.projects()
        host = self.config.runner.session_host

        tickets = [self._ticket(page, names, projects, host) for page in pages]

        # Whether this board has a validated column at all. The console offers
        # the gesture only where the runner would honour it: a button that
        # writes a status Notion does not know is a button that fails.
        validated = settings.state("validated")
        try:
            offers = validated not in (
                settings.state("review"),
                settings.state("done"),
            ) and validated in self.runner.client.options(
                self.runner.database, settings.prop("status")
            )
        except store.StoreError:
            offers = False

        order = {key: index for index, key in enumerate(COLUMNS)}
        tickets.sort(key=lambda item: (order.get(item["column"], len(COLUMNS)), item["title"].lower()))
        columns = [
            {"key": key, "name": settings.state(key)}
            for key in COLUMNS
            # A board whose `blocked` and `failed` are one column must not
            # be drawn twice under two headings.
            if settings.state(key) not in [settings.state(other) for other in COLUMNS[: COLUMNS.index(key)]]
        ]
        # A ticket with no status, or with one nobody configured, is a ticket
        # somebody wrote and the runner will never claim. Dropping it from the
        # board because it fits no heading would be hiding exactly the card
        # that needs a look — so it gets a column of its own, and only while
        # something is in it. No name: the board has none for it, and the
        # console says "No status" in whichever language it is in.
        if any(item["column"] == "other" for item in tickets):
            columns.append({"key": "other", "name": ""})
        return {"tickets": tickets, "validate": offers, "columns": columns}

    def _ticket(self, page: store.Page, names: dict[str, str], projects: dict, host: str) -> dict:
        """One page of the tickets database, as a card reads it."""
        settings = self.config.notion
        status = str(store.read(page, settings.prop("status")) or "")
        relation = store.read(page, settings.prop("project")) or []
        project = projects.get(relation[0]) if relation else None
        session_id = _session_id(str(store.read(page, settings.prop("session")) or ""))
        moment = scheduled_for(store.read(page, settings.prop("due")))
        return {
            "id": page.id.replace("-", ""),
            "short": short_id(page.id),
            "title": page.title or "(untitled ticket)",
            "url": page.url,
            "status": status,
            "column": names.get(status, "other"),
            "project": (project or {}).get("name", ""),
            "kind": (project or {}).get("kind", ""),
            "priority": str(store.read(page, settings.prop("priority")) or ""),
            "model": str(store.read(page, settings.prop("model")) or ""),
            "progress": str(store.read(page, settings.prop("progress")) or ""),
            "runner": str(store.read(page, settings.prop("agent")) or ""),
            "pull_request": str(store.read(page, settings.prop("pull_request")) or ""),
            "session": session_id,
            "session_link": session.deep_link(session_id, host=host) if session_id else "",
            "cost": store.read(page, settings.prop("cost")),
            "duration": store.read(page, settings.prop("duration")),
            "scheduled": moment.isoformat(timespec="minutes") if moment else "",
            "created": page.raw.get("created_time", ""),
        }

    def ticket(self, page_id: str) -> dict:
        """One ticket, and what its page says.

        The card on the board is the row; this is the page under it — the
        brief you wrote, the report a run appended, the notes in between —
        flattened the way the runner itself reads it before it starts. It is
        the same page the ticket's discussion hangs off, so a console showing
        both is showing one thing.
        """
        settings = self.config.notion
        names = {settings.state(key): key for key in COLUMNS}
        try:
            page = self.runner.client.page(page_id)
            content = self.runner.client.blocks_text(page_id)
        except store.StoreError:
            self.forget()
            raise
        card = self._ticket(page, names, self.projects(), self.config.runner.session_host)
        return {**card, "content": content}

    def projects(self) -> dict[str, dict]:
        """{page id: {name, kind, …}} — one query, kept for a few minutes.

        Read from the projects database in one go rather than resolved ticket by
        ticket: resolving costs two API calls per project, and the board asks
        this question every time it refreshes.
        """
        if self._projects and time.time() - self._projects_at < PROJECT_TTL:
            return self._projects
        index: dict[str, dict] = {}
        try:
            database = self.runner.workspace.projects
            if database:
                for page in self.runner.client.query(database):
                    repository = _first(page, "Repository", "repository", "github", "repo")
                    path = _first(page, "Path", "path")
                    index[page.id] = {
                        "id": page.id.replace("-", ""),
                        "name": page.title or "(untitled project)",
                        "kind": "code" if (repository or path) else "document",
                        "url": page.url,
                        "repository": repository,
                        "path": path,
                    }
        except store.StoreError:
            # A projects database that cannot be read costs the board its
            # project names, and nothing else. The tickets still show.
            return self._projects
        self._projects = index
        self._projects_at = time.time()
        return index

    def all_projects(self) -> dict:
        """Every project this installation knows of, from wherever it knows it.

        Three sources, and the pane shows the three as one list because that is
        how somebody thinks of their projects: the board's own database; the
        `[projects]` table of the configuration, which is a path this machine
        maps a name onto; and — for either of those — where the repository
        actually turned out to be on this disk.

        A configuration entry for a project the board already has is not a
        second project: it is the same one, with its path resolved. Only a name
        the board has never heard of adds a row, and it is marked as coming from
        the file so that nobody goes looking for its page.
        """
        rows: list[dict] = []
        try:
            known = self.projects()
        except store.StoreError:
            known = {}
        overrides = dict(self.config.projects)
        for project in sorted(known.values(), key=lambda item: item["name"].lower()):
            declared = overrides.pop(project["name"], "")
            rows.append({**project, "configured": declared, "source": "board"})
        for name, path in sorted(overrides.items(), key=lambda pair: pair[0].lower()):
            rows.append(
                {
                    "id": "",
                    "name": name,
                    "kind": "code",
                    "url": "",
                    "repository": "",
                    "path": path,
                    "configured": path,
                    "source": "config",
                }
            )
        counts: dict[str, int] = {}
        try:
            for page in self.runner.client.query(self.runner.database):
                for page_id in store.read(page, self.config.notion.prop("project")) or []:
                    key = str(page_id).replace("-", "")
                    counts[key] = counts.get(key, 0) + 1
        except store.StoreError:
            counts = {}
        for row in rows:
            row["tickets"] = counts.get(row["id"], 0)
        return {
            "projects": rows,
            "workspace_root": str(self.config.runner.workspace_root),
            "storage": self.config.storage.mode,
        }

    def project(self, page_id: str) -> dict:
        """One project, as the list says it, plus what is written on its page.

        The row is `all_projects`' own, so a project opened reads like the
        project listed — and what a card cannot carry is added here: the brief.
        Which is the reason a project is worth opening at all. It is not
        decoration on the page, it is standing instructions: the audience, the
        voice, the conventions, the things never to do. `projects.brief` reads
        the same text into every ticket of that project.
        """
        wanted = page_id.replace("-", "")
        row = next(
            (item for item in self.all_projects()["projects"] if item["id"] == wanted), None
        )
        if row is None:
            raise LookupError(f"no project with id {wanted}")
        return {**row, "content": self.runner.client.blocks_text(page_id)}

    def save_project(self, page_id: str, values: dict) -> dict:
        """Change one project page from the console.

        Four things, which are the whole of what a project is: its name, the
        repository its tickets are worked in, the path this machine finds that
        repository at, and the brief. Never its tickets — those point at the
        page, and are moved on the board.

        The columns are written under the name the page already carries:
        a project database is written by hand, so "Repository" is sometimes
        "github" and sometimes "repo", and a save that invented a second column
        beside the one somebody filled in would be a save that changes nothing
        anybody can see. `projects.py` reads them the same way.
        """
        database = self.runner.workspace.projects
        if not database:
            raise ValueError("this workspace has no projects database")
        page = self.runner.client.page(page_id)
        written: dict[str, Any] = {}
        if "repository" in values:
            column = _column(page, "Repository", "repository", "github", "repo")
            written[column] = str(values["repository"] or "")
        if "path" in values:
            written[_column(page, "Path", "path")] = str(values["path"] or "")
        if str(values.get("name", "")).strip():
            written[self.runner.client.title_property(database)] = str(values["name"]).strip()
        if not written and "content" not in values:
            raise ValueError("nothing to change")
        if written:
            self.runner.client.update(database, page_id, written)
        # Replacing, not appending: the brief is a value. See `save_context`,
        # which is the same gesture on the one page above all projects.
        if "content" in values:
            self.runner.client.replace_markdown(page_id, str(values["content"]))
        # The index is kept for ten minutes, and a rename that took that long to
        # show would be a rename somebody made twice.
        self._projects = {}
        self._projects_at = 0.0
        self.hub.publish("projects", saved=page_id)
        return self.project(page_id)

    # -- the standing context -------------------------------------------------

    def context(self) -> dict:
        """What reaches every ticket before the ticket itself does.

        Read as text rather than as blocks, which is what the runner puts in the
        prompt anyway — so what this pane shows is exactly what an agent is told,
        and editing it here is editing that.
        """
        space = self.runner.workspace
        return {
            "text": space.context,
            "page": space.context_page,
            "where": self.config.notion.page("context"),
            "storage": self.config.storage.mode,
            # No page to write to is not an error, it is a workspace without a
            # context row — the pane says so rather than offering a save button
            # that could only fail.
            "editable": bool(space.context_page),
        }

    def save_context(self, text: str) -> dict:
        """Rewrite the standing context. The one page the console replaces.

        Replacing, not appending: this is a value, not a history — saving it
        twice must leave one text, not two copies of it under each other. Every
        other write in this console appends, and for the opposite reason.
        """
        space = self.runner.workspace
        if not space.context_page:
            raise ValueError(
                f"this workspace has no “{self.config.notion.page('context')}” page to write to"
            )
        self.runner.client.replace_markdown(space.context_page, text)
        # The workspace was resolved with the old text in it.
        self.forget()
        self.hub.publish("context", saved=True)
        return {"ok": True, "text": text.strip()}

    # -- what comes back on its own, as something you can change --------------

    def save_schedule(self, page_id: str, values: dict) -> dict:
        """Change one row of the Schedules database from the console.

        Only the seven columns a schedule is *written* in — the cadence, the
        hour, the day, the tick, and the three a ticket inherits. Never `Next`
        or `Last`: those are what a pass writes back, and a console that let you
        edit them would let you make an occurrence happen twice.
        """
        database = self.runner.workspace.schedules
        if not database:
            raise ValueError("this workspace has no schedules database")
        settings = self.config.notion
        writable = {
            "cadence": settings.prop("cadence"),
            "at": settings.prop("at"),
            "day": settings.prop("day"),
            "active": settings.prop("active"),
            "model": settings.prop("model"),
            "priority": settings.prop("priority"),
        }
        written: dict[str, Any] = {}
        for key, name in writable.items():
            if key not in values:
                continue
            value = values[key]
            written[name] = bool(value) if key == "active" else str(value or "")
        if "project" in values:
            written[settings.prop("project")] = [values["project"]] if values["project"] else []
        if "name" in values and str(values["name"]).strip():
            written[self.runner.client.title_property(database)] = str(values["name"]).strip()
        if not written and "body" not in values:
            raise ValueError("nothing to change")
        if written:
            self.runner.client.update(database, page_id, written)
        # Replacing, not appending: the body is the brief every occurrence is
        # born with, a value like a project's. See `save_project`.
        if "body" in values:
            self.runner.client.replace_markdown(page_id, str(values["body"]))
        self.hub.publish("schedules", saved=page_id)
        return {"id": page_id.replace("-", "")}

    def create_schedule(self, name: str, values: dict) -> dict:
        """A new row in the Schedules database, left unticked.

        Unticked deliberately, whatever the form said: a schedule that starts
        producing tickets the second it is typed is a schedule nobody dares
        write. You look at it, then you turn it on.
        """
        name = str(name).strip()
        if not name:
            raise ValueError("a schedule needs a name")
        database = self.runner.workspace.schedules
        if not database:
            raise ValueError("this workspace has no schedules database")
        page_id = self.runner.client.create_row(
            database, name, {self.config.notion.prop("active"): False}
        )
        self.save_schedule(page_id, {**values, "active": False})
        return {"id": page_id.replace("-", ""), "name": name}

    def schedules(self) -> dict:
        """What comes back on its own, as `ticket-runner schedules` says it.

        Read when the page is opened rather than watched like the board: a
        schedule moves four times a day at the very most, and a console polling
        that database would be asking Notion a question whose answer has not
        changed since breakfast.

        Two facts travel with the rows, because a list of schedules that all
        look fine explains nothing on an installation where none of them fire:
        whether the workspace has the database at all, and whether
        `runner.schedule` is on.
        """
        try:
            rows = self.runner.schedules()
            database = bool(self.runner.workspace.schedules)
        except store.StoreError:
            self.forget()
            raise
        projects = self.projects()
        return {
            "enabled": self.config.runner.schedule,
            "database": database,
            "page": self.config.notion.page("schedules"),
            "schedules": [self._schedule(row, projects) for row in rows],
        }

    def schedule(self, page_id: str) -> dict:
        """One schedule, as the list says it, plus what is written on its page.

        The body is what the list leaves out, and it is the part that matters:
        it is copied under every ticket the schedule makes. Read here, once,
        rather than with every row — a list of twenty schedules would otherwise
        be twenty pages read to draw a table that shows none of them.
        """
        wanted = page_id.replace("-", "")
        row = next(
            (item for item in self.schedules()["schedules"] if item["id"] == wanted), None
        )
        if row is None:
            raise LookupError(f"no schedule with id {wanted}")
        return {**row, "body": self.runner.client.blocks_text(page_id)}

    def _schedule(self, schedule: schedules_module.Schedule, projects: dict) -> dict:
        """One row of the Schedules database, as the pane reads it.

        Left in the order Notion hands them over — that order is somebody's, and
        a console that sorted it would be rearranging their page for them.
        """
        return {
            "id": schedule.page.id.replace("-", ""),
            "name": schedule.name,
            "url": schedule.page.url,
            "cadence": schedule.cadence,
            "at": schedule.at,
            "day": schedule.day,
            "active": schedule.active,
            "next": schedule.next.isoformat(timespec="minutes") if schedule.next else "",
            "last": schedule.last.isoformat(timespec="minutes") if schedule.last else "",
            # The ticket the last occurrence made, addressed the way the board
            # addresses one: the console links to its page, not to Notion's.
            "ticket": schedule.last_ticket.replace("-", ""),
            "project": (projects.get(schedule.project) or {}).get("name", ""),
            "model": schedule.model,
            "priority": schedule.priority,
            "problem": schedule.problem,
        }

    def state(self) -> dict:
        """Everything the header shows: the timer, the lock, the version, the spend."""
        configuration = self.config
        held = state.running()
        entries = state.history(10_000)
        # A timer that is on and a board that does not move is the one state
        # somebody would open a terminal for. `credits` is 0 the rest of the
        # time, which is how the header knows to say nothing.
        # The reserve counts as being out of credit here, and deliberately so:
        # to whoever is looking at the header, "nothing is being started and
        # here is when that changes" is one state, not two.
        waiting = (
            credits.held() or credits.held(what="reserve")
            if configuration.runner.wait_for_credits
            else 0.0
        )
        return {
            "timer": systemd.read().label,
            "running": bool(held),
            "lock": held,
            # The sessions in flight, read from their logs: what a page that has
            # just been reloaded counts before the stream has said a word.
            "sessions": live.active(held=lambda: held),
            "credits": waiting,
            "credits_at": credits.when(waiting) if waiting else "",
            "workspace_root": str(configuration.runner.workspace_root),
            # Which board this console is looking at. The panes read it to know
            # whether a Notion link is worth drawing, and whether the sync has
            # anything to say — in `markdown` mode neither does.
            "storage": configuration.storage.mode,
            "board_path": str(configuration.storage.path)
            if configuration.storage.markdown
            else "",
            "interval_seconds": configuration.runner.interval_seconds,
            "model": configuration.runner.model or "default",
            "permission_mode": configuration.runner.permission_mode,
            "claude": bool(session.available()),
            "version": _version(),
            "update": _update_available(),
            "spend": round(sum(float(entry.get("cost_usd") or 0) for entry in entries), 2),
            "handled": len(entries),
            "chat": self.chat.state(),
            "commands": sorted(self.commands.allowed),
            "busy": self.commands.busy,
        }

    def history(self, limit: int = 30) -> dict:
        return {"entries": list(reversed(state.history(limit)))}

    def logs(self) -> dict:
        paths = sorted(state.logs_dir().glob("*.jsonl"), reverse=True)[:40]
        return {
            "logs": [
                {
                    "name": path.name,
                    "ticket": path.name.removesuffix(".jsonl").rsplit("-", 1)[-1],
                    "at": path.stat().st_mtime,
                    "size": path.stat().st_size,
                }
                for path in paths
                if path.exists()
            ]
        }

    def log(self, name: str) -> dict:
        """One session, as the steps it was made of. Never as a path from outside."""
        target = state.logs_dir() / Path(name).name
        if not target.exists() or target.suffix != ".jsonl":
            raise LookupError(f"no such log: {name}")
        steps = []
        with target.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                for step in live.steps(line):
                    steps.append({"label": step.label, "detail": step.detail})
        return {"name": target.name, "steps": steps[-1000:]}

    def talk(self, page_id: str) -> dict:
        """What has been said on one ticket, oldest first.

        This is the ticket's terminal, and it is not a new place to talk: it is
        the discussion Notion already holds, read as a conversation. An answer
        relayed from a phone — or from this console — wears the runner's token
        and is nonetheless yours, so it is shown under your name and without the
        line that says which device it came through.
        """
        me = self.runner.myself()
        comments = self.runner.client.comments(page_id)
        return {
            "id": page_id,
            "mention": self.config.notion.mention or conversation.MENTION,
            "messages": [
                {
                    "role": _voice(comment, me),
                    "text": conversation.said(comment.text),
                    "at": comment.created_time,
                }
                for comment in comments
            ],
        }

    # -- writing --------------------------------------------------------------

    def create_ticket(self, title: str, body: str = "", project: str = "", ready: bool = True) -> dict:
        title = title.strip()
        if not title:
            raise ValueError("a ticket needs a title")
        settings = self.config.notion
        values: dict[str, Any] = {}
        # Ready means "start it now"; anything else means the ticket is being
        # written. A draft is left with no status rather than parked in a column
        # nobody named: the runner claims what it was told to claim, and a
        # console that invented a sixth column would be inventing a workflow.
        if ready:
            values[settings.prop("status")] = settings.state("ready")
        if project:
            values[settings.prop("project")] = [project]
        page_id = self.runner.client.create_row(self.runner.database, title, values)
        if body.strip():
            self.runner.client.append_markdown(page_id, body)
        self.watch.nudge()
        return {"id": page_id, "title": title}

    def set_status(self, page_id: str, key: str) -> dict:
        if key not in COLUMNS:
            raise ValueError(f"unknown column “{key}”")
        settings = self.config.notion
        self.runner.client.update(
            self.runner.database, page_id, {settings.prop("status"): settings.state(key)}
        )
        self.watch.nudge()
        return {"id": page_id, "status": settings.state(key)}

    def tell(self, page_id: str, text: str) -> dict:
        """Say something to a ticket, as a comment on it.

        Which is already how a ticket is answered: a run that ends `blocked`
        leaves its question on the page, the reply underneath puts the ticket
        back in the queue, and a reply that names the runner asks it for words
        instead. The console types into that, rather than beside it.

        Two things make it work. It goes **into the thread the runner last spoke
        in**, so it sits under the question and so the next pass finds a thread
        it is part of. And it opens with `conversation.RELAYED`, because the only
        Notion token this console has is the runner's own: without that line the
        next run would read its own voice, and answer itself forever.
        """
        text = text.strip()
        if not text:
            raise ValueError("nothing to say")
        me = self.runner.myself()
        comments = self.runner.client.comments(page_id)
        self.runner.client.comment(
            page_id, f"{conversation.RELAYED}the console.\n{text}", _thread(comments, me)
        )
        self.runner.forget_comments(page_id)
        message = {
            "role": "you",
            "text": text,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.hub.publish("talk", ticket=page_id, **message)
        return message

    # -- the configuration ----------------------------------------------------

    def settings(self) -> dict:
        """Every setting the file holds, as the console draws it — secrets aside."""
        return settings_module.describe(self.config)

    def save_settings(self, payload: dict) -> dict:
        """Write what the console changed, and pick the new file up at once.

        The caches go first because a saved token, workspace or property name is
        a different board: keeping the old client would have the console explain
        that the setting did not work.
        """
        result = settings_module.save(self.config, payload)
        if result["saved"]:
            self.forget()
            self.hub.publish("settings", saved=result["saved"])
            self.watch.nudge()
        return result

    # -- the chat's opening frame ---------------------------------------------

    def brief(self) -> str:
        """What the workspace conversation is told before your first sentence.

        Written once per conversation, not once per message: it costs two Notion
        reads, and repeating it every turn would spend them for a session that
        already remembers. What it carries is the frame — who you are, what the
        projects are, where they live — and one instruction that matters more
        than the rest: the board is changed through `ticket-runner`, not by
        guessing at the Notion API.
        """
        configuration = self.config
        lines = [
            "You are the assistant of a ticket-runner workspace, reached from its web console.",
            "Somebody is in front of you: answer them, ask when something is ambiguous.",
            "",
            "# Your workspace",
            "",
            f"- Repositories live under `{configuration.runner.workspace_root}`.",
            "- `ticket-runner` is on your PATH. `ticket-runner list`, `status`, `history`,",
            "  `projects`, `logs <id>` and `doctor` are how you look at the board;",
            "  `run` handles the ready tickets now.",
            "- The Notion board is the source of truth for tickets. Read it through the",
            "  `ticket-runner` command rather than through the Notion API directly.",
            "- You are not inside a ticket: nothing here has a worktree, a branch or a",
            "  pull request waiting. Work that deserves those is work that deserves a",
            "  ticket — say so, and offer to create one.",
        ]
        try:
            context = self.runner.workspace.context.strip()
        except store.StoreError:
            context = ""
        projects = self.projects()
        if projects:
            lines += ["", "# Projects", ""]
            for project in sorted(projects.values(), key=lambda item: item["name"].lower()):
                lines.append(f"- **{project['name']}** — {project['kind']} work")
        if context:
            lines += ["", "# Who you are working for", "", context[:6000]]
        return "\n".join(lines)


def _first(page: store.Page, *names: str) -> str:
    """The first of those columns the page actually carries, as text.

    A project database is written by hand, so its columns are named by hand:
    "Repository", "repository", or the bare "github" the runner used to ask for.
    `projects.py` reads them the same way, for the same reason.
    """
    for name in names:
        value = store.read(page, name)
        if value not in (None, "", []):
            return str(value)
    return ""


def _column(page: store.Page, *names: str) -> str:
    """The first of those columns the page actually carries, by name.

    What `_first` reads, written back: a value goes to the column somebody
    filled in rather than to a second one beside it. A page carrying none of
    them is written under the first name, which is the one this project would
    have been given had it been created here.
    """
    lookup = {key.lower(): key for key in page.properties}
    for name in names:
        found = lookup.get(name.lower())
        if found is not None:
            return found
    return names[0]


def _voice(comment: store.Comment, me: str) -> str:
    """Who said this: the runner, or you.

    `conversation.ours` is the answer wherever Notion will say who we are. Where
    it will not — an integration without the *Read user information* capability —
    the mark a report opens with is enough to *read* a discussion. It is not
    enough to answer one, which is why `converse` stays silent in that case and
    this does not.
    """
    if me:
        return "runner" if conversation.ours(comment, me) else "you"
    return "runner" if voice.is_report(comment.text) else "you"


def _thread(comments: list[store.Comment], me: str) -> str:
    """The discussion a message typed at a ticket belongs in.

    The last one the runner has spoken in, which is where an answer to its
    question goes. On a page it has never spoken on there is no such thread, and
    on a board whose integration will not say who it is there is no telling —
    both open a discussion of their own, which is the honest thing to do.
    """
    for thread in reversed(conversation.threads(comments)):
        if thread.spoken_by(me) and thread.last.discussion_id:
            return thread.last.discussion_id
    return ""


def _session_id(value: str) -> str:
    """The identifier inside a Session cell, whichever shape the column has.

    A URL column holds `ticket-runner://session/<id>?cwd=…`, a text column holds
    the bare ID. Both are the same session, and the console shows the same link.
    """
    value = value.strip()
    if not value:
        return ""
    if "://" in value:
        return value.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    return value


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _version() -> str:
    """The number this console is running — nothing else.

    Kept bare so the header can print it where a version belongs, next to the
    name, rather than as one more sentence in a row of pills. What is *newer*
    than it is `_update_available`, which is a different question.
    """
    from .. import __version__

    return __version__


def _update_available() -> str:
    """The commit waiting to be installed, or an empty string for "none".

    Read from the stamp a run already writes — never by asking the remote: the
    console redraws its header on every reconnection, and a `git fetch` behind
    that would be a fetch every time a laptop wakes up.
    """
    status = update_module.remembered()
    return status.latest[:8] if status.stale else ""


def _subcommands() -> tuple[str, ...]:
    from ..__main__ import subcommands

    return subcommands()
