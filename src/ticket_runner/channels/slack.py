"""Slack: the same conversation, where the team already is.

Read by polling, like Telegram, and for the same reason: `conversations.history`
is a GET. Slack's other two ways in — the Events API and Socket Mode — want a
public HTTPS endpoint or a websocket held open by a daemon, and a runner that
wakes every thirty minutes has neither. Polling costs one call per run, two
when a question is outstanding.

A question is posted to the channel, and its **thread** is where the answer is
expected: that is how two tickets can be waiting at once without their answers
being confused. A message typed in the channel itself still counts — it answers
the last question asked — because that is what people do.

The bot needs `chat:write` to speak, and the history scope matching where you
put it: `channels:history` for a public channel, `groups:history` for a private
one, `im:history` for a direct message. And it has to be *in* the channel:
`/invite @your-bot`, which is the step everyone forgets.
"""

from __future__ import annotations

import urllib.parse

from . import Ask, Channel, ChannelError, Incoming, request

API = "https://slack.com/api"

# Slack renders anything longer as a file, which nobody opens on a phone.
LIMIT = 3000

HINTS = {
    "not_in_channel": "the bot is not in that channel — /invite @your-bot",
    "channel_not_found": "no such channel id, or the bot cannot see it",
    "missing_scope": "the token lacks a scope — chat:write, and channels:history to read replies",
    "invalid_auth": "the bot token was refused — it starts with xoxb-",
}


class Slack(Channel):
    name = "slack"
    # A channel has other conversations in it, and a colleague's "ok" is not an
    # approval of anything. The thread of the question is what makes an answer
    # an answer here — or the ticket, named in the message.
    fallback = False

    def __init__(self, token: str, channel: str) -> None:
        self._token = token
        self._channel = str(channel).strip()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _call(self, method: str, payload: dict | None = None, **query: str) -> dict:
        url = f"{API}/{method}"
        if query:
            url = f"{url}?{urllib.parse.urlencode({k: v for k, v in query.items() if v})}"
        body = request(url, payload, headers=self._headers())
        if not body.get("ok"):
            code = str(body.get("error", "refused"))
            hint = HINTS.get(code, "")
            raise ChannelError(f"{code}{f' — {hint}' if hint else ''}")
        return body

    # -- outbound ------------------------------------------------------------

    def _thread_of(self, reply) -> str:
        """A thread is counted from its first message, not from the last one."""
        return reply.thread or reply.ref

    def _post(self, text: str, thread: str = "") -> str:
        payload: dict = {"channel": self._channel, "text": text[:LIMIT], "unfurl_links": False}
        if thread:
            payload["thread_ts"] = thread
        body = self._call("chat.postMessage", payload)
        return str(body.get("ts", ""))

    # -- inbound -------------------------------------------------------------

    def _fetch(self, cursor: str, asks: list[Ask]) -> tuple[list[Incoming], str]:
        """What was said in the channel, and under the questions still open.

        Two shapes, because Slack has two: a message in the channel appears in
        `conversations.history`, a message in a thread does not — it only shows
        up under its parent. So the history is read once, then the replies of
        each question we are still waiting on. Bounded by the questions the
        channel remembers, which is why that list is short.

        A Slack timestamp sorts like a number, so the newest one seen is the
        cursor for both calls at once.
        """
        latest = cursor
        incoming: list[Incoming] = []

        for message in self._call(
            "conversations.history", channel=self._channel, oldest=cursor, limit="50"
        ).get("messages", []):
            found = self._read(message, cursor)
            if found:
                incoming.append(found)
                latest = max(latest, found.ref)

        for ask in asks:
            if not ask.ref:
                continue
            try:
                replies = self._call(
                    "conversations.replies",
                    channel=self._channel,
                    ts=ask.ref,
                    oldest=cursor,
                    limit="50",
                ).get("messages", [])
            except ChannelError:
                # A thread whose parent was deleted is not a reason to lose the
                # rest of the run's answers.
                continue
            for message in replies:
                found = self._read(message, cursor)
                if not found or found.ref == ask.ref:
                    continue
                found.thread = ask.ref
                incoming.append(found)
                latest = max(latest, found.ref)

        incoming.sort(key=lambda message: message.ref)
        return incoming, latest

    def _read(self, message: dict, cursor: str) -> Incoming | None:
        """One raw Slack message, or None when it is not somebody talking.

        Our own posts carry a `bot_id`, and joins, pins and file comments carry
        a `subtype`: neither is an answer, and a bot reading its own messages
        back is how a loop starts.
        """
        if message.get("bot_id") or message.get("subtype") or not message.get("user"):
            return None
        stamp = str(message.get("ts", ""))
        if not stamp or (cursor and stamp <= cursor):
            return None
        thread = str(message.get("thread_ts", ""))
        return Incoming(
            ref=stamp,
            thread=thread if thread and thread != stamp else "",
            text=message.get("text") or "",
            who="",
        )

    # -- diagnostics ---------------------------------------------------------

    def check(self) -> str:
        me = self._call("auth.test")
        channel = self._call("conversations.info", channel=self._channel).get("channel", {})
        name = channel.get("name") or self._channel
        if channel.get("is_channel") and not channel.get("is_member"):
            raise ChannelError(f"not in #{name} — /invite @{me.get('user', 'your-bot')}")
        return f"{me.get('user', 'bot')} on {me.get('team', 'your workspace')} → #{name}"
