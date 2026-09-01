"""What the session is doing, written into the ticket while it does it.

A run used to be a black box: the ticket went to *In progress* and nothing more
was said until the pull request arrived, half an hour later. The transcript was
there all along — `ticket-runner logs -f` streams it — but that means a terminal
on the machine that runs the tickets, which is not where you are when you glance
at the board from a phone.

So the steps go **into the ticket**, as they happen. The run appends one toggle
to the page and drops its steps under it: the page stays as short as it was, and
the work is one click away. The toggle's own title carries the count and the
elapsed time, so a collapsed toggle still shows movement.

Two things keep it from becoming noise, and they are the whole design:

- **A cadence, not a stream.** Steps are buffered and written at most once every
  `progress_interval_seconds` (ten by default). A session emits several events a
  second; writing each one would rewrite the page continuously, spend the
  integration's rate limit and produce something nobody can read.
- **A line per tool call, never the payload.** A tool call becomes “Bash · npm
  test”, not the eight hundred lines it printed; the log remains the place for
  everything else. What the agent *said* is not a tool call and is not written
  like one: it goes down whole, as a paragraph under a rule, with its markdown
  honoured. Prose cut after two hundred characters stops being worth reading,
  and a sentence in bold on a bullet reads like shouting.

Nothing here can fail a ticket. Every call to Notion is caught, and a page that
refuses three writes in a row switches the whole thing off for the rest of the
session — the work carries on, unreported.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from . import markdown, notion

# The default cadence, in seconds. Ten is short enough to feel live and long
# enough that a page is not rewritten under the reader's eyes.
CADENCE = 10.0

# How much of a tool step survives into the page. A command, not a file.
LINE = 200

# How much of what the agent *said* survives. Generous on purpose: this is the
# part a human actually reads, and the only thing that should ever shorten it is
# a turn so long that a ticket page is the wrong place for it.
SAID = 5700

# A ceiling on the steps one session writes into its ticket. A long session can
# make hundreds of tool calls, and a ticket page is not a log file.
MAX_STEPS = 300

# Consecutive Notion refusals after which the reporting gives up for good.
MAX_FAILURES = 3


@dataclass
class Step:
    """One line of the story: what was done, and to what."""

    label: str
    detail: str = ""
    # Prose — what the agent said, as opposed to what it did. It is written as a
    # paragraph rather than a bullet, and it is not cut.
    said: bool = False

    @property
    def line(self) -> str:
        return f"{self.label} · {self.detail}" if self.detail else self.label


# The tools worth naming, and the input that says what they were pointed at.
# Anything else falls through to `_hint`, which is right often enough.
_TOOLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Bash": ("Bash", ("command",)),
    "Read": ("Read", ("file_path", "notebook_path")),
    "Write": ("Write", ("file_path",)),
    "Edit": ("Edit", ("file_path",)),
    "MultiEdit": ("Edit", ("file_path",)),
    "NotebookEdit": ("Edit", ("notebook_path",)),
    "Glob": ("Search", ("pattern",)),
    "Grep": ("Search", ("pattern",)),
    "Task": ("Sub-agent", ("description", "prompt")),
    "WebFetch": ("Web", ("url",)),
    "WebSearch": ("Web", ("query",)),
    "TodoWrite": ("Plan", ()),
    "SlashCommand": ("Command", ("command",)),
}

_HINTS = ("file_path", "command", "pattern", "query", "url", "description", "path", "prompt")


def _one_line(text: str, limit: int = LINE) -> str:
    """A block of text reduced to something that fits on a bullet."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _prose(text: str) -> str:
    """What the agent said, kept whole — only its blank lines are tidied.

    Its line breaks are its own: a paragraph holds them, and an agent that laid
    its answer out in three lines meant three lines.
    """
    lines = [" ".join(line.split()) for line in str(text).splitlines()]
    flat = "\n".join(line for line in lines if line)
    return flat if len(flat) <= SAID else flat[: SAID - 1].rstrip() + "…"


