"""Client Notion minimal, sur la bibliothèque standard uniquement.

Pas de SDK : trois verbes HTTP et une poignée de conversions suffisent, et une
dépendance de moins est une dépendance qui ne casse pas l'installation.

Le client lit **le schéma de la base** avant d'écrire quoi que ce soit. C'est ce
qui permet de renommer une colonne dans Notion, ou de passer un `Status` de type
« statut » à un type « sélection », sans toucher au code : la valeur est
encodée selon le type déclaré, et une propriété absente est ignorée en silence
plutôt que de faire échouer le ticket.
"""

from __future__ import annotations

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
    """Erreur renvoyée par l'API, ou réseau indisponible."""


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
        self._schemas: dict[str, dict[str, str]] = {}

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
                # 429 : quota. 5xx : panne passagère. Le reste est notre faute.
                if error.code not in (429, 500, 502, 503, 504):
                    raise NotionError(f"{method} {path} : {last}") from error
            except urllib.error.URLError as error:
                last = str(error.reason)
            time.sleep(1.5 * (attempt + 1))
        raise NotionError(f"{method} {path} : {last} (abandon après {MAX_ATTEMPTS} essais)")

    # -- lecture -------------------------------------------------------------

    def schema(self, database_id: str) -> dict[str, str]:
        """{nom de propriété: type}, mis en cache pour la durée du run."""
        if database_id not in self._schemas:
            database = self._request("GET", f"/databases/{database_id}")
            self._schemas[database_id] = {
                name: prop.get("type", "")
                for name, prop in database.get("properties", {}).items()
            }
        return self._schemas[database_id]

    def resolve_database(self, identifier: str) -> str:
        """L'ID d'une base, à partir de la base ou de la page qui la contient.

        Copier l'URL d'une page Notion est le geste naturel ; mais une base
        « inline » vit *dans* une page et porte un autre identifiant, et l'API
        répond alors « object not found » sans dire pourquoi. On regarde donc
        les blocs de la page, et on prend la base qu'on y trouve.
        """
        try:
            self.schema(identifier)
            return identifier
        except NotionError:
            pass
        try:
            payload = self._request("GET", f"/blocks/{identifier}/children?page_size=100")
        except NotionError as error:
            raise NotionError(
                f"ni base ni page accessible pour {identifier} : {error}\n"
                "  la base doit être partagée avec l'intégration (menu ··· → Connexions)"
            ) from error
        for block in payload.get("results", []):
            if block.get("type") == "child_database":
                return block["id"].replace("-", "")
        raise NotionError(
            f"{identifier} est une page sans base de données — "
            "donnez l'URL de la base elle-même (··· → Copier le lien de la vue)"
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

    def blocks_text(self, block_id: str, depth: int = 0) -> str:
        """Le contenu d'une page, aplati en texte lisible par un agent."""
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

    # -- écriture ------------------------------------------------------------

    def update(self, database_id: str, page_id: str, values: dict[str, Any]) -> None:
        """Écrit des propriétés par nom ; celles absentes du schéma sont ignorées."""
        schema = self.schema(database_id)
        properties: dict[str, Any] = {}
        for name, value in values.items():
            kind = schema.get(name)
            encoded = _encode(kind, value)
            if encoded is not None:
                properties[name] = encoded
        if properties:
            self._request("PATCH", f"/pages/{page_id}", {"properties": properties})

    def comment(self, page_id: str, text: str) -> None:
        self._request(
            "POST",
            "/comments",
            {"parent": {"page_id": page_id}, "rich_text": _rich_text(text)},
        )


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
    """Valeur d'une propriété, ramenée à un type Python simple."""
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
    return None


def _rich_text(text: str) -> list[dict]:
    """Notion refuse un bloc de texte au-delà de 2000 caractères."""
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
        # L'URL S3 est signée et expire : elle n'est utile qu'à titre indicatif.
        return f"[{label} joint au ticket : {source.split('?')[0]}]"
    if kind == "bookmark":
        return block.get(kind, {}).get("url", "")
    if kind == "child_page":
        return f"[sous-page : {block.get(kind, {}).get('title', '')}]"
    if kind in ("table", "table_row", "column_list", "column"):
        return ""
    return _plain(block, kind)


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())
