"""Where the runner reaches you, and where you answer it from.

A run happens while you are elsewhere — that is the whole point — and the two
moments that need you are the two the board is worst at delivering: the agent
asked a question, and a pull request is waiting. A desktop notification only
works if you are in front of that desktop. So the runner also talks to a
messaging app, and **a message you answer is an answer to the ticket**: the
reply comes back as a Notion comment, and the comment is already how a blocked
ticket wakes up (see `runner.woken`). Nothing new on the board, no second
mechanism — one word in Telegram and the ticket runs again on the next pass.

Two channels, both polled:

- **Telegram** — a bot token, a chat id, and nothing else. No public URL, no
  webhook, no domain: `getUpdates` is a plain GET, which is what makes this the
  one channel that installs in two minutes on a laptop behind a NAT;
- **Slack** — a bot token and a channel. `conversations.history` for what was
  said in the channel, `conversations.replies` for what was said under a
  question. Same polling shape, same absence of an inbound port.

WhatsApp is deliberately not here: its API delivers inbound messages *only* to
a public HTTPS webhook you have to host and have verified by Meta, which is a
server and a business account — the opposite of a runner that lives on your
machine. A `Channel` is four methods, though, so the day you have that endpoint
it is one file.

Everything fails quietly, for the reason desktop notifications do: a token that
expired, a channel the bot was removed from, a network that is down — none of
that is a reason for a ticket to fail. The Notion comment stays the record.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..config import Notify, state_dir

# How many questions a channel remembers, so that a reply arriving tomorrow
# still knows which ticket it answers. Ten is a fortnight of a normal board.
ASKS = 10
TIMEOUT = 20


class ChannelError(Exception):
    """The service refused, or could not be reached."""


# -- transport ---------------------------------------------------------------


def request(url: str, payload: dict | None = None, *, headers: dict | None = None) -> dict:
    """One JSON call. Both APIs speak JSON both ways, so one helper does."""
    data = json.dumps(payload).encode() if payload is not None else None
    every = {"Content-Type": "application/json; charset=utf-8", "User-Agent": "ticket-runner"}
    every.update(headers or {})
    message = urllib.request.Request(url, data=data, headers=every)
    try:
        with urllib.request.urlopen(message, timeout=TIMEOUT) as response:
            body = response.read() or b"{}"
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:400]
        # Telegram says what is wrong in the body of a 4xx, and that sentence
        # is the whole diagnosis ("chat not found"). Losing it for the status
        # code would leave the user with a number.
        try:
            detail = json.loads(detail).get("description", detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        raise ChannelError(f"{error.code} {detail}") from error
    except (urllib.error.URLError, OSError) as error:
        raise ChannelError(str(getattr(error, "reason", error))) from error
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise ChannelError("the answer was not JSON") from error


# -- what travels ------------------------------------------------------------


@dataclass
class Incoming:
    """One message read from a channel, before it is attached to a ticket."""

    ref: str = ""
    thread: str = ""
    text: str = ""
    who: str = ""


@dataclass
class Reply:
    """An incoming message, once it is known what it answers."""

    channel: str
    text: str
    ticket: str = ""
    title: str = ""
    # The message itself, and the question it hangs under — not the same thing,
    # and the two channels acknowledge on opposite ones. See `_thread_of`.
    ref: str = ""
    thread: str = ""
    who: str = ""


@dataclass
class Ask:
    """A question the runner sent, kept so that its answer can find its way."""

    ref: str
    ticket: str
    title: str = ""
    at: str = ""


# -- yes, no, and everything else --------------------------------------------

_YES = {
    "y", "yes", "yep", "yeah", "ok", "okay", "go", "sure", "do it", "ship it",
    "oui", "ouais", "vas-y", "vas y", "allez", "d'accord", "daccord", "ça marche",
    "ca marche", "👍", "✅", "👌",
}
_NO = {
    "n", "no", "nope", "nah", "stop", "cancel", "drop it",
    "non", "nan", "laisse", "laisse tomber", "annule", "👎", "❌", "🚫",
}


def decide(text: str) -> str:
    """"yes", "no", or "" for anything that is not one of those two.

    Only the *first* word is read, and only when it stands alone or opens the
    sentence: "yes, and rename the column while you are there" is a yes with an
    instruction attached, while "no idea what you mean" is not a no. The rest of
    the message travels either way — the verdict never replaces what was said.
    """
    stripped = " ".join(text.strip().lower().split())
    if not stripped:
        return ""
    if any(_opens(stripped, word) for word in _YES):
        return "yes"
    if any(_opens(stripped, word) for word in _NO):
        return "no"
    return ""


def _opens(sentence: str, word: str) -> bool:
    return sentence == word or sentence.startswith(f"{word} ") or sentence.startswith(f"{word},")


def answer(reply: Reply) -> str:
    """The comment a reply becomes, written for the session that will read it.

    A bare "oui" means nothing to an agent reading the ticket a minute later —
    it has no idea it is being approved. So the verdict is spelled out, and
    whatever else was said is kept underneath, untouched: the word is a
    shortcut, not a translation.
    """
    verdict = decide(reply.text)
    said = " ".join(reply.text.split())
    lines = [f"Answered from {reply.channel.title()}" + (f" by {reply.who}" if reply.who else "") + "."]
    if verdict == "yes":
        lines.append("Yes — go ahead with what you proposed.")
    elif verdict == "no":
        lines.append("No — do not do that.")
    if said and (not verdict or len(said.split()) > 1):
        lines.append(said)
    return "\n".join(lines)


# -- what a channel remembers ------------------------------------------------


def memory_path() -> Path:
    state_dir().mkdir(parents=True, exist_ok=True)
    return state_dir() / "channels.json"


def _memory() -> dict:
    path = memory_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A cursor lost is a handful of messages read twice, not a broken run.
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _remember(name: str, changes: dict) -> None:
    everything = _memory()
    everything[name] = {**everything.get(name, {}), **changes}
    try:
        memory_path().write_text(
            json.dumps(everything, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


# -- a channel ---------------------------------------------------------------


class Channel:
    """Send a message, remember what it was about, read what came back.

    Subclasses supply the two ends — `_post` and `_fetch` — and inherit the
    part that is the same everywhere: which ticket an answer belongs to.
    """

    name = ""
    # May a message that threads nothing and names nothing answer the last
    # question asked? True where everything written is addressed to the runner
    # — a private Telegram chat — and false in a room shared with other people.
    fallback = True

    # -- outbound ------------------------------------------------------------

    def send(self, text: str, *, ticket: str = "", title: str = "", ask: bool = False) -> bool:
        try:
            reference = self._post(text)
        except ChannelError:
            return False
        if ask and ticket:
            asks = [Ask(**item) for item in _memory().get(self.name, {}).get("asks", [])]
            asks.append(
                Ask(
                    ref=reference,
                    ticket=ticket,
                    title=title,
                    at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
            )
            _remember(self.name, {"asks": [vars(item) for item in asks[-ASKS:]]})
        return True

    def acknowledge(self, reply: Reply, text: str) -> bool:
        """Say where an answer landed, under the message that carried it.

        Not politeness: a reply typed into a phone is otherwise indistinguishable
        from a reply nobody read, and the whole point of answering from Telegram
        is not having to go and check the board afterwards.
        """
        try:
            self._post(text, thread=self._thread_of(reply))
        except ChannelError:
            return False
        return True

    def _thread_of(self, reply: Reply) -> str:
        """What an acknowledgement hangs off: the message that carried it.

        Which is a Telegram reply — the notification on the phone then quotes
        your own "oui" back at you. Slack counts threads from their first
        message instead, so it overrides this.
        """
        return reply.ref

    # -- inbound -------------------------------------------------------------

    def collect(self) -> list[Reply]:
        mine = _memory().get(self.name, {})
        asks = [Ask(**item) for item in mine.get("asks", [])]
        listening = bool(mine.get("listening"))
        incoming, cursor = self._fetch(str(mine.get("cursor", "")), asks)
        _remember(self.name, {"listening": True, **({"cursor": cursor} if cursor else {})})
        if not listening:
            # The first poll of a channel only establishes where "now" is.
            # Telegram keeps a day of updates and Slack a channel's whole
            # history: everything said before the runner started listening is a
            # conversation, not a queue of answers, and pouring it onto the
            # board would be a spectacular first impression.
            #
            # A flag of its own rather than "is there a cursor yet", because a
            # first poll that finds nothing has no cursor to write — and would
            # otherwise throw away the first real answer as well.
            return []
        replies = []
        for message in incoming:
            if not message.text.strip():
                continue
            match = self._route(message, asks)
            replies.append(
                Reply(
                    channel=self.name,
                    text=message.text,
                    ticket=match.ticket if match else "",
                    title=match.title if match else "",
                    ref=message.ref,
                    thread=message.thread,
                    who=message.who,
                )
            )
        return replies

    def _route(self, message: Incoming, asks: list[Ask]) -> Ask | None:
        """Which question this message answers — threading first, then words.

        Three readings, narrowest first. A reply *to* one of our messages says
        so itself and is never guessed at. A message naming a ticket — pasting
        its link, or the eight characters the runner prints everywhere — means
        that one. And a message that does neither answers the last question
        asked, which is what "oui" means when it arrives thirty seconds after
        the phone buzzed.

        That last reading is the one a shared room does not get: in Slack the
        message beside yours belongs to somebody else's conversation, and
        writing it onto a ticket would be worse than missing an answer.
        """
        if message.thread:
            for ask in reversed(asks):
                if ask.ref == message.thread:
                    return ask
        haystack = re.sub(r"[^a-z0-9]", "", message.text.lower())
        for ask in reversed(asks):
            identifier = ask.ticket.replace("-", "").lower()
            if identifier and (identifier in haystack or identifier[-8:] in haystack):
                return ask
        return asks[-1] if asks and self.fallback else None

    # -- the two ends a channel has to provide -------------------------------

    def _post(self, text: str, thread: str = "") -> str:
        raise NotImplementedError

    def _fetch(self, cursor: str, asks: list[Ask]) -> tuple[list[Incoming], str]:
        raise NotImplementedError

    def check(self) -> str:
        """Who the runner speaks as, and where — or ChannelError saying why not.

        The one thing `doctor` cannot infer from the configuration file: a token
        that has been revoked and a channel the bot was removed from both look
        exactly like a correct configuration until the first question goes
        unanswered.
        """
        raise NotImplementedError


# -- the ones there are ------------------------------------------------------


def open(settings: Notify) -> list[Channel]:  # noqa: A001 — it opens channels
    """Every channel the configuration names, ready to talk. Never raises."""
    from . import slack as slack_module
    from . import telegram as telegram_module

    live: list[Channel] = []
    if settings.telegram.get("token") and settings.telegram.get("chat"):
        live.append(
            telegram_module.Telegram(settings.telegram["token"], str(settings.telegram["chat"]))
        )
    if settings.slack.get("token") and settings.slack.get("channel"):
        live.append(slack_module.Slack(settings.slack["token"], str(settings.slack["channel"])))
    return live


def announce(
    settings: Notify, text: str, *, ticket: str = "", title: str = "", ask: bool = False
) -> int:
    """Send one message to every configured channel. Returns how many took it."""
    return sum(
        1
        for channel in open(settings)
        if channel.send(text, ticket=ticket, title=title, ask=ask)
    )