def _hint(payload: dict) -> str:
    for key in _HINTS:
        value = payload.get(key)
        if value:
            return _one_line(value)
    return ""


def describe(event: dict) -> list[Step]:
    """The steps a stream-json event is worth, in reading order.

    Assistant events carry both what the agent said and what it decided to do;
    both belong on the board. Tool *results* do not — they are the payload, and
    the payload is what the log is for — except when they failed, which is
    exactly the moment somebody watching would want to know.
    """
    kind = event.get("type")
    steps: list[Step] = []
    if kind == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text":
                spoken = _prose(block.get("text", ""))
                if spoken:
                    steps.append(Step(spoken, said=True))
            elif block.get("type") == "tool_use":
                name = str(block.get("name", "tool"))
                payload = block.get("input") or {}
                label, keys = _TOOLS.get(name, (name.split("__")[-1], ()))
                detail = ""
                for key in keys:
                    if payload.get(key):
                        detail = _one_line(payload[key])
                        break
                steps.append(Step(label, detail or _hint(payload)))
    elif kind == "user":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_result" and block.get("is_error"):
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                steps.append(Step("Error", _one_line(content or "")))
    return steps


def _rich(step: Step) -> list[dict]:
    parts: list[dict] = [
        {"type": "text", "text": {"content": step.label[:LINE]}, "annotations": {"bold": True}}
    ]
    if step.detail:
        parts.append({"type": "text", "text": {"content": "  "}})
        parts.append(
            {
                "type": "text",
                "text": {"content": step.detail[:LINE]},
                "annotations": {"code": True},
            }
        )
    return parts


def _bullet(step: Step) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich(step)},
    }


def _paragraph(step: Step) -> dict:
    """A sentence the agent wrote, as a sentence — whole, and in its own words.

    Notion caps one piece of rich text at two thousand characters, not the block
    that holds them, so a long turn is a handful of pieces and not a cut.
    """
    parts: list[dict] = []
    for start in range(0, len(step.label), markdown.MAX_CONTENT):
        parts += markdown.inline(step.label[start : start + markdown.MAX_CONTENT])
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": parts}}


def _divider() -> dict:
    """The rule that keeps what was said apart from what was done."""
    return {"object": "block", "type": "divider", "divider": {}}


