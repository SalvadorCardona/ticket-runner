"""What the console shows without being asked: the board, and the sessions.

One stream reaches the browser, and everything travels on it — the board, the
steps of a running ticket, the chat, the output of a command. A page that opened
three connections would have to reconnect three times after a suspend, and would
still have to put the events back in order at the far end.

Two rules keep it honest:

- **nobody watching, nothing polled.** The board is read from Notion only while
  a browser is connected. A console left open in a tab is one reader; a console
  nobody opened must cost the integration nothing at all;
- **the logs are the live feed, not Notion.** A running ticket already writes its
  session to disk, ten events a second. Tailing that file is free and instant,
  where asking Notion what it is doing would be neither.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from .. import progress, state

# What a browser connecting mid-flight is given to catch up with. Enough to
# rebuild a running session's steps, small enough to send in one go.
BACKLOG = 300

# A log stops being live this long after its last write. Past that the session is
# over — the runner has moved on and nothing more will be appended.
IDLE_SECONDS = 180


@dataclass
class Event:
    kind: str
    payload: dict
    id: int = 0
    at: float = field(default_factory=time.time)

    def encode(self) -> str:
        body = json.dumps({"kind": self.kind, "at": self.at, **self.payload}, ensure_ascii=False)
        return f"id: {self.id}\nevent: {self.kind}\ndata: {body}\n\n"


class Hub:
    """Fan-out to every connected browser, plus a backlog for the next one."""

    def __init__(self, backlog: int = BACKLOG) -> None:
        self._lock = threading.Lock()
        self._clients: set[queue.Queue] = set()
        self._backlog: deque[Event] = deque(maxlen=backlog)
        # Every event is numbered, and the number is the SSE id. A browser
        # reconnecting after a suspend hands back the last one it saw, and gets
        # what it missed — rather than the whole backlog a second time.
        self._sequence = 0
        # The board and the run's state are *states*, not events: a browser
        # connecting wants the current one, not the last twenty. They are kept
        # aside, by kind, and replayed after the backlog.
        self._latest: dict[str, Event] = {}

    def publish(self, kind: str, **payload: object) -> None:
        with self._lock:
            self._sequence += 1
            event = Event(kind, dict(payload), id=self._sequence)
            if kind in ("board", "state"):
                self._latest[kind] = event
            else:
                self._backlog.append(event)
            clients = list(self._clients)
        for client in clients:
            try:
                client.put_nowait(event)
            except queue.Full:
                # A browser that stopped reading is a browser that went away.
                # Dropping the event beats blocking the runner behind it.
                pass

    def subscribe(self, after: int = 0) -> queue.Queue:
        """A channel, primed with what this browser has not seen.

        A first connection (`after` is zero) is given the current board and
        nothing else: its transcript comes from `/api/chat`, and replaying the
        backlog on top of that would show every message twice. A reconnection
        names the last event it saw, and gets exactly what came after it.
        """
        channel: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            replay = list(self._latest.values())
            if after:
                replay += [event for event in self._backlog if event.id > after]
            for event in sorted(replay, key=lambda event: event.id):
                try:
                    channel.put_nowait(event)
                except queue.Full:
                    break
            self._clients.add(channel)
        return channel

    def unsubscribe(self, channel: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(channel)

    @property
    def watchers(self) -> int:
        with self._lock:
            return len(self._clients)


class Tail:
    """The session logs, read forward, turned into steps as they are written.

    Position is kept per file, so a log already half-read when the console opens
    does not replay from its first line — except once, on the first pass, which
    is what puts a session already in flight on the screen.
    """

    def __init__(self, hub: Hub, directory: Path | None = None) -> None:
        self.hub = hub
        self.directory = directory or state.logs_dir()
        self._offsets: dict[str, int] = {}
        self._seen: set[str] = set()

    def pass_once(self) -> int:
        published = 0
        for path in self._live_logs():
            published += self._read(path)
        return published

    def _live_logs(self) -> Iterator[Path]:
        cutoff = time.time() - IDLE_SECONDS
        try:
            paths = sorted(self.directory.glob("*.jsonl"))
        except OSError:
            return
        for path in paths:
            try:
                if path.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            yield path

    def _read(self, path: Path) -> int:
        key = path.name
        first = key not in self._seen
        self._seen.add(key)
        offset = self._offsets.get(key, 0)
        try:
            size = path.stat().st_size
            if size < offset:  # truncated or replaced: start over
                offset = 0
            if first:
                # A session already running when the console opened: give it its
                # last few steps rather than its first, so the panel opens on
                # where the work *is*.
                offset = max(0, size - 200_000)
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                lines = handle.readlines()
                self._offsets[key] = handle.tell()
        except OSError:
            return 0

        published = 0
        for line in lines:
            if not line.endswith("\n"):  # a half-written line: next pass has it
                self._offsets[key] -= len(line.encode("utf-8", "replace"))
                break
            for step in steps(line):
                self.hub.publish(
                    "step", source=_ticket(key), log=key, label=step.label, detail=step.detail
                )
                published += 1
        return published


def steps(line: str) -> list[progress.Step]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return []
    return progress.describe(event)


def _ticket(filename: str) -> str:
    """The ticket a log belongs to: `20260830-120000-1a2b3c4d.jsonl` → `1a2b3c4d`."""
    return filename.removesuffix(".jsonl").rsplit("-", 1)[-1]


class Watch:
    """One thread, running only while somebody is looking.

    The board is asked of Notion every `interval` seconds; the logs are tailed
    every second, because that is where "live" actually happens and it costs a
    stat call. Both stop the moment the last browser disconnects.
    """

    def __init__(
        self,
        hub: Hub,
        board: Callable[[], dict],
        *,
        interval: int = 15,
        directory: Path | None = None,
    ) -> None:
        self.hub = hub
        self.board = board
        self.interval = max(5, interval)
        self.tail = Tail(hub, directory)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._fingerprint = ""
        self._nudged = threading.Event()

    def ensure_running(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="tr-watch", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def nudge(self) -> None:
        """Ask for a board read on the next tick, without waiting for it here.

        A ticket created or moved from the console should show up at once — but
        the browser must not sit through a Notion round trip to be told the
        write it just made succeeded. The watching thread does it, a second
        later, and the board arrives on the stream like any other.
        """
        self._nudged.set()

    def refresh(self, *, force: bool = False) -> None:
        """Read the board and publish it, if it says something new.

        A fingerprint rather than a timestamp: the board is polled on a clock,
        but a board that has not moved is not news, and a console that redrew
        itself every fifteen seconds would lose your scroll position for nothing.
        """
        try:
            payload = self.board()
        except Exception as error:  # noqa: BLE001
            self.hub.publish("notice", where="board", message=str(error).splitlines()[0])
            return
        fingerprint = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if not force and fingerprint == self._fingerprint:
            return
        self._fingerprint = fingerprint
        self.hub.publish("board", **payload)

    def _loop(self) -> None:
        next_board = 0.0
        while not self._stop.is_set():
            if self.hub.watchers == 0:
                # Idle rather than dead: a browser reconnecting after a suspend
                # finds the thread already there, and its board one second later.
                if self._stop.wait(2):
                    return
                next_board = 0.0
                continue
            now = time.monotonic()
            asked = self._nudged.is_set()
            if asked or now >= next_board:
                self._nudged.clear()
                next_board = now + self.interval
                self.refresh(force=asked)
            try:
                self.tail.pass_once()
            except Exception as error:  # noqa: BLE001
                self.hub.publish("notice", where="logs", message=str(error).splitlines()[0])
            if self._stop.wait(1):
                return
