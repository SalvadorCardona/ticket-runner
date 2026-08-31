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
"""

from __future__ import annotations

import re
import shutil
import socket
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import agents, channels, conversation, git, notion, notify, progress
from . import prompt as prompt_module, session, state
from . import update as update_module
from . import workspace as workspace_module
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
    agent: agents.Agent = field(default_factory=agents.Agent)
    comments: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def scheduled_for(value: object) -> datetime | None:
    """When a ticket may start, from its Notion date property.

    A bare date means the start of that day, read in this machine's timezone: a
    ticket due "30 August" becomes eligible at midnight, not at noon UTC. A date
    with a time is taken as written, offset included. Anything unparseable is
    treated as no date at all — a ticket is never held back by a value the
    runner failed to read.
    """
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment.astimezone() if moment.tzinfo is None else moment


def short_id(page_id: str) -> str:
    """Eight characters that actually tell two tickets apart.

    Notion page IDs are time-ordered: two tickets created the same day share a
    long *prefix*. Taking the first eight gave both of the first two tickets
    written for this tool the same short id — which would have had them fight
    over one scratch directory. The tail is where the entropy is.
    """
    return page_id.replace("-", "")[-8:]


def is_blank(body: str) -> bool:
    """A ticket body that says nothing, template headings included.

    A database template fills a new page with empty headings. They are not
    blank text, so they would travel into the prompt as noise and — worse —
    stop the "everything is in the title" fallback from firing on a ticket
    whose whole content is its title.
    """
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and set(stripped) != {"-"}:
            return False
    return True


# How much of a ticket's own history is worth carrying into the prompt.
COMMENT_LIMIT = 10
COMMENT_CHARS = 2000


def _line(error: object) -> str:
    """The first line of an error, which is the part meant for a human."""
    return str(error).splitlines()[0] if str(error).strip() else ""


def _message_of(prompt_text: str) -> str:
    """The message a built conversation prompt is about to answer.

    A resumed session has the whole frame already; sending it again would cost
    the ticket's body and the project's brief on every turn and teach it
    nothing. What it has not seen is the last section.
    """
    marker = "# The message to answer\n\n"
    if marker in prompt_text:
        return prompt_text.split(marker, 1)[1].split("\n# What is expected", 1)[0].strip()
    return prompt_text.strip()


def slugify(text: str, limit: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:limit].rstrip("-")) or "ticket"


class Runner:
    def __init__(
        self,
        config: Config,
        *,
        dry_run: bool = False,
        quiet: bool = False,
        announce_idle: bool = True,
    ) -> None:
        self.config = config
        self.dry_run = dry_run or config.runner.dry_run
        self.quiet = quiet
        # At a ten-second cadence, saying "nothing to do" writes six lines a
        # minute into the systemd journal forever, and buries the runs that
        # matter. A terminal wants the reassurance; a log does not.
        self.announce_idle = announce_idle
        self.client = notion.Client(config.notion.token)
        self.resolver = Resolver(config.runner.workspace_root, config.projects)
        self.agent_label = f"ticket-runner@{socket.gethostname()}"
        self._workspace: workspace_module.Workspace | None = None
        # The comments of a page, read once per run. Three things want them —
        # what wakes a ticket, what goes into its prompt, and what is waiting
        # for an answer — and asking Notion three times for the same thread is
        # how a board with forty tickets becomes a rate limit problem.
        self._comments: dict[str, list[notion.Comment]] = {}
        self._ledger: conversation.Ledger | None = None
        self._ledger_lock = threading.Lock()
        self._spellings: tuple[str, ...] | None = None
        self._me: str | None = None
        self._identity_error = ""
        # The tickets this run is about to handle. A comment on one of them is
        # already going into its prompt: answering it as well would be the
        # runner talking over itself.
        self._claimed: set[str] = set()

    @property
    def workspace(self) -> workspace_module.Workspace:
        """The databases and the standing context, resolved once per run.

        Once, because a run can hold several tickets and they all read the same
        thing — and because the context page would otherwise be fetched again
        for every ticket, to be told the same story.
        """
        if self._workspace is None:
            self._workspace = workspace_module.resolve(self.client, self.config.notion)
        return self._workspace

    @property
    def database(self) -> str:
        """The tickets database ID, resolved once for the whole session."""
        return self.workspace.tickets

    # -- output --------------------------------------------------------------

    def say(self, message: str) -> None:
        if not self.quiet:
            print(message, flush=True)

    def _notify(self, title: str, body: str, *, urgent: bool = False) -> None:
        if self.config.notify.desktop and not self.dry_run:
            notify.send(title, body, urgent=urgent)

    def _tell(
        self,
        event: str,
        ticket: Ticket,
        headline: str,
        body: str,
        *,
        urgent: bool = False,
        ask: bool = False,
    ) -> None:
        """One moment of a ticket, said everywhere it is worth saying.

        The screen of the machine the runner sits on, and the messaging app you
        actually have on you. Same sentence in both, one line longer in the
        second because a message you can answer has to say so — and because a
        notification without the ticket's link is a notification you then have
        to go and find.
        """
        self._notify(headline, body, urgent=urgent)
        settings = self.config.notify
        if self.dry_run or not settings.remote or not settings.wants(event):
            return
        invitation = (
            "\n\nAnswer here — yes, no, or a sentence — and it runs again on the next pass."
            if ask
            else ""
        )
        mark = {"blocked": "🙋", "failed": "⚠️", "done": "✅"}.get(event, "•")
        channels.announce(
            settings,
            f"{mark} {headline}\n{body}{invitation}\n{ticket.url}",
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
                        channel.acknowledge(
                            reply,
                            "Nothing here is waiting on an answer — reply under the "
                            "question itself, or name the ticket.",
                        )
                    continue
                try:
                    self.client.comment(reply.ticket, channels.answer(reply))
                except notion.NotionError as error:
                    self.say(f"    ! the answer could not be written to Notion: {error}")
                    channel.acknowledge(reply, f"Notion refused that answer: {error}")
                    continue
                answered += 1
                label = reply.title or reply.ticket
                self.say(f"  ↩ {label} — answered from {channel.name}, back in the queue")
                channel.acknowledge(reply, f"✓ noted on “{label}” — it runs again in a moment.")
        return answered

    # -- reading -------------------------------------------------------------

    def queue(self) -> tuple[list[Ticket], list[tuple[Ticket, datetime]]]:
        """The tickets to run now, and those waiting for their date.

        Two ways in: the ready column, and a ticket the runner already handled
        that has been commented on since (see `woken`). Both are ranked and
        held back by their date the same way — once a ticket is to be run,
        what put it there changes nothing.

        A ticket carrying a date is **scheduled**, not merely deadlined: it is
        left alone until that moment comes. Which is the only reading that means
        anything here — a ticket without a date starts within seconds of being
        made ready, so a date can only be there to say "not yet".

        Among the tickets that may run, order settles who goes first when more
        are ready than `max_concurrent` allows: priority, then the one whose
        date passed longest ago, then age. Age last, so that nothing is starved
        by a steady trickle of newer work.
        """
        tickets = [Ticket(page) for page in self.client.query(self.database, self._ready_filter())]
        tickets += self.woken()
        priorities = {name: index for index, name in enumerate(PRIORITIES)}
        default = priorities.get("Normal", len(PRIORITIES))
        now = datetime.now().astimezone()

        eligible: list[Ticket] = []
        waiting: list[tuple[Ticket, datetime]] = []
        moments: dict[str, float] = {}
        for ticket in tickets:
            moment = scheduled_for(notion.read(ticket.page, self.config.notion.prop("due")))
            if moment and moment > now:
                waiting.append((ticket, moment))
                continue
            moments[ticket.id] = moment.timestamp() if moment else float("inf")
            eligible.append(ticket)

        def rank(ticket: Ticket) -> tuple[int, float, str]:
            value = notion.read(ticket.page, self.config.notion.prop("priority"))
            return (
                priorities.get(str(value), default),
                moments[ticket.id],
                ticket.page.raw.get("created_time", ""),
            )

        return sorted(eligible, key=rank), sorted(waiting, key=lambda pair: pair[1])

    def ready(self) -> list[Ticket]:
        return self.queue()[0]

    def _ready_filter(self) -> dict:
        status_property = self.config.notion.prop("status")
        kind = self.client.schema(self.database).get(status_property, "status")
        return {"property": status_property, kind: {"equals": self.config.notion.state("ready")}}

    def _woken_filter(self) -> dict:
        """Every status but the ones that already speak for a ticket.

        Ready is on its way, running is in flight, in review is waiting on a
        merge, validated is about to be carried out, and done is done: a comment
        on a ticket that came back with its pull request is a conversation about
        the work, not a request to do it again. What is left is where a run
        leaves a ticket it could not finish — which is precisely where an answer
        is expected.
        """
        status_property = self.config.notion.prop("status")
        kind = self.client.schema(self.database).get(status_property, "status")
        settled = {
            self.config.notion.state(key)
            for key in ("done", "review", "validated", "ready", "running")
        }
        return {
            "and": [
                {"property": status_property, kind: {"does_not_equal": value}}
                for value in sorted(settled)
            ]
        }

    def woken(self) -> list[Ticket]:
        """Tickets this runner has already reported on, and answered since.

        A comment is how a ticket is answered: a run that ends `blocked` leaves
        its question on the page, and the reply lands underneath. That reply is
        now the whole gesture — no need to also move the ticket back to the
        ready column. It rejoins the queue and is claimed like any other, so it
        goes to "in progress" for as long as the new run lasts.

        Narrow on purpose, because not every comment is an instruction. A
        ticket wakes only if this runner reported on it and someone else has
        had the last word since: a ticket it never touched belongs to a
        conversation of yours, and one handled by another host is that host's
        to pick up. The report the next run posts is also what closes the
        ticket again — without it, the same comment would wake it forever.
        """
        woken: list[Ticket] = []
        for page in self.client.query(self.database, self._woken_filter()):
            ticket = Ticket(page)
            if not self._answered(ticket):
                continue
            self.say(f"  ↻ {ticket.title} — answered in a comment, picked up again")
            woken.append(ticket)
        return woken

    def _answered(self, ticket: Ticket) -> bool:
        """Did someone have the last word on a ticket this runner reported on?

        Two kinds of comment are not that last word. What the runner itself said
        in the thread since — an answer it gave is not an instruction it was
        given. And a comment that *names* it: naming it is how you ask it to
        speak rather than to work, and `converse` is what picks that up.
        Everything else under a report is still an answer to a question a run
        asked, and still puts the ticket back in the queue — an answer relayed
        from Telegram or Slack included, which wears the runner's token and is
        nonetheless yours.
        """
        try:
            comments = self.comments(ticket.page.id)
        except notion.NotionError:
            # Comments the integration cannot read already cost a ticket its
            # discussion; they are not going to become a reason to run it again.
            # `discussion` is where that is said out loud, once per ticket.
            return False
        reports = [
            index
            for index, comment in enumerate(comments)
            if comment.text.startswith(self.agent_label)
        ]
        if not reports:
            return False
        me = self.myself()
        # What the runner has said in the comments since its report is not an
        # answer to it — that is the whole point of being able to talk here.
        since = [
            comment
            for comment in comments[reports[-1] + 1 :]
            if not conversation.ours(comment, me)
        ]
        if not since:
            return False
        return not conversation.addressed(since[-1].text, self.spellings())

    def myself(self) -> str:
        """The integration's own user ID, or "" if Notion would not say.

        Asked once per run, and never a reason to fail one: without it the
        runner falls back on recognising its own signature, which is enough to
        tell a report from an answer and not enough to answer comments — see
        `converse`.
        """
        if self._me is None:
            try:
                self._me = self.client.me()
            except notion.NotionError as error:
                self._me = ""
                self._identity_error = _line(error)
        return self._me

    def spellings(self) -> tuple[str, ...]:
        """Every way of naming the runner in a comment, resolved once per run.

        The integration's own name comes from Notion and a run must not fail for
        want of it: without it, the configured word and the built-in aliases are
        still every name anybody types.
        """
        if self._spellings is None:
            try:
                integration = self.client.my_name()
            except notion.NotionError:
                integration = ""
            self._spellings = conversation.names(self.config.notion.mention, integration)
        return self._spellings

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

    def close_merged(self) -> int:
        """Close the tickets whose pull request has been merged.

        A pull request is not the end of a ticket: it is a question asked of
        you. The ticket waits in "in review" until you answer it by merging —
        and merging is the answer, so nobody should have to move the ticket by
        hand afterwards.

        Asked at the start of every run rather than by a watcher of its own: the
        runner already wakes up on a timer, and a second one would only be a
        second thing to install, to enable and to forget. `interval_seconds` is
        the cadence of this too.

        A board whose `review` and `done` are the same status has nowhere for a
        ticket to wait, so there is nothing to look at.
        """
        review = self.config.notion.state("review")
        if review == self.config.notion.state("done"):
            return 0
        status_property = self.config.notion.prop("status")
        kind = self.client.schema(self.database).get(status_property, "status")
        pages = self.client.query(
            self.database, {"property": status_property, kind: {"equals": review}}
        )
        closed = 0
        for page in pages:
            url = str(notion.read(page, self.config.notion.prop("pull_request")) or "")
            if not url.startswith("http") or git.pull_request_state(url) != "MERGED":
                continue
            ticket = Ticket(page)
            self.say(f"  ✓ {ticket.title} — pull request merged, moved to done")
            self._set(ticket, **{status_property: self.config.notion.state("done")})
            self._comment(
                ticket,
                f"{self.agent_label} — done.\nIts pull request has been merged: {url}",
            )
            closed += 1
        return closed

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
        """
        settings = self.config.notion
        validated = settings.state("validated")
        if validated in (settings.state("review"), settings.state("done")):
            return []
        status_property = settings.prop("status")
        if validated not in self.client.options(self.database, status_property):
            return []
        kind = self.client.schema(self.database).get(status_property, "status")
        pages = self.client.query(
            self.database, {"property": status_property, kind: {"equals": validated}}
        )
        results = []
        for page in pages:
            ticket = Ticket(page)
            url = str(notion.read(page, settings.prop("pull_request")) or "")
            done = self._merge(ticket, url) if url.startswith("http") else self._publish(ticket)
            if done:
                results.append(done)
        return results

    def _merge(self, ticket: Ticket, url: str) -> dict | None:
        """A validated pull request: merge it, and take the ticket to done."""
        state_of = git.pull_request_state(url)
        if not state_of:
            # The same rule as `close_merged`: a ticket is never moved on an
            # answer GitHub did not give. The next run asks again.
            self.say(f"  · {ticket.title} — GitHub did not answer about {url}, left validated")
            return None
        if state_of == "CLOSED":
            return self._fail(
                ticket,
                "validated, but its pull request was closed without being merged",
                f"{url}\n\nReopen it, or take the ticket back to the ready column.",
                blocked=True,
                question=f"Its pull request was closed rather than merged: {url}",
            )
        method = self.config.runner.merge_method
        note = "It had already been merged."
        if state_of != "MERGED":
            try:
                said = git.merge_pull_request(url, method)
            except git.GitError as error:
                return self._fail(
                    ticket,
                    "the pull request could not be merged",
                    f"{url}\n\n{error}",
                    blocked=True,
                    question=f"GitHub refused the merge: {_line(error)}",
                )
            note = f"Merged by the runner ({method}).\n{said}"
        self.say(f"  ✓ {ticket.title} — pull request merged, moved to done")
        self._set(
            ticket,
            **{self.config.notion.prop("status"): self.config.notion.state("done")},
        )
        self._comment(
            ticket,
            f"{self.agent_label} — done.\nYou validated this ticket, so its "
            f"pull request went in: {url}\n{note}",
        )
        return {"ticket": ticket.title, "id": ticket.id, "status": "done", "merged": url}

    def _publish(self, ticket: Ticket) -> dict | None:
        """A validated ticket with no pull request: publish what it holds.

        The Instagram post drafted last week, the email written into the page,
        the announcement waiting on somebody to press send: work whose last step
        is not a commit. A session is given the page as it stands — the ask, and
        the answer a previous run wrote under it — and told to put it where the
        ticket says, changing nothing on the way.

        Claimed like any other work, by moving the ticket to "in progress":
        publishing twice is the one mistake this must not make, and two runners
        looking at the same board would otherwise both take it.
        """
        short = short_id(ticket.id)
        project = self._project_of(ticket)
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
        job.workdir.mkdir(parents=True, exist_ok=True)
        try:
            outcome = self._run_session(job, prompt_module.template(
                self.config.runner.delivery_prompt_file, prompt_module.DELIVERY
            ))
        except (OSError, FileNotFoundError) as error:
            return self._fail(ticket, "Claude session could not be started", str(error))
        trace = self._trace(job, outcome)

        if not outcome.ok:
            # Kept, always: a publication that half happened is exactly the log
            # somebody is going to want to read before trying again.
            return self._fail(
                ticket,
                "the ticket was validated but could not be published",
                f"{outcome.summary or outcome.error}\n\n{trace}\n"
                f"Working directory kept: `{job.workdir}`",
                blocked=outcome.blocked,
                question=outcome.summary,
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
            f"{self.agent_label} — done.\nValidated, so it was published: "
            f"{outcome.summary}\n\n{trace}\n"
            f"{outcome.turns} turns · {outcome.seconds / 60:.1f} min{cost}",
        )
        self.say(f"    ✓ {ticket.title} — published")
        self._tell("done", ticket, f"Published · {ticket.title}", outcome.summary)
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
            return session.deep_link(
                session_id,
                home or self.config.runner.workspace_root,
                self.config.runner.session_host,
            )
        return session_id

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
        except notion.NotionError as error:
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

    def comments(self, page_id: str) -> list[notion.Comment]:
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
        except notion.NotionError as error:
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
            if conversation.ours(comment, me) and not text.startswith(self.agent_label):
                # Something the runner said in a thread rather than reported.
                # Attributing it to the ticket's author would have the next run
                # read its own words back as an instruction.
                text = " ".join(text.split())
                who = "answered in the comments, by us"
            elif text.startswith(self.agent_label):
                # Our own report. Its first two lines hold the verdict and the
                # reason; the rest is branch names, session IDs and log paths,
                # which mean nothing to the session about to read them.
                text = text[len(self.agent_label):].lstrip(" —-")
                text = " ".join("\n".join(text.splitlines()[:2]).split())
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

    def _fail(
        self,
        ticket: Ticket,
        reason: str,
        detail: str = "",
        *,
        blocked: bool = False,
        question: str = "",
    ) -> dict:
        outcome = "blocked" if blocked else "failed"
        self.say(f"    ✗ {ticket.title} — {reason}")
        # A blocked ticket is a question, and a question is the one thing worth
        # waking somebody for — so it travels with what the agent actually
        # asked, not with the runner's own summary of the situation.
        self._tell(
            outcome,
            ticket,
            f"{'Blocked' if blocked else 'Failed'} · {ticket.title}",
            (question.strip() if blocked and question.strip() else reason),
            urgent=not blocked,
            ask=blocked,
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
            # No project at all is not an error: it is the plainest possible
            # document ticket. "Draft me an email", "summarise this" — there is
            # nothing to commit and nowhere to commit it, so the answer goes
            # back into the page, exactly as for a project without a repository.
            project = Project(name="", path=None)
        else:
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
        if is_blank(body):
            body = ""
            if not ticket.page.title.strip():
                self._fail(
                    ticket,
                    "nothing to work from: the ticket has neither a title nor a description",
                    "Give it a title, or fill in the template headings, then move it back "
                    "to the ready column.",
                    blocked=True,
                )
                return None

        # Both are optional and neither can fail a ticket: a database with no
        # Agent column reads as no agent, and unreadable comments as none.
        role = notion.read(ticket.page, self.config.notion.prop("role")) or []
        agent = (
            agents.resolve(self.client, role[0], self.config.notion.prop("model"))
            if role
            else agents.Agent()
        )

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
            agent=agent,
            comments=self.discussion(ticket),
        )
        where = f"{project.path} · {branch}" if project.is_code else "document → Notion"
        said = f" · {len(job.comments)} comment(s)" if job.comments else ""
        role = f" · as {agent.name}" if agent else ""
        self.say(f"  → {ticket.title}\n    {project.name or 'no project'} · {where}{role}{said}")
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
            brief=job.project.brief,
            context=self.workspace.context,
            agent_name=job.agent.name,
            agent_brief=job.agent.brief,
            comments=job.comments,
        )
        log = job.log or state.log_file(short_id(job.ticket.id))
        # The ticket first, then its agent, then the runner: the narrower the
        # choice, the more deliberate it was.
        chosen = job.model or job.agent.model or self.config.runner.model
        self.say(f"    Claude session {job.session_id}{' · ' + chosen if chosen else ''} → {log}")
        live = self._live(job)
        try:
            outcome = session.run(
                text,
                cwd=job.workdir,
                log=log,
                model=chosen,
                permission_mode=self.config.runner.permission_mode,
                timeout_minutes=self.config.runner.timeout_minutes,
                session_id=job.session_id,
                on_event=live.event if live else None,
            )
        except BaseException:
            # A session that dies still leaves a ticket saying “⏳ Live” and a
            # column stuck on whatever it was doing. Closing here is what makes
            # the page tell the truth on the way out too.
            if live:
                live.close("interrupted")
            raise
        if live:
            # The toggle's last word: what the session achieved, or which of the
            # two ways of not achieving it this was.
            live.close(
                outcome.summary
                if outcome.ok
                else ("blocked — it asked a question" if outcome.blocked else "stopped")
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
            say=self.say,
        )

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
                ticket,
                reason,
                f"{detail}\n\n{trace}{kept}",
                blocked=outcome.blocked or not content,
                question=detail,
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
        self._tell(
            "done",
            ticket,
            f"Ready to review · {ticket.title}",
            "Written into the Notion ticket.",
        )
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
            return self._fail(
                ticket,
                reason,
                f"{detail}\n\n{trace}{kept}",
                blocked=outcome.blocked,
                question=detail if outcome.blocked else "",
            )

        commits = git.commits_ahead(job.workdir, job.base)
        if commits == 0:
            if not git.is_dirty(job.workdir):
                git.remove_worktree(project.path, job.workdir)
            return self._fail(
                ticket,
                "the session declared itself done without a single commit",
                f"{outcome.summary}\n\n{trace}",
                blocked=True,
                question=outcome.summary,
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
        self._tell(
            "done",
            ticket,
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
            self.say(f"    ! comment not answered: {_line(error)}")
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
        )

        discussion = thread.last.discussion_id
        resumed = self.ledger.session_of(discussion) if discussion else ""
        outcome = self._reply_session(
            text, workdir, short, agent, ticket, session_id=resumed or session.new_id(),
            resume=bool(resumed),
        )
        if not outcome.ok and resumed:
            # A session Claude Code no longer has — pruned, or filed on another
            # machine. The thread's history is in Notion, so a fresh one starts
            # from everything except the tone of the last exchange.
            self.say("    ↻ that conversation could not be resumed — starting a new one")
            with self._ledger_lock:
                self.ledger.forget_session(discussion)
            outcome = self._reply_session(
                text, workdir, short, agent, ticket, session_id=session.new_id(), resume=False
            )

        answer = conversation.trim(outcome.answer if outcome.ok else "")
        if not answer:
            answer = (
                "I could not answer this one: "
                f"{_line(outcome.error) or 'the session ended without saying anything'}.\n"
                f"Log: `{outcome.log}`"
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
            prompt_module.FOLLOW_UP.format(message=_message_of(text)) if resume else text
        )
        chosen = (
            str(notion.read(ticket.page, self.config.notion.prop("model")) or "")
            or agent.model
            or self.config.runner.model
        )
        return session.run(
            prompt_text,
            cwd=workdir,
            log=state.log_file(f"{short}-talk"),
            model=chosen,
            permission_mode=self.config.runner.reply_permission_mode,
            timeout_minutes=self.config.runner.reply_timeout_minutes,
            session_id=session_id,
            resume=resume,
        )

    def _project_of(self, ticket: Ticket) -> Project:
        """The ticket's project, or none at all. Never a failure: a conversation
        about a ticket whose repository has moved is still a conversation."""
        relation = notion.read(ticket.page, self.config.notion.prop("project")) or []
        if not relation:
            return Project(name="", path=None)
        try:
            return self.resolver.resolve(self.client, relation[0])
        except (LookupError, notion.NotionError):
            return Project(name="", path=None)

    def _body(self, ticket: Ticket) -> str:
        try:
            return self.client.blocks_text(ticket.page.id)
        except notion.NotionError:
            return ""

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
                delivered = self.deliver()
                # Merged, published, or refused: as much a run of this ticket as
                # a session is, and `ticket-runner history` should say so.
                for done in delivered:
                    state.record(done)
            tickets, waiting = self.queue()
            # Every ticket the queue wants, and not only the ones that will fit
            # in this pass: a ticket queued for the next run — or held until
            # Thursday — is still work, and the comment that queued it is going
            # into its prompt. Talking to it as well would be the runner
            # answering a question it is also about to act on.
            self._claimed = {ticket.id for ticket in tickets} | {
                ticket.id for ticket, _ in waiting
            }
            if not tickets:
                replies = self.converse()
                if self.announce_idle and not replies and not delivered:
                    later = f", {len(waiting)} waiting for their date" if waiting else ""
                    self.say(f"No ticket ready{later}.")
                return delivered + replies
            later = f", {len(waiting)} scheduled for later" if waiting else ""
            self.say(f"{len(tickets)} ticket(s) ready{later}.")

        # Said here rather than on resolution: at a ten-second cadence, a run
        # with nothing to do would repeat them forever into the journal.
        for warning in self.workspace.warnings:
            self.say(f"  ! {warning}")

        ceiling = limit if limit is not None else self.config.runner.max_concurrent
        replies = [] if reference else self.converse()

        jobs = [job for job in (self.prepare(ticket) for ticket in tickets[:ceiling]) if job]
        if not jobs:
            return delivered + replies

        if len(jobs) == 1:
            results = [self.execute(jobs[0])]
        else:
            with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
                results = list(pool.map(self.execute, jobs))

        for result in results:
            state.record(result)
        state.prune_logs(self.config.runner.log_retention_days)
        return delivered + replies + results