class Live:
    """A ticket's live report: buffer the steps, write them on the cadence.

    Held by the job that runs the session, fed one event at a time, and closed
    when the session ends. Everything it writes is additive — the toggle it
    creates is its own, so a ticket run three times keeps the three stories.
    """

    def __init__(
        self,
        client: notion.Client,
        page_id: str,
        *,
        database: str = "",
        property_name: str = "",
        interval: float = CADENCE,
        heading: str = "Live",
        clock: Callable[[], float] = time.monotonic,
        say: Callable[[str], None] = lambda message: None,
    ) -> None:
        self.client = client
        self.page_id = page_id
        self.database = database
        self.property_name = property_name
        self.interval = max(1.0, float(interval))
        self.heading = heading
        self.clock = clock
        self.say = say
        self.started = clock()
        self.written = 0
        self.disabled = False
        self._pending: list[Step] = []
        self._last_flush = self.started
        self._last_line = ""
        self._toggle = ""
        self._failures = 0
        self._capped = False

    # -- feeding ------------------------------------------------------------

    def event(self, payload: dict) -> None:
        """One stream-json event. Writes only if the cadence has come round."""
        for step in describe(payload):
            self.add(step)

    def add(self, step: Step) -> None:
        if self.disabled or self._capped:
            return
        # Two identical lines in a row say nothing the first one did not: an
        # agent reading four files in a row would otherwise fill the toggle
        # with “Read”.
        previous = self._pending[-1].line if self._pending else self._last_line
        if step.line == previous:
            return
        self._pending.append(step)
        if self.clock() - self._last_flush >= self.interval:
            self.flush()

    # -- writing ------------------------------------------------------------

    def flush(self) -> int:
        """Write what has accumulated. Returns how many steps were written."""
        self._last_flush = self.clock()
        if self.disabled or self._capped or not self._pending:
            return 0
        steps, self._pending = self._pending, []
        room = MAX_STEPS - self.written
        if room <= 0:
            self._cap()
            return 0
        if len(steps) > room:
            steps = steps[:room]

        if not self._open():
            return 0
        try:
            self.client.append_blocks(self._toggle, self._blocks(steps))
        except notion.NotionError as error:
            self._failed(error)
            return 0
        self._failures = 0
        self.written += len(steps)
        self._last_line = steps[-1].line
        self._retitle(f"⏳ {self.heading} — {self._tally()}")
        self._publish(_one_line(self._last_line))
        if self.written >= MAX_STEPS:
            self._cap()
        return len(steps)

    def close(self, note: str = "") -> None:
        """Last flush, then the toggle stops saying it is live."""
        if self.disabled:
            return
        self.flush()
        if not self._toggle:
            return
        tail = f" · {_one_line(note, 120)}" if note else ""
        self._retitle(f"✓ {self._tally()}{tail}")
        # The ticket's own report — the comment, the status, the pull request —
        # is what speaks now; a column still showing “Edit src/x.py” would be
        # saying something that stopped being true.
        self._publish("")

    def _blocks(self, steps: list[Step]) -> list[dict]:
        """The blocks a batch of steps becomes.

        A tool call is a bullet: it is one line, and a list of them is scannable
        at a glance. Prose is a paragraph, preceded by a rule — which is what
        turns the toggle from one long list into what it really is, a run of
        short sections, each headed by what the agent said it was about to do.
        """
        blocks: list[dict] = []
        for step in steps:
            if not step.said:
                blocks.append(_bullet(step))
                continue
            if blocks or self.written:
                blocks.append(_divider())
            blocks.append(_paragraph(step))
        return blocks

    # -- the page -----------------------------------------------------------

    def _open(self) -> bool:
        """Create the toggle, on the first step and not before.

        Lazily, so a session that ends before it did anything leaves no empty
        “Live” block behind on the ticket.
        """
        if self._toggle:
            return True
        try:
            created = self.client.append_blocks(
                self.page_id,
                [
                    {
                        "object": "block",
                        "type": "toggle",
                        "toggle": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": f"⏳ {self.heading}"},
                                    "annotations": {"bold": True},
                                }
                            ]
                        },
                    }
                ],
            )
        except notion.NotionError as error:
            self._failed(error)
            return False
        if not created:
            self.disabled = True
            return False
        self._toggle = created[0]
        return True

    def _retitle(self, title: str) -> None:
        if not self._toggle:
            return
        try:
            self.client.update_block(
                self._toggle,
                {
                    "toggle": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": title[:LINE]},
                                "annotations": {"bold": True},
                            }
                        ]
                    }
                },
            )
        except notion.NotionError as error:
            self._failed(error)

    def _publish(self, line: str) -> None:
        """The current step, in the board's own column — when there is one."""
        if not (self.database and self.property_name):
            return
        try:
            self.client.update(self.database, self.page_id, {self.property_name: line})
        except notion.NotionError as error:
            self._failed(error)

    def _cap(self) -> None:
        """Enough. The steps stop; the toggle still gets its closing title.

        A ticket page is not a log file, and a session that makes a thousand
        tool calls would turn it into one. What stops here is the *steps* — the
        run carries on, and `close` still says how it ended.
        """
        if self._capped:
            return
        self._capped = True
        self._pending = []
        if not self._toggle:
            return
        try:
            self.client.append_blocks(
                self._toggle,
                [_bullet(Step("…", f"more than {MAX_STEPS} steps — the rest is in the log"))],
            )
        except notion.NotionError:
            pass

    def _tally(self) -> str:
        minutes = (self.clock() - self.started) / 60
        return f"{self.written} step(s) · {minutes:.0f} min"


    def _failed(self, error: notion.NotionError) -> None:
        self._failures += 1
        if self._failures < MAX_FAILURES:
            return
        self.disabled = True
        self.say(f"    ! live steps switched off for this ticket: {error}")
