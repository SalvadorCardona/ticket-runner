"""Talking to the runner in the comments, rather than only through the board.

A ticket already had one way of answering you: it ran. You wrote a comment
under a `blocked` report, the next run read it and did the work again. That is
the right gesture for *do this differently* — and the wrong one for *why did you
do it like that?*, which is most of what one actually wants to say to something
that just wrote code on one's behalf.

So a comment can also simply be **answered**. Same place, same thread, no status
moved, nothing built: the runner replies under your question the way a colleague
would, and the board does not pretend anything happened.

Three rules keep that from turning into noise, and they are all about knowing
who is being spoken to:

- **a thread the runner already speaks in belongs to it.** Reply under its
  report and it answers you. A new remark elsewhere on the page is a
  conversation of yours, and stays one;
- **naming it works wherever the runner is looking.** A comment carrying
  `@claude` — or whatever `notion.mention` says, or the integration's own name
  as Notion writes it when you @-mention it — is addressed to the runner,
  whatever the ticket's status. Where it looks is the `Ledger`'s business;
- **work wins over talk.** A plain answer under a question a run asked is still
  what puts the ticket back in the queue: that loop was the point of `blocked`,
  and it keeps it. Naming the runner is how you ask for words instead.

And one rule about not talking to itself. Every comment the runner writes comes
back to it on the next pass; recognising its own voice by the signature it
happens to write would hold until the day it writes something else. So it asks
Notion for its own user ID and compares identifiers — and when it cannot get
one, it says nothing at all. A conversation with oneself is the single failure
mode here that never ends on its own.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import notion
from .config import state_dir

# What to call it when you want its attention. Configurable — `notion.mention` —
# because the word has to be one you would type, and half the boards this runs
# on are written in French.
MENTION = "@claude"

# Always understood, whatever the configuration says: the tool's own name is not
# something anyone should have to declare in order to be able to use it.
ALIASES = ("@ticket-runner", "@runner")

# How many pages one pass looks at, and how many answers it writes. The scan is
# one request per page and a run can happen every ten seconds; the answers are
# Claude sessions, and five people waiting is already a busy afternoon.
SCAN = 20
ANSWERS = 5

# How a comment relayed from Telegram or Slack opens (see `channels.answer`).
# It is written by the integration and it is *not* the runner speaking: it is
# you, from your phone, and it has to wake a blocked ticket exactly as the same
# words typed into Notion would. Shared with `channels` rather than spelled
# twice, because the day the sentence changes in one place and not the other,
# every answer given from a phone stops arriving.
RELAYED = "Answered from "

# A comment is a comment. Past this, the answer is a document, and a document
# belongs in the page rather than under it.
ANSWER_CHARS = 4000

# What the ledger remembers, at most. Beyond this the oldest are dropped: a
# conversation nobody has touched in two hundred tickets is over.
REMEMBERED = 200


@dataclass
class Thread:
    """One discussion on a page, oldest comment first.

    Notion groups comments into discussions, and that grouping is what makes an
    answer an answer: posted into the thread it belongs to, it sits under the
    question instead of at the bottom of the page.
    """

    discussion: str
    comments: list[notion.Comment] = field(default_factory=list)

    @property
    def last(self) -> notion.Comment:
        return self.comments[-1]

    def spoken_by(self, user: str) -> bool:
        return any(ours(comment, user) for comment in self.comments)


def is_relayed(text: str) -> bool:
    """Was this comment written by the integration on somebody else's behalf?

    An answer given in Telegram or Slack is posted here by the runner's own
    token, which makes it look like the runner talking. It is not: it is the
    ticket's author, one device removed.
    """
    return text.lstrip().startswith(RELAYED)


def said(text: str) -> str:
    """A relayed comment without the line that says where it came from.

    “Answered from Telegram by Salva.” is an address, not a message: read back
    in the console's own terminal the words belong under your name, and the name
    is already on the turn.
    """
    text = text.strip()
    if not is_relayed(text):
        return text
    _, _, rest = text.partition("\n")
    return rest.strip() or text


def ours(comment: notion.Comment, me: str) -> bool:
    """Is this the runner's own voice — not merely its token?"""
    return bool(me) and comment.created_by == me and not is_relayed(comment.text)


def threads(comments: Iterable[notion.Comment]) -> list[Thread]:
    """The comments of a page, grouped into their discussions, in order.

    A comment whose discussion Notion did not give us is a thread of one rather
    than a thread of everything: lumping unrelated remarks together would have
    the runner answer a question nobody asked it.
    """
    order: list[str] = []
    grouped: dict[str, Thread] = {}
    for index, comment in enumerate(comments):
        key = comment.discussion_id or comment.id or f"loose-{index}"
        if key not in grouped:
            grouped[key] = Thread(key)
            order.append(key)
        grouped[key].comments.append(comment)
    return [grouped[key] for key in order]


