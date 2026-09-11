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

import re
import shutil
import socket
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path

from . import agents, channels, conversation, credits, git, naming, notion, notify
from . import openrouter, progress
from . import prompt as prompt_module, schedules as schedules_module, session, state
from . import update as update_module
from . import voice as voice_module
from . import workspace as workspace_module
from .config import PRIORITIES, Config, state_dir
from .projects import Project, Resolver
# The one reading of a Notion date in the project. It lives beside the calendar
# because a date on a ticket and a date on a schedule mean the same thing, and
# two readings of them that drift apart is a bug nobody would ever find.
from .schedules import scheduled_for


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
    resumed: bool = False
    # The folded block this job's session wrote its steps into, once it has one.
    # Kept on the job because what goes in it is decided after the session ends:
    # a run that failed files its trace there rather than in the report.
    live: progress.Live | None = None


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


def _pull_request(said: voice_module.Voice, url: str) -> str:
    """“PR #19”, which is how anybody refers to one out loud.

    The URL says the same thing in seventy characters, and a verdict line has
    about eighty in all — so the number goes on that line and the URL goes on
    its own, where it is a link to click rather than a fact to read.
    """
    found = re.search(r"/pull/(\d+)", str(url or ""))
    return said.say("pull-request", number=found.group(1)) if found else ""


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
        # What the last `deliver` left for later, so a pass can say so.
        self._deferred: list[tuple[Ticket, datetime]] = []

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

    @property
    def voice(self) -> voice_module.Voice:
        """Everything the runner says on a ticket, in the configured language.

        Read off the configuration each time rather than kept, so that a file
        edited in the console — where `runner.language` is one field of a form —
        is heard on the next run without the service being restarted.
        """
        return voice_module.Voice(self.config.runner.language)

    @property
    def environment(self) -> dict[str, str]:
        """What every session this run starts is given, beyond what it inherits.

        The OpenRouter key when there is one, and nothing at all when there is
        not. Read off the configuration each time, for the same reason as
        `voice`: a key typed into the console is a key the next run uses.
        """
        return openrouter.environment(self.config.openrouter)

    # -- output --------------------------------------------------------------

    def say(self, message: str) -> None:
        if not self.quiet:
            print(message, flush=True)

    def _notify(
        self, title: str, body: str, *, urgent: bool = False, link: str = ""
    ) -> None:
        if self.config.notify.desktop and not self.dry_run:
            notify.send(title, body, urgent=urgent, link=link)

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
                except notion.NotionError as error:
                    self.say(f"    ! the answer could not be written to Notion: {error}")
                    channel.acknowledge(reply, self.voice.say("notion-refused", error=error))
                    continue
                answered += 1
                label = reply.title or reply.ticket
                self.say(f"  ↩ {label} — answered from {channel.name}, back in the queue")
                channel.acknowledge(reply, self.voice.say("noted", title=label))
        return answered

    # -- reading -------------------------------------------------------------

    def _moment(self, ticket: Ticket) -> datetime | None:
        """When this ticket may be acted on, or `None` if it carries no date.

        The one reading of the date property. Two columns honour it — ready,
        where it holds the work back, and validated, where it holds back the
        merge or the publication — and they must not drift apart on what a date
        means.
        """
        return scheduled_for(notion.read(ticket.page, self.config.notion.prop("due")))

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
            moment = self._moment(ticket)
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

        Which machine reported is read off the board's Agent column rather than
        off the comment: reports open on a verdict now, not on a host, and the
        column is where the host was always written down anyway.
        """
        agent = str(notion.read(ticket.page, self.config.notion.prop("agent")) or "")
        if agent and agent != self.agent_label:
            return False
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
            if voice_module.is_report(comment.text)
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

        Back to ready, but **not** when it was claimed for a publication. A
        ticket taken from the validated column was work somebody had already
        accepted; re-doing it is not recovery, and re-publishing it is the one
        mistake this must not make — the post may well have gone out just before
        the machine died. So it goes to blocked with the question spelled out,
        and moving it back to validated is a click if it never went out.
        Where it was taken from is remembered locally, which is enough: only
        this host's own claims are ever recovered here.

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
            origin = state.claims().get(ticket.id, "")
            said = self.voice
            stopped = said.say("abandoned", minutes=said.minutes(age.total_seconds()))
            if origin and origin != self.config.notion.state("ready"):
                self.say(
                    f"  ↺ {ticket.title} — publication interrupted, asking rather than redoing"
                )
                interrupted = said.say("publication-interrupted", origin=origin)
                self._set(ticket, **{status_property: self.config.notion.state("blocked")})
                self._comment(
                    ticket,
                    said.report(
                        said.verdict("blocked", interrupted), said.say("answer-here")
                    ),
                )
                self._tell("blocked", ticket, "blocked", said.sentence(interrupted), ask=True)
                state.release(ticket.id)
                recovered += 1
                continue
            self.say(f"  ↺ {ticket.title} — claimed but no run alive, put back")
            self._set(ticket, **{status_property: self.config.notion.state("ready")})
            self._comment(
                ticket,
                said.report(
                    said.verdict("requeued", stopped), said.say("abandoned-requeued")
                ),
            )
            state.release(ticket.id)
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
            said = self.voice
            self.say(f"  ✓ {ticket.title} — pull request merged, moved to done")
            self._set(ticket, **{status_property: self.config.notion.state("done")})
            self._comment(
                ticket, said.report(said.verdict("merged", _pull_request(said, url)), url)
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
        """
        settings = self.config.notion
        results: list[dict] = []
        publishing: list[tuple[Ticket, Project]] = []
        held: list[tuple[Ticket, datetime]] = []
        now = datetime.now().astimezone()
        for page in self.validated():
            ticket = Ticket(page)
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
        return results + self._publish_all(publishing)

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

    def _publish_all(self, publishing: list[tuple[Ticket, Project]]) -> list[dict]:
        """Every validated publication of this pass, up to `max_concurrent` at once.

        A batch, unlike the ticket queue in `_work`, and deliberately so: the
        whole list is handed to `pool.map`, which starts the next publication as
        soon as a worker frees, so no place is ever left idle. What it does not
        do is look at the board again mid-list — and it has no reason to, since
        a validated ticket is work you accepted before the pass began, and the
        one you accept during it is published by the pass after.
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

    def _merge(self, ticket: Ticket, url: str) -> dict | None:
        """A validated pull request: merge it, and take the ticket to done."""
        state_of = git.pull_request_state(url)
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
        if state_of != "MERGED":
            try:
                git.merge_pull_request(url, method)
            except git.GitError as error:
                return self._fail(
                    ticket,
                    said.say("merge-refused"),
                    f"{url}\n\n{error}",
                    blocked=True,
                    question=said.say("merge-refused-question", error=_line(error)),
                )
            how = said.say("merged-with", method=method)
        self.say(f"  ✓ {ticket.title} — pull request merged, moved to done")
        self._set(
            ticket,
            **{self.config.notion.prop("status"): self.config.notion.state("done")},
        )
        self._comment(
            ticket,
            said.report(said.verdict("merged", _pull_request(said, url), how), url),
        )
        return {"ticket": ticket.title, "id": ticket.id, "status": "done", "merged": url}

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

    # -- what comes back on its own -------------------------------------------

    def schedules(self) -> list[schedules_module.Schedule]:
        """Every row of the Schedules database, or none where there is no such
        database. Read rather than acted on: `list` and `doctor` want it too."""
        database = self.workspace.schedules
        if not database:
            return []
        settings = self.config.notion
        return [schedules_module.read(page, settings) for page in self.client.query(database)]

    def recur(self) -> list[dict]:
        """The schedules whose moment has come, turned into tickets.

        A pass of its own, between `deliver` and the queue — before the queue on
        purpose, so a ticket born at 09:00 is claimed by the very pass that made
        it rather than by the next one. What it produces is an ordinary ticket:
        same ready column, same file, same session, same pull request. The
        schedule only presses the button for you.

        Four rules, and they are the whole of it.

        - **Catching up: one occurrence, and the missed ones are dropped.**
          Machine off for three days, timer stopped, laptop shut: waking up
          gives you one ticket for the occurrence that is due, not twelve. The
          next moment is computed *from now*, never by stacking up what was
          lost. This is anacron, not cron — turning a laptop back on must not
          set off an avalanche of sessions.
        - **Overlapping: skipped, and said out loud.** While the ticket of the
          previous occurrence is neither done nor failed, no new one is made.
          The next moment moves on regardless. Without that, one schedule stuck
          on a question fills the board with twenty identical tickets.
        - **Idempotence: the occurrence is taken before it is acted on.** `Next`
          and `Last` are written first, the ticket second. A crash in between
          loses one occurrence; the other order would create two, which costs a
          session and dirties the board. A second runner on another machine
          reads a `Next` that has already moved, and does nothing.
        - **The timezone is this machine's**, the same reading `scheduled_for`
          gives a date on a ticket.
        """
        if not self.config.runner.schedule:
            return []
        born: list[dict] = []
        now = datetime.now().astimezone()
        for schedule in self.schedules():
            if not schedule.active or schedule.problem:
                # A schedule nobody can read holds nobody up: `doctor` names it,
                # and the others go on being born.
                continue
            upcoming = schedules_module.next_occurrence(
                schedule.cadence, schedule.at, schedule.day, after=now
            )
            if schedule.next is None:
                # A new schedule does not fire the second it is written: writing
                # “Weekly / Monday” on a Tuesday must not produce a ticket now.
                if upcoming:
                    self._mark(schedule, {self.config.notion.prop("next_run"): upcoming})
                    self.say(
                        f"  ⧗ {schedule.name} — first occurrence "
                        f"{upcoming.strftime('%Y-%m-%d %H:%M')}"
                    )
                continue
            if schedule.next > now or upcoming is None:
                # `problem` already caught everything that makes a cadence
                # uncomputable; taking an occurrence without knowing when the
                # next one falls would have this fire on every single pass.
                continue
            if self.dry_run:
                self.say(f"  (dry run) {schedule.name} — due: would create a ticket")
                born.append({"ticket": schedule.name, "status": "dry-run"})
                continue
            # Taken before it is done: see the third rule above.
            self._mark(
                schedule,
                {
                    self.config.notion.prop("next_run"): upcoming,
                    self.config.notion.prop("last_run"): now,
                },
            )
            if self._busy(schedule):
                self.say(
                    f"  · {schedule.name} — its last ticket is still open, "
                    "no second one made"
                )
                continue
            entry = self._born(schedule)
            if entry:
                born.append(entry)
        return born

    def _busy(self, schedule: schedules_module.Schedule) -> bool:
        """Is the previous occurrence still going?

        Anywhere but done or failed — so still ready, in progress, in review,
        validated, or blocked on a question nobody has answered — means yes. A
        ticket the integration can no longer read is not one of those: a page
        somebody deleted would otherwise wedge its schedule for good.
        """
        if not schedule.last_ticket:
            return False
        settings = self.config.notion
        try:
            page = self.client.page(schedule.last_ticket)
        except notion.NotionError:
            return False
        status = str(notion.read(page, settings.prop("status")) or "")
        return status not in (settings.state("done"), settings.state("failed"))

    def _born(self, schedule: schedules_module.Schedule) -> dict | None:
        """One schedule, one ticket, in the ready column.

        The body is a line saying where it came from, then the schedule page's
        own body copied under it — the same road a report travels. Copied rather
        than linked, so the ticket reads on its own and its history shows what
        was actually asked for that day.

        A schedule that fails takes only itself down: the pass says so and moves
        on to the next one.
        """
        settings = self.config.notion
        moment = datetime.now().astimezone()
        stamp = moment.strftime("%Y-%m-%d %H:%M" if schedule.cadence == "Hourly" else "%Y-%m-%d")
        title = f"{schedule.name} — {stamp}"
        values: dict[str, object] = {settings.prop("status"): settings.state("ready")}
        for key, value in (
            ("project", schedule.project),
            ("model", schedule.model),
            ("priority", schedule.priority),
        ):
            if value:
                values[settings.prop(key)] = value
        # The brief is read before anything is written: the page it comes from is
        # the likeliest thing to be unreadable, and a ticket that is all title
        # would run on nothing at all.
        try:
            brief = self.client.blocks_text(schedule.page.id)
            page_id = self.client.create_row(self.database, title, values)
        except notion.NotionError as error:
            self.say(f"  ! {schedule.name} — the ticket could not be created: {_line(error)}")
            return None
        # Linked first, so that a body Notion refuses still leaves the schedule
        # knowing what it produced — otherwise the next occurrence makes a twin.
        self._mark(schedule, {settings.prop("last_ticket"): page_id})
        try:
            self.client.append_markdown(
                page_id,
                f"*Born of the “{schedule.name}” schedule, {stamp}* — {schedule.page.url}\n"
                + (f"\n{brief}\n" if brief.strip() else ""),
            )
        except notion.NotionError as error:
            self.say(f"  ! {title} — created, but its body was refused: {_line(error)}")
        self.say(f"  ✳ {title} — created by a schedule, ready")
        return {
            "ticket": title,
            "id": page_id.replace("-", ""),
            "status": "scheduled",
            "from": schedule.name,
        }

    def _mark(self, schedule: schedules_module.Schedule, values: dict[str, object]) -> None:
        """Write back onto a schedule. Never a reason to fail a pass.

        Dates go over as ISO 8601 rather than as `str(datetime)`, which spells
        the separator as a space and is not what Notion accepts.
        """
        if self.dry_run or not self.workspace.schedules:
            return
        written = {
            name: value.isoformat() if isinstance(value, datetime) else value
            for name, value in values.items()
        }
        try:
            self.client.update(self.workspace.schedules, schedule.page.id, written)
        except notion.NotionError as error:
            self.say(f"  ! {schedule.name} — Notion refused the write: {_line(error)}")

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

    # -- nothing left to spend -----------------------------------------------

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
        self._notify("ticket-runner is out of credit", f"Back to work at {when}.")

    def _requeue(
        self, ticket: Ticket, status: str, outcome: session.Outcome, note: str = ""
    ) -> dict:
        """Put a ticket back in the column it was taken from, and say why.

        The one way out of a run that is neither a success nor a failure:
        nothing was wrong with the ticket, there was simply nothing left to work
        on it with. So no question is asked and nobody's phone rings — the
        column it goes back to is the whole of the message, and the first run
        after the wait claims it like any other ticket.
        """
        said = self.voice
        when = credits.when(outcome.resets_at)
        self.say(f"    ⏸ {ticket.title} — out of credit, back in “{status}” until {when}")
        self._set(ticket, **{self.config.notion.prop("status"): status})
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
                # The one caller allowed to fetch a repository that is declared
                # but not on this machine: a ticket about to run needs the
                # clone to exist, and a project created from its GitHub link
                # alone has never had one made. A dry run stays a dry run.
                project = self.resolver.resolve(
                    self.client, relation[0], clone=not self.dry_run
                )
            except (LookupError, notion.NotionError) as error:
                self._fail(ticket, self.voice.say("no-project"), str(error), blocked=True)
                return None

        short = short_id(ticket.id)
        try:
            body = self.client.blocks_text(ticket.page.id)
        except notion.NotionError as error:
            self._fail(ticket, self.voice.say("unreadable"), str(error))
            return None
        if is_blank(body):
            body = ""
            if not ticket.page.title.strip():
                self._fail(
                    ticket,
                    self.voice.say("empty-ticket"),
                    self.voice.say("empty-ticket-detail"),
                    blocked=True,
                )
                return None
        elif not ticket.page.title.strip() and not self.dry_run:
            # Named before the branch is drawn, since the branch is made of the
            # title. Only a page whose title is empty ever gets here, so the
            # common case costs nothing — and a dry run writes nowhere.
            self._name(ticket, body, short)

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
        # `cloned` says the repository was not here until a minute ago — worth a
        # line, since the ticket is running on a folder nobody made by hand.
        # `note` says it was found by a way of last resort: the ticket runs, and
        # the ticket's comment says which declaration on the project page to
        # correct — or the page stays wrong for as long as the fallback works.
        for line in (project.cloned, project.note):
            if line:
                self.say("    · " + line)
                job.notes.append(line)
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

    def _name(self, ticket: Ticket, body: str, short: str) -> None:
        """Give a nameless ticket a title, and write it on the page.

        Into Notion rather than into this run's memory alone: the board has to
        show it too, or the page stays anonymous for whoever reads it back. And
        the page is what the runner then works from, so the branch, the report
        and the pull request all carry the same name.

        Never a reason to fail a ticket. A session that will not start, an
        answer that says nothing, a Notion that refuses the write: each of them
        is one line in the journal, and the ticket runs under the default
        label as it did before. The title is only kept once Notion has taken
        it — a branch named after something the board does not show would be a
        worse outcome than a ticket with no name.
        """
        title = ""
        workdir = state_dir() / "scratch" / f"name-{short}"
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            outcome = session.run(
                naming.prompt(body),
                cwd=workdir,
                log=state.log_file(f"{short}-name"),
                model=self.config.runner.model,
                # It reads one page and answers one line: the mode a
                # conversation runs in is more than it needs.
                permission_mode=self.config.runner.reply_permission_mode,
                timeout_minutes=naming.TIMEOUT_MINUTES,
                environment=self.environment,
            )
            if outcome.ok:
                title = naming.clean(outcome.answer)
            if not title:
                self.say("  ! the naming session said nothing usable — reading the content")
        except (OSError, ValueError) as error:
            self.say(f"  ! the ticket could not be named by a session: {_line(error)}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        title = title or naming.fallback(body)
        if not title:
            return
        try:
            self.client.update(
                self.database,
                ticket.page.id,
                {self.client.title_property(self.database): title},
            )
        except notion.NotionError as error:
            self.say(f"  ! the title could not be written to Notion: {_line(error)}")
            return
        ticket.page.title = title
        self.say(f"  · named “{title}” — the ticket had none of its own")

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
        self.say(f"    Claude session {job.session_id}{' · ' + chosen if chosen else ''} → {log}")
        live = job.live = self._live(job)
        try:
            outcome = session.run(
                text,
                cwd=job.workdir,
                log=log,
                model=chosen,
                permission_mode=self.config.runner.permission_mode,
                timeout_minutes=self.config.runner.timeout_minutes,
                session_id=job.session_id,
                environment=self.environment,
                on_event=live.event if live else None,
            )
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

    def _trace(self, job: Job, outcome: session.Outcome) -> str:
        """Where to look when the report was not enough — and only then.

        One sentence, and it no longer ends a report: it goes into the folded
        block of a run that failed, which is the only day anybody has wanted to
        read it. See `_filed`.
        """
        return self.voice.trace(outcome.resume_command, outcome.log, job.session_home)

    def _execute_document(self, job: Job) -> dict:
        """A ticket with no repository: the deliverable is the Notion page."""
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
            return self._requeue(ticket, self.config.notion.state("ready"), outcome)

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
        except notion.NotionError as error:
            return self._fail(
                ticket,
                said.say("answer-not-written"),
                _line(error),
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
        if self.config.runner.push:
            pushed = git.push(job.workdir, job.branch, force=worktree.reused)
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
                    pull_request = git.open_pull_request(job.workdir, ticket.title, body, job.base)
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
            _pull_request(said, pull_request) or said.say("on-branch", branch=job.branch),
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
                error=_line(outcome.error) or said.say("said-nothing"),
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
            prompt_module.follow_up(_message_of(text), self.voice.instruction(reply=True))
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
                done, flight = wait(flight, return_when=FIRST_COMPLETED)
                for future in done:
                    result = future.result()
                    results.append(result)
                    state.record(result)
                if self.waiting_for_credits():
                    # A session died on the quota while this pass was running.
                    # Every one it could still start would die on the same
                    # sentence, so nothing more is begun — what is in flight is
                    # left to finish, and the first pass after the wait picks
                    # the board up where it was.
                    queued = []
                    continue
                if refill and (remaining is None or remaining > 0):
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
            self.say(f"  ! the board could not be read again: {_line(error)}")
            return []
        fresh = [ticket for ticket in tickets if ticket.id not in started]
        # Queued or held for later, both are work about to happen: `converse`
        # leaves them alone, because their comments are going into a prompt.
        self._claimed |= {ticket.id for ticket in fresh} | {ticket.id for ticket, _ in waiting}
        if fresh:
            self.say(f"  ↺ {len(fresh)} ticket(s) ready since — filling the free place(s).")
        return fresh
