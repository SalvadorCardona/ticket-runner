"""A minimal Notion client, standard library only.

No SDK: three HTTP verbs and a handful of conversions are enough, and one less
dependency is one less thing that can break the install.

The client reads **the database schema** before writing anything. That is what
lets you rename a column in Notion, or switch `Status` from a status property to
a select, without touching the code: values are encoded according to the
declared type, and a property that does not exist is skipped silently rather
than failing the ticket.

It is one implementation of `store.Store`, and the one everything was written
against — `Page`, `Comment` and `read` are that module's now, re-exported here
because a Notion page is still what they were shaped after.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .config import PLACEHOLDER
from .store import Comment, Page, StoreError, read

API = "https://api.notion.com/v1"
# The one seam in this file, and it exists for `tests/functional.py`: the
# functional suite stands a Notion of its own on a local port and runs a whole
# ticket against it. Read at each request rather than at import, so that the
# tests can point the runner somewhere else once the modules are loaded — and
# unset everywhere else, which is every installation.
API_ENV = "TICKET_RUNNER_NOTION_API"
VERSION = "2022-06-28"
MAX_ATTEMPTS = 4

# Re-exported so that `notion.Page`, `notion.Comment` and `notion.read` keep
# meaning what they always meant.
__all__ = ["API", "Client", "Comment", "NotionError", "Page", "VERSION", "read"]


def endpoint() -> str:
    """Where the API lives: Notion's, unless `TICKET_RUNNER_NOTION_API` says."""
    return os.environ.get(API_ENV, "").strip().rstrip("/") or API


# Past this, a Retry-After is not a pause, it is Notion saying "not today": the
# run moves on and the next one asks again.
LONGEST_WAIT = 60


def _replayable(method: str, path: str) -> bool:
    """May this request be sent again after it may already have been carried out?

    A read, yes, and the two reads Notion spells as a POST — a database query and
    a search. A write that sets a value, too: setting it twice is setting it
    once. What *adds* something — a page, a comment, blocks appended to a page —
    is not: the second copy is a duplicate somebody has to delete by hand.
    """
    if method in ("GET", "DELETE"):
        return True
    if method == "POST":
        return path.endswith("/query") or path == "/search"
    if method == "PATCH":
        return not path.endswith("/children")
    return False


def _retry_after(error: urllib.error.HTTPError) -> float:
    """What a 429 asks us to wait, in seconds — bounded, and 0 when unsaid."""
    try:
        return min(float(error.headers.get("Retry-After", "") or 0), LONGEST_WAIT)
    except (TypeError, ValueError, AttributeError):
        return 0.0


class NotionError(StoreError):
    """The API returned an error, or the network is unreachable."""