def names(mention: str = "", integration: str = "") -> tuple[str, ...]:
    """Every way of naming the runner in a comment.

    The configured word, the built-in aliases, and the integration's own name —
    the last one because @-mentioning it in Notion is the gesture people
    actually make, and it reaches the API as that name in plain text. A name
    under four characters is left out: a bot called “IA” would answer every
    sentence containing it.
    """
    found = [mention.strip() or MENTION, *ALIASES]
    if len(integration.strip()) >= 4:
        found.append(integration.strip())
    return tuple(dict.fromkeys(name for name in found if name))


def addressed(text: str, spellings: Iterable[str]) -> bool:
    """Is this comment speaking *to* the runner, rather than about the ticket?

    Matched as a whole word, with or without its `@`, anywhere in the comment —
    “@claude tu peux relire ?” and “une idée, claude ?” are the same gesture.
    Inside a longer word it is not: `claudette` is somebody's name.
    """
    for spelling in spellings:
        bare = re.escape(spelling.lstrip("@"))
        if re.search(rf"(?<![\w@])@?{bare}\b", text, flags=re.IGNORECASE):
            return True
    return False


def waiting(
    comments: Iterable[notion.Comment], *, me: str, spellings: Iterable[str]
) -> list[Thread]:
    """The threads of a page that are waiting on a reply from the runner.

    Empty when we do not know who we are: without an identity there is no way to
    tell our own last word from yours, and answering ourselves is worse than
    answering nothing.
    """
    if not me:
        return []
    pending = []
    for thread in threads(comments):
        last = thread.last
        if not last.text.strip() or ours(last, me):
            continue
        if addressed(last.text, spellings) or thread.spoken_by(me):
            pending.append(thread)
    return pending


def strip_mention(text: str, spellings: Iterable[str]) -> str:
    """The message without the name it opens with.

    Only at the start, and only once: “@claude pourquoi ?” is addressed to the
    runner and says “pourquoi ?”, while a name in the middle of a sentence is
    part of the sentence.
    """
    for spelling in spellings:
        bare = re.escape(spelling.lstrip("@"))
        cleaned = re.sub(rf"^\s*@?{bare}\b[\s,:—-]*", "", text, count=1, flags=re.IGNORECASE)
        if cleaned != text:
            return cleaned.strip() or text.strip()
    return text.strip()


def transcript(thread: Thread, me: str, limit: int = 12, budget: int = 2000) -> list[str]:
    """What has been said in this thread, ready for a prompt, newest last.

    Bounded like the ticket's own discussion is, and for the same reason: a
    thread six answers deep would otherwise spend the prompt on itself. The
    last comment is left out — it is the message being answered, and it gets a
    section of its own.
    """
    lines: list[str] = []
    for comment in reversed(thread.comments[:-1][-limit:]):
        who = "you" if ours(comment, me) else "them"
        line = f"{who}: {' '.join(comment.text.split())}"
        budget -= len(line)
        if budget < 0:
            break
        lines.append(line)
    return list(reversed(lines))


# -- what the runner remembers between passes --------------------------------


def ledger_path() -> Path:
    state_dir().mkdir(parents=True, exist_ok=True)
    return state_dir() / "conversations.json"


