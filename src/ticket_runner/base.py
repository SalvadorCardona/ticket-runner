"""What every other piece of a run has under its hand.

A run is deliberately *one* object: one Notion client, one reading of the
workspace, one cache of a page's comments, one ledger of what has been said and
one lock over it. Two of them would mean two claims on the same ticket, the
same thread fetched twice, and a comment answered by whichever half read it
last — so the state below is not split, and cannot be.

What was split is the work. Each responsibility of a run — reading the board,
writing on a ticket, preparing one, executing it, delivering it, answering a
comment — is a class of its own in a module of its own, and `Runner` is those
classes put together over this one. A class that *adds methods* to the run
rather than a collaborator holding a reference back to it: the state stays in
one place, every call site stays the plain `self._fail(...)` it has always
been, and each module reads as the one chapter it is.

Which leaves this module as the bottom of that pile: the configuration, the
client, the caches, what the runner says out loud, and the three things a run
resolves once and re-reads all day.
"""

from __future__ import annotations

import socket
import threading
from datetime import datetime

from . import conversation, notify, notion, openrouter
from . import voice as voice_module
from . import workspace as workspace_module
from .config import Config
from .projects import Resolver
from .ticket import Ticket


class Base:
    """The state of one run, and the little every module of it needs."""

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

    def say(self, message: str) -> None:
        if not self.quiet:
            print(message, flush=True)

    def _notify(
        self, title: str, body: str, *, urgent: bool = False, link: str = ""
    ) -> None:
        if self.config.notify.desktop and not self.dry_run:
            notify.send(title, body, urgent=urgent, link=link)