class Client:
    def __init__(self, token: str, timeout: int = 30) -> None:
        self._token = token
        self._timeout = timeout
        self._databases: dict[str, dict] = {}
        self._me: dict | None = None

    # -- transport -----------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        if not self._token.strip() or self._token.strip() == PLACEHOLDER:
            # A fresh installation: the console runs before anybody has typed a
            # token, and asks for the board every few seconds while a browser
            # is open. Sending the example's placeholder to Notion would only
            # buy a 401 — or a timeout — per poll, to say what is known here.
            raise NotionError(
                "no Notion token yet — the console's first connection, "
                "or `ticket-runner init`, sets it"
            )
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{endpoint()}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Notion-Version": VERSION,
                "Content-Type": "application/json",
                "User-Agent": "ticket-runner",
            },
        )
        last = ""
        replayable = _replayable(method, path)
        for attempt in range(MAX_ATTEMPTS):
            wait = 1.5 * (attempt + 1)
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    return json.loads(response.read() or b"{}")
            except urllib.error.HTTPError as error:
                # First: an HTTPError is a URLError, which is an OSError.
                try:
                    payload = error.read().decode(errors="replace")
                except OSError:
                    payload = ""  # the status says enough; its body timed out
                message = payload
                try:
                    message = json.loads(payload).get("message", payload)
                except json.JSONDecodeError:
                    pass
                last = f"{error.code} {message}"
                if error.code == 429:
                    # Refused before anything was done, whatever the method:
                    # always worth the wait Notion asks for.
                    wait = max(wait, _retry_after(error))
                elif error.code in (500, 502, 503, 504) and replayable:
                    pass
                else:
                    # Anything else is our fault — or a 5xx on a write, which
                    # Notion may have carried out before failing to say so.
                    raise NotionError(f"{method} {path}: {last}") from error
            except urllib.error.URLError as error:
                # Raised while connecting or sending: the request never reached
                # Notion whole, so even a comment is safe to send again.
                last = str(error.reason)
            except (ValueError, http.client.InvalidURL) as error:
                # A malformed path never becomes valid by retrying — most often
                # a configuration value that is not what it claims to be. And
                # an answer that is not JSON is not going to become JSON either.
                raise NotionError(f"{method} {path}: {error}") from error
            except (OSError, http.client.HTTPException) as error:
                # Raised while *reading* the answer — a timeout, a reset, a
                # connection closed halfway. The request may have been carried
                # out, and a second comment is worse than an error.
                last = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
                if not replayable:
                    raise NotionError(
                        f"{method} {path}: {last} — not retried, it may have been applied"
                    ) from error
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(wait)
        raise NotionError(f"{method} {path}: {last} (gave up after {MAX_ATTEMPTS} attempts)")

    # -- reading -------------------------------------------------------------

    def database(self, database_id: str) -> dict:
        """The raw database object, fetched once per run."""
        if database_id not in self._databases:
            self._databases[database_id] = self._request("GET", f"/databases/{database_id}")
        return self._databases[database_id]

    def forget_database(self, database_id: str) -> None:
        """Drop the cached database, so the next read asks Notion again.

        A run is short and reads the board's shape once. The console is not: it
        outlives any number of runs, and a column added in Notion this morning
        has to reach it before tomorrow.
        """
        self._databases.pop(database_id, None)

    def schema(self, database_id: str) -> dict[str, str]:
        """{property name: type}, cached for the lifetime of the run."""
        return {
            name: prop.get("type", "")
            for name, prop in self.database(database_id).get("properties", {}).items()
        }

    def options(self, database_id: str, name: str) -> list[str]:
        """The values a status or select property accepts, in Notion's order.

        A status the configuration names but the database does not offer is
        rejected at the end of a ticket, when the runner tries to write it —
        which is the worst possible moment to discover a typo. `doctor` uses
        this to catch it beforehand.
        """
        prop = self.database(database_id).get("properties", {}).get(name, {})
        kind = prop.get("type", "")
        return [option.get("name", "") for option in prop.get(kind, {}).get("options", [])]

    def title_property(self, database_id: str) -> str:
        """The name of the title column, whatever the database calls it.

        Every database has exactly one, and Notion lets you rename it — `Name`,
        `Titre`, `Ticket`. Writing a page's own name means finding it first.
        """
        schema = self.schema(database_id)
        return next((name for name, kind in schema.items() if kind == "title"), "Name")

    def find_database(self, name: str) -> str:
        """The ID of the database whose title matches `name`.

        Writing the database's name in the configuration is a reasonable thing
        to do, so it works: the search endpoint only ever sees what the
        integration was given access to, which makes an exact match reliable.
        """
        payload = self._request(
            "POST",
            "/search",
            {"query": name, "filter": {"value": "database", "property": "object"}},
        )
        candidates = []
        for item in payload.get("results", []):
            title = "".join(part.get("plain_text", "") for part in item.get("title", []))
            candidates.append((title.strip(), item.get("id", "").replace("-", "")))
        for title, identifier in candidates:
            if title.lower() == name.strip().lower():
                return identifier
        if len(candidates) == 1:
            return candidates[0][1]
        if not candidates:
            raise NotionError(
                f"no database named “{name}” is shared with this integration\n"
                "  share it: the database's ··· menu → Connections → your integration"
            )
        names = ", ".join(f"“{title}”" for title, _ in candidates[:5])
        raise NotionError(f"several databases match “{name}”: {names} — use its URL instead")

    def resolve_database(self, identifier: str) -> str:
        """A database ID, from an ID, the page holding it, or its name.

        Copying a Notion page URL is the natural gesture, but an inline database
        lives *inside* a page and carries a different ID — and the API then
        answers "object not found" without saying why. So we look at the page's
        blocks and take the database we find there. And a value that is not an
        identifier at all is taken for a name and searched.
        """
        from .config import is_identifier

        if not is_identifier(identifier):
            return self.find_database(identifier)
        try:
            self.schema(identifier)
            return identifier
        except NotionError:
            pass
        try:
            payload = self._request("GET", f"/blocks/{identifier}/children?page_size=100")
        except NotionError as error:
            raise NotionError(
                f"neither a database nor a readable page for {identifier}: {error}\n"
                "  the database must be shared with the integration (··· menu → Connections)"
            ) from error
        for block in payload.get("results", []):
            if block.get("type") == "child_database":
                return block["id"].replace("-", "")
        raise NotionError(
            f"{identifier} is a page with no database in it — "
            "give the URL of the database itself (··· → Copy link to view)"
        )

    def query(self, database_id: str, filter_: dict | None = None) -> list[Page]:
        pages: list[Page] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if filter_:
                body["filter"] = filter_
            if cursor:
                body["start_cursor"] = cursor
            payload = self._request("POST", f"/databases/{database_id}/query", body)
            pages.extend(_to_page(item) for item in payload.get("results", []))
            if not payload.get("has_more"):
                return pages
            cursor = payload.get("next_cursor")

    def page(self, page_id: str) -> Page:
        return _to_page(self._request("GET", f"/pages/{page_id}"))

    def comments(self, page_id: str) -> list[Comment]:
        """The discussion on a page, oldest first.

        This is where a ticket gets answered. A run that ends `blocked` leaves
        its question here, you reply, and the ticket goes back to ready — so
        without reading this, the next run reopens the very question it asked.

        Reading comments is a separate capability of a Notion integration, and
        one that is off by default. A refusal is not a reason to fail a ticket:
        it comes back as no comments, and the caller says so.
        """
        found: list[Comment] = []
        cursor: str | None = None
        while True:
            suffix = f"&start_cursor={cursor}" if cursor else ""
            payload = self._request("GET", f"/comments?block_id={page_id}&page_size=100{suffix}")
            for item in payload.get("results", []):
                text = "".join(part.get("plain_text", "") for part in item.get("rich_text", []))
                if text.strip():
                    found.append(
                        Comment(
                            text.strip(),
                            item.get("created_time", ""),
                            id=item.get("id", ""),
                            discussion_id=item.get("discussion_id", ""),
                            created_by=(item.get("created_by") or {}).get("id", ""),
                        )
                    )
            if not payload.get("has_more"):
                return found
            cursor = payload.get("next_cursor")

    def blocks_text(self, block_id: str, depth: int = 0) -> str:
        """A page's content, flattened into something an agent can read."""
        if depth > 3:
            return ""
        lines: list[str] = []
        cursor: str | None = None
        while True:
            suffix = f"?page_size=100&start_cursor={cursor}" if cursor else "?page_size=100"
            payload = self._request("GET", f"/blocks/{block_id}/children{suffix}")
            for block in payload.get("results", []):
                lines.append(_block_text(block, depth))
                if block.get("has_children") and block.get("type") != "child_page":
                    nested = self.blocks_text(block["id"], depth + 1)
                    if nested:
                        lines.append(_indent(nested))
            if not payload.get("has_more"):
                break
            cursor = payload.get("next_cursor")
        return "\n".join(line for line in lines if line is not None).strip()

    # -- writing -------------------------------------------------------------

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        """Write properties by name; those absent from the schema are ignored.

        The schema is cached for the run, and a run can last half an hour — long
        enough for someone to change a column's type in Notion meanwhile. Values
        are then encoded for a type the database no longer has, and Notion
        answers `400 X is expected to be url`. So a rejection on those grounds
        refreshes the schema and tries once more, rather than losing the write.
        """
        def encode(schema: dict[str, str]) -> dict[str, Any]:
            properties: dict[str, Any] = {}
            for name, value in values.items():
                encoded = _encode(schema.get(name), value)
                if encoded is not None:
                    properties[name] = encoded
            return properties

        properties = encode(self.schema(database_id))
        if not properties:
            return
        try:
            self._request("PATCH", f"/pages/{page_id}", {"properties": properties})
        except NotionError as error:
            if "expected to be" not in str(error):
                raise
            self._databases.pop(database_id, None)
            retry = encode(self.schema(database_id))
            if retry:
                self._request("PATCH", f"/pages/{page_id}", {"properties": retry})

    def append_markdown(self, page_id: str, markdown: str) -> int:
        """Append markdown to a page, as real Notion blocks. Returns the count.

        Appending, never replacing: the ticket's own description is what the
        agent was asked to work from, and destroying it to make room for the
        answer would be a poor trade.
        """
        from . import markdown as converter

        blocks = converter.to_blocks(markdown)
        self.append_blocks(page_id, blocks)
        return len(blocks)

    def replace_markdown(self, page_id: str, markdown: str) -> int:
        """Make a page say this and nothing else. Returns the block count.

        The one destructive write in this client, and it exists for the two
        places where a page is *a value* rather than a history: the standing
        context, which the console edits as a text area, and a page the Markdown
        side of a mirrored board has just won a conflict over. Appending there
        would grow a second copy under the first every time either is saved.

        Everything that is not those two appends — a report, an answer, a
        ticket's body — because a ticket's own description is what the agent was
        asked to work from, and destroying it to make room would be a poor trade.
        """
        self.delete_children(page_id)
        return self.append_markdown(page_id, markdown)

    def delete_children(self, block_id: str) -> int:
        """Empty a page, block by block, and say how many went.

        Notion has no "delete the contents of this page": archiving a block is
        one request each, and there is no batch. A hundred at a time is what
        `children` hands over, and the loop asks again until it hands over none.
        """
        gone = 0
        while True:
            payload = self._request("GET", f"/blocks/{block_id}/children?page_size=100")
            blocks = payload.get("results", [])
            if not blocks:
                return gone
            for block in blocks:
                self._request("DELETE", f"/blocks/{block['id']}")
                gone += 1
            if not payload.get("has_more"):
                return gone

    def append_blocks(self, block_id: str, blocks: list[dict]) -> list[str]:
        """Append blocks under a page *or* under a block, and return their IDs.

        Notion takes a hundred at a time, hence the batching; and it answers
        with what it created, which is how the live report gets hold of the
        toggle it will then keep filling.
        """
        from . import markdown as converter

        created: list[str] = []
        for batch in converter.chunked(blocks):
            if not batch:
                continue
            payload = self._request(
                "PATCH", f"/blocks/{block_id}/children", {"children": batch}
            )
            created += [item.get("id", "") for item in payload.get("results", [])]
        return created

    def update_block(self, block_id: str, payload: dict) -> None:
        """Rewrite a block in place — its text, not its type.

        Used by the live report to keep a toggle's title current: the count and
        the elapsed time belong on the line you see when it is collapsed.
        """
        self._request("PATCH", f"/blocks/{block_id}", payload)

    def comment(self, page_id: str, text: str, discussion_id: str = "") -> None:
        """Say something on a page — or *into* one of its threads.

        A report opens its own discussion, because it is the runner speaking
        first. An answer to a question belongs under the question: given a
        discussion, Notion threads it there, and the page keeps reading as a
        conversation instead of as a stack of monologues.
        """
        body: dict[str, Any] = {"rich_text": _rich_text(text)}
        if discussion_id:
            body["discussion_id"] = discussion_id
        else:
            body["parent"] = {"page_id": page_id}
        self._request("POST", "/comments", body)

    def me(self) -> str:
        """The integration's own user ID, fetched once.

        Everything the runner says in the comments comes back to it on the next
        pass. Recognising its own voice by the signature it writes would work
        until the day it writes something else — so it asks Notion who it is,
        and compares identifiers. Answering a comment is gated on this: without
        it, the runner cannot prove a comment is not its own, and a conversation
        with itself is the one failure mode that never stops.
        """
        return self._identity().get("id", "")

    def my_name(self) -> str:
        """The name the integration answers to, as Notion shows it.

        Mentioning it in a comment is the natural way to address it, and a
        mention reaches the API as the name in plain text — so knowing the name
        is what makes “@Ticket Runner, pourquoi ?” a message rather than a
        remark about the weather.
        """
        return str(self._identity().get("name", "")).strip()

    def workspace(self, settings):
        """The databases and the standing context of this board. See workspace.py.

        Part of the store interface rather than of `workspace.resolve`, because
        "what is this board made of" is the one question each backend answers in
        its own terms: a Notion workspace is a directory database whose rows
        hold inline databases, and a Markdown board is four directories.

        Imported here rather than at the top: `workspace` reads pages through
        this very client, and the two modules would otherwise import each other.
        """
        from . import workspace as workspace_module

        return workspace_module.from_notion(self, settings)

    def _identity(self) -> dict:
        """Who Notion says we are. Cached on success only, so a network blip
        that hid our identity for one run does not hide it for the next."""
        if self._me is None:
            self._me = self._request("GET", "/users/me")
        return self._me

    # -- writing the shape, not the content ----------------------------------

    def child_databases(self, page_id: str) -> dict[str, str]:
        """{title: database id} for the databases living inside a page.

        `resolve_database` already walks these blocks to find *the* database of
        a page; provisioning needs to know whether the one it is about to
        create is already there, and under which title.
        """
        payload = self._request("GET", f"/blocks/{page_id}/children?page_size=100")
        found: dict[str, str] = {}
        for block in payload.get("results", []):
            if block.get("type") != "child_database":
                continue
            title = (block.get("child_database") or {}).get("title", "").strip()
            found.setdefault(title, block["id"].replace("-", ""))
        return found

    def create_database(
        self, parent_page_id: str, title: str, properties: dict, *, inline: bool = True
    ) -> str:
        """Create a database inside a page and return its ID.

        Inline by default, because that is the shape the workspace is read as:
        a row of the directory is a page, and the database it holds lives in it.
        """
        payload = self._request(
            "POST",
            "/databases",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": _rich_text(title),
                "is_inline": inline,
                "properties": properties,
            },
        )
        return payload.get("id", "").replace("-", "")

    def add_properties(self, database_id: str, properties: dict) -> None:
        """Add or widen properties on an existing database.

        Only ever called with what is missing: a column somebody retyped on
        purpose is theirs, and provisioning has no business overruling it.
        """
        if not properties:
            return
        self._request("PATCH", f"/databases/{database_id}", {"properties": properties})
        self._databases.pop(database_id, None)  # the cached schema just aged

    def create_row(self, database_id: str, title: str, values: dict | None = None) -> str:
        """Create a page in a database, titled, and return its ID."""
        schema = self.schema(database_id)
        properties: dict[str, Any] = {
            self.title_property(database_id): _encode("title", title)
        }
        for key, value in (values or {}).items():
            encoded = _encode(schema.get(key), value)
            if encoded is not None:
                properties[key] = encoded
        payload = self._request(
            "POST",
            "/pages",
            {"parent": {"type": "database_id", "database_id": database_id}, "properties": properties},
        )
        return payload.get("id", "").replace("-", "")

    def create_child_page(self, parent_page_id: str, title: str) -> str:
        """Create a plain page inside a page, and return its ID."""
        payload = self._request(
            "POST",
            "/pages",
            {
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "properties": {"title": {"title": _rich_text(title)}},
            },
        )
        return payload.get("id", "").replace("-", "")



# -- conversions -------------------------------------------------------------


def _to_page(raw: dict) -> Page:
    properties = raw.get("properties", {})
    title = ""
    for prop in properties.values():
        if prop.get("type") == "title":
            title = "".join(part.get("plain_text", "") for part in prop.get("title", []))
            break
    return Page(
        id=raw.get("id", ""),
        url=raw.get("url", ""),
        title=title.strip(),
        properties=properties,
        raw=raw,
    )


def _encode(kind: str | None, value: Any) -> dict | None:
    if kind is None or value is None:
        return None
    if kind == "status":
        return {"status": {"name": str(value)}}
    if kind == "select":
        # An empty name is not an option, and Notion answers 400 to one. What
        # emptying a select means is clearing the cell, and `null` is how that
        # is said — which is what the console's "nothing said" sends.
        return {"select": {"name": str(value)} if str(value) else None}
    if kind == "url":
        return {"url": str(value) or None}
    if kind in ("rich_text", "title"):
        return {kind: _rich_text(str(value))}
    if kind == "checkbox":
        return {"checkbox": bool(value)}
    if kind == "number":
        return {"number": value}
    if kind == "date":
        return {"date": {"start": str(value)}}
    if kind == "relation":
        # A relation is written as a list of page IDs, and accepts one on its
        # own: a ticket created from the console names its project, and naming
        # it is the whole difference between code work and document work.
        ids = value if isinstance(value, (list, tuple)) else [value]
        return {"relation": [{"id": str(one)} for one in ids if one]}
    return None


def _rich_text(text: str) -> list[dict]:
    """Notion rejects a text block longer than 2000 characters."""
    chunks = [text[index : index + 1900] for index in range(0, len(text), 1900)] or [""]
    return [{"type": "text", "text": {"content": chunk}} for chunk in chunks[:20]]


def _block_text(block: dict, depth: int) -> str:
    """One block as text. See `markdown.plain`, where the conversion lives."""
    from . import markdown as converter

    return converter.plain(block)


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())
