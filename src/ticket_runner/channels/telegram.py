"""Telegram: the two-minute channel.

Everything here is a plain HTTPS call to `api.telegram.org`, in both
directions. That is the point: reading your replies costs a GET on
`getUpdates`, so the runner needs no public address, no webhook, no domain and
no reverse proxy — it works from a laptop behind a NAT, which is where a runner
usually lives.

Setting it up is two messages to @BotFather (`/newbot`, take the token) and one
message to your own new bot, which is what `ticket-runner notify --pair` then
reads to find your chat id. There is nothing else: no app to create, no
business account, no review.

One rule worth stating out loud, because it is the security of the whole
channel: **only the configured chat is read.** A bot token is a public address —
anyone who guesses your bot's name can write to it — and a message from any
other chat is dropped before it can become a comment on your board.
"""

from __future__ import annotations

from . import Ask, Channel, ChannelError, Incoming, request

API = "https://api.telegram.org"

# Telegram caps a message at 4096 characters and refuses the whole call past
# that — a long question would arrive as nothing at all.
LIMIT = 3900


class Telegram(Channel):
    name = "telegram"

    def __init__(self, token: str, chat: str) -> None:
        self._token = token
        self._chat = str(chat).strip()

    def _url(self, method: str) -> str:
        return f"{API}/bot{self._token}/{method}"

    def _call(self, method: str, payload: dict) -> dict:
        body = request(self._url(method), payload)
        if not body.get("ok"):
            raise ChannelError(body.get("description", f"{method} refused"))
        return body.get("result") or {}

    # -- outbound ------------------------------------------------------------

    def _post(self, text: str, thread: str = "") -> str:
        payload: dict = {
            "chat_id": self._chat,
            "text": text[:LIMIT],
            "disable_web_page_preview": True,
        }
        if thread:
            # `reply_to_message_id` is what makes the conversation navigable a
            # week later — and what lets an answer name its ticket by itself.
            payload["reply_to_message_id"] = int(thread) if thread.isdigit() else thread
        result = self._call("sendMessage", payload)
        return str(result.get("message_id", ""))

    # -- inbound -------------------------------------------------------------

    def _fetch(self, cursor: str, asks: list[Ask]) -> tuple[list[Incoming], str]:
        """Every message since the last run, and where to resume next time.

        `offset` is Telegram's own acknowledgement: asking for update N + 1 is
        what tells the server we are done with N, and updates are kept for 24
        hours, so a runner that was off overnight still finds yesterday's
        answer. `timeout: 0` because a run is not a daemon — it asks what is
        there and moves on to the tickets.
        """
        payload: dict = {"timeout": 0, "allowed_updates": ["message"]}
        if cursor.isdigit():
            payload["offset"] = int(cursor)
        updates = self._call("getUpdates", payload)
        if not isinstance(updates, list):
            return [], cursor

        incoming: list[Incoming] = []
        highest = int(cursor) - 1 if cursor.isdigit() else -1
        for update in updates:
            highest = max(highest, int(update.get("update_id", 0)))
            message = update.get("message") or {}
            if str((message.get("chat") or {}).get("id", "")) != self._chat:
                continue
            author = message.get("from") or {}
            if author.get("is_bot"):
                continue
            replied = message.get("reply_to_message") or {}
            incoming.append(
                Incoming(
                    ref=str(message.get("message_id", "")),
                    thread=str(replied.get("message_id", "")) if replied else "",
                    text=message.get("text") or message.get("caption") or "",
                    who=author.get("first_name") or author.get("username") or "",
                )
            )
        return incoming, str(highest + 1) if highest >= 0 else cursor


    # -- diagnostics ---------------------------------------------------------

    def check(self) -> str:
        me = self._call("getMe", {})
        chat = self._call("getChat", {"chat_id": self._chat})
        name = chat.get("title") or chat.get("first_name") or chat.get("username") or self._chat
        return f"@{me.get('username', 'bot')} → {name}"


def chats(token: str) -> list[tuple[str, str]]:
    """The (id, name) of everyone who has written to this bot recently.

    What `notify --pair` is: a chat id is not something anybody knows by heart,
    and the usual way of finding it is a third-party bot you paste your token
    into. Saying hello to your own bot and reading it back is strictly better.

    Deliberately does not consume the updates — no `offset` — so that pairing
    twice, or pairing after the runner has already been polling, still sees the
    message.
    """
    body = request(f"{API}/bot{token}/getUpdates", {"timeout": 0})
    if not body.get("ok"):
        raise ChannelError(body.get("description", "getUpdates refused"))
    found: dict[str, str] = {}
    for update in body.get("result") or []:
        chat = (update.get("message") or {}).get("chat") or {}
        identifier = str(chat.get("id", ""))
        if not identifier:
            continue
        name = chat.get("title") or " ".join(
            part for part in (chat.get("first_name"), chat.get("last_name")) if part
        ) or chat.get("username") or "chat"
        found[identifier] = name
    return sorted(found.items())