@dataclass
class Ledger:
    """Where the runner speaks, and what it has already answered.

    Two things live here, and neither is worth a database. **The pages it has
    spoken on**, because a comment does not change a page and Notion offers no
    way to ask "what has been commented on since": the only affordable scan is
    of the pages where a conversation could plausibly be. And **the thread it is
    talking in**, with the Claude session that is doing the talking — so a
    follow-up question lands in the same session as the one before it, and the
    conversation is a conversation rather than a series of strangers.
    """

    pages: dict[str, str] = field(default_factory=dict)
    threads: dict[str, dict] = field(default_factory=dict)
    cursor: int = 0
    at: float = 0.0
    path: Path = field(default_factory=ledger_path)

    @classmethod
    def load(cls, path: Path | None = None) -> "Ledger":
        target = path or ledger_path()
        ledger = cls(path=target)
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ledger
        if not isinstance(raw, dict):
            return ledger
        ledger.pages = {
            str(key): str(value) for key, value in (raw.get("pages") or {}).items()
        }
        ledger.threads = {
            str(key): value
            for key, value in (raw.get("threads") or {}).items()
            if isinstance(value, dict)
        }
        try:
            ledger.cursor = int(raw.get("cursor") or 0)
        except (TypeError, ValueError):
            ledger.cursor = 0
        try:
            ledger.at = float(raw.get("at") or 0.0)
        except (TypeError, ValueError):
            ledger.at = 0.0
        return ledger

    def save(self) -> None:
        """Best effort: a ledger that cannot be written costs a resumed session
        and a rotation, never a run."""
        payload = {
            "pages": _newest(self.pages, REMEMBERED),
            "threads": _newest_threads(self.threads, REMEMBERED),
            "cursor": self.cursor,
            "at": self.at,
        }
        try:
            self.path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.path.chmod(0o600)
        except OSError:
            pass

    def due(self, interval_seconds: int) -> bool:
        """Has enough time passed to look at the board again?

        The scan is a request per page, and a run can come round every ten
        seconds — while a comment, unlike a ticket, is written by a person and
        can wait a minute. This is the difference between a feature and a way of
        spending the integration's rate limit.
        """
        return time.time() - self.at >= max(0, interval_seconds)

    def stamp(self) -> None:
        self.at = time.time()

    # -- pages ---------------------------------------------------------------

    def remember_page(self, page_id: str) -> None:
        """The runner just spoke here, so here is where it may be answered."""
        if page_id:
            self.pages[page_id.replace("-", "")] = _now()

    def known_pages(self) -> list[str]:
        """The pages it has spoken on, most recently first."""
        return [page for page, _ in sorted(self.pages.items(), key=lambda item: item[1], reverse=True)]

    def rotate(self, pages: list[str], limit: int) -> list[str]:
        """`limit` pages to look at now, taking the next ones each pass.

        A board is scanned a page at a time and a run can come round every ten
        seconds; taking the whole list every pass would spend the integration's
        rate limit on tickets nobody has touched in a month. So the window
        moves, and every page comes up within a few passes.
        """
        if not pages:
            return []
        if limit <= 0 or limit >= len(pages):
            self.cursor = 0
            return list(pages)
        start = self.cursor % len(pages)
        window = (pages + pages)[start : start + limit]
        self.cursor = (start + limit) % len(pages)
        return window

    # -- threads -------------------------------------------------------------

    def session_of(self, discussion: str) -> str:
        return str((self.threads.get(discussion) or {}).get("session") or "")

    def answered(self, discussion: str) -> str:
        """The ID of the last comment the runner answered in that thread.

        Notion can hand back a comment we have just replied to — the reply
        travels, the read is a moment behind. Without this the second pass would
        answer the same question twice, in the same thread, minutes apart.
        """
        return str((self.threads.get(discussion) or {}).get("answered") or "")

    def remember_thread(self, discussion: str, *, session: str, comment: str) -> None:
        if not discussion:
            return
        entry = dict(self.threads.get(discussion) or {})
        entry.update({"session": session, "answered": comment, "at": _now()})
        self.threads[discussion] = entry

    def forget_session(self, discussion: str) -> None:
        """A session that could not be resumed is a session that is gone.

        Its transcript was pruned, or the machine changed. The thread keeps its
        history in Notion, which is enough to start a fresh one from.
        """
        if discussion in self.threads:
            self.threads[discussion] = {
                **self.threads[discussion], "session": "", "at": _now()
            }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _newest(entries: dict[str, str], keep: int) -> dict[str, str]:
    ordered = sorted(entries.items(), key=lambda item: item[1], reverse=True)
    return dict(ordered[:keep])


def _newest_threads(entries: dict[str, dict], keep: int) -> dict[str, dict]:
    ordered = sorted(entries.items(), key=lambda item: str(item[1].get("at", "")), reverse=True)
    return dict(ordered[:keep])


def trim(answer: str, limit: int = ANSWER_CHARS) -> str:
    """An answer cut to the length of a comment, on a paragraph if it can be."""
    answer = answer.strip()
    if len(answer) <= limit:
        return answer
    cut = answer[:limit]
    edge = max(cut.rfind("\n\n"), cut.rfind("\n"), cut.rfind(". "))
    if edge > limit // 2:
        cut = cut[: edge + 1]
    return cut.rstrip() + "\n\n[…] the rest was too long for a comment — ask for it in pieces."


def talk_dir(short: str) -> Path:
    """Where a conversation about a ticket without a repository runs.

    Kept rather than made and destroyed, because Claude Code files a session
    under the directory it ran in: a scratch directory drawn afresh every time
    would make every follow-up a stranger.
    """
    path = state_dir() / "talks" / short
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_talks(keep: Iterable[str]) -> int:
    """Drop the scratch directories of conversations no longer remembered."""
    root = state_dir() / "talks"
    if not root.is_dir():
        return 0
    wanted = set(keep)
    removed = 0
    for path in root.iterdir():
        if path.name not in wanted and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed
