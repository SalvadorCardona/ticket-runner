"""A minimal Notion client, standard library only.

No SDK: three HTTP verbs and a handful of conversions are enough, and one less
dependency is one less thing that can break the install.

The client reads **the database schema** before writing anything. That is what
lets you rename a column in Notion, or switch `Status` from a status property to
a select, without touching the code: values are encoded according to the
declared type, and a property that does not exist is skipped silently rather
than failing the ticket.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
MAX_ATTEMPTS = 4


class NotionError(Exception):
    """The API returned an error, or the network is unreachable."""


@dataclass
class Comment:
    text: str
    created_time: str = ""


@dataclass
class Page:
    id: str
    url: str
    title: str
    properties: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class Client:
    def __init__(self, token: str, timeout: int = 30) -> None:
        self._token = token
        self._timeout = timeout
        self._databases: dict[str, dict] = {}

    # -- transport -----------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{API}{path}",
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
        for attempt in range(MAX_ATTEMPTS):
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    return json.loads(response.read() or b"{}")
            except urllib.error.HTTPError as error:
                payload = error.read().decode(errors="replace")
                message = payload
                try:
                    message = json.loads(payload).get("message", payload)
                except json.JSONDecodeError:
                    pass
                last = f"{error.code} {message}"
                # 429: rate limited. 5xx: transient. Anything else is our fault.
                if error.code not in (429, 500, 502, 503, 504):
                    raise NotionError(f"{method} {path}: {last}") from error
            except urllib.error.URLError as error:
                last = str(error.reason)
            except (http.client.HTTPException, ValueError) as error:
                # A malformed path never becomes valid by retrying — most often
                # a configuration value that is not what it claims to be.
                raise NotionError(f"{method} {path}: {error}") from error
            time.sleep(1.5 * (attempt + 1))
        raise NotionError(f"{method} {path}: {last} (gave up after {MAX_ATTEMPTS} attempts)")

    # -- reading -------------------------------------------------------------

    def database(self, database_id: str) -> dict:
        """The raw database object, fetched once per run."""
        if database_id not in self._databases:
            self._databases[database_id] = self._request("GET", f"/databases/{database_id}")
        return self._databases[database_id]

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
                    found.append(Comment(text.strip(), item.get("created_time", "")))
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
        for batch in converter.chunked(blocks):
            if batch:
                self._request("PATCH", f"/blocks/{page_id}/children", {"children": batch})
        return len(blocks)

    def comment(self, page_id: str, text: str) -> None:
        self._request(
            "POST",
            "/comments",
            {"parent": {"page_id": page_id}, "rich_text": _rich_text(text)},
        )

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
        name = next((key for key, kind in schema.items() if kind == "title"), "Name")
        properties: dict[str, Any] = {name: _encode("title", title)}
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


def read(page: Page, name: str) -> Any:
    """A property's value, reduced to a plain Python type."""
    prop = page.properties.get(name)
    if not prop:
        return None
    kind = prop.get("type")
    if kind in ("rich_text", "title"):
        return "".join(part.get("plain_text", "") for part in prop.get(kind, [])).strip()
    if kind == "status":
        return (prop.get("status") or {}).get("name")
    if kind == "select":
        return (prop.get("select") or {}).get("name")
    if kind == "url":
        return prop.get("url")
    if kind == "relation":
        return [item.get("id") for item in prop.get("relation", [])]
    if kind == "people":
        return [item.get("id") for item in prop.get("people", [])]
    if kind == "checkbox":
        return prop.get("checkbox")
    if kind == "number":
        return prop.get("number")
    if kind == "date":
        # A Notion date may be a range. The deadline is where it ends.
        value = prop.get("date") or {}
        return value.get("end") or value.get("start")
    if kind == "formula":
        inner = prop.get("formula") or {}
        return inner.get(inner.get("type", ""), None)
    return prop.get(kind)


def _encode(kind: str | None, value: Any) -> dict | None:
    if kind is None or value is None:
        return None
    if kind == "status":
        return {"status": {"name": str(value)}}
    if kind == "select":
        return {"select": {"name": str(value)}}
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
    return None


def _rich_text(text: str) -> list[dict]:
    """Notion rejects a text block longer than 2000 characters."""
    chunks = [text[index : index + 1900] for index in range(0, len(text), 1900)] or [""]
    return [{"type": "text", "text": {"content": chunk}} for chunk in chunks[:20]]


def _plain(block: dict, kind: str) -> str:
    return "".join(
        part.get("plain_text", "") for part in block.get(kind, {}).get("rich_text", [])
    )


def _block_text(block: dict, depth: int) -> str:
    kind = block.get("type", "")
    if kind == "paragraph":
        return _plain(block, kind)
    if kind in ("heading_1", "heading_2", "heading_3"):
        level = "#" * int(kind[-1])
        return f"{level} {_plain(block, kind)}"
    if kind == "bulleted_list_item":
        return f"- {_plain(block, kind)}"
    if kind == "numbered_list_item":
        return f"1. {_plain(block, kind)}"
    if kind == "to_do":
        done = block.get(kind, {}).get("checked")
        return f"- [{'x' if done else ' '}] {_plain(block, kind)}"
    if kind == "quote":
        return f"> {_plain(block, kind)}"
    if kind == "callout":
        return f"> {_plain(block, kind)}"
    if kind == "toggle":
        return _plain(block, kind)
    if kind == "code":
        language = block.get(kind, {}).get("language", "")
        return f"```{language}\n{_plain(block, kind)}\n```"
    if kind == "divider":
        return "---"
    if kind in ("image", "file", "pdf"):
        payload = block.get(kind, {})
        source = payload.get("external", {}).get("url") or payload.get("file", {}).get("url", "")
        caption = "".join(part.get("plain_text", "") for part in payload.get("caption", []))
        label = caption or kind
        # The S3 URL is signed and expires: it is indicative only.
        return f"[{label} attached to the ticket: {source.split('?')[0]}]"
    if kind == "bookmark":
        return block.get(kind, {}).get("url", "")
    if kind == "child_page":
        return f"[sub-page: {block.get(kind, {}).get('title', '')}]"
    if kind in ("table", "table_row", "column_list", "column"):
        return ""
    return _plain(block, kind)


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())
