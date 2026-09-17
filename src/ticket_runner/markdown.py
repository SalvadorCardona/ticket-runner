"""Markdown, turned into Notion blocks.

Only what an agent actually writes in a plan: headings, lists, checkboxes,
quotes, code fences, dividers, paragraphs, and inline bold, italic, code and
links. Nested lists are flattened — a plan reads perfectly well flat, and one
level of children would double the size of this file for very little.

Anything unrecognised falls through as a paragraph, which is the right failure:
the text always reaches the page, at worst without its formatting.
"""

from __future__ import annotations

import re

# Notion rejects a code block whose language it does not know.
LANGUAGES = {
    "bash", "c", "c++", "c#", "css", "diff", "docker", "go", "graphql", "html",
    "java", "javascript", "json", "kotlin", "makefile", "markdown", "php",
    "python", "ruby", "rust", "shell", "sql", "swift", "toml", "typescript",
    "xml", "yaml",
}
ALIASES = {"sh": "shell", "js": "javascript", "ts": "typescript", "py": "python", "yml": "yaml"}

INLINE = re.compile(
    r"\*\*(?P<bold>.+?)\*\*"
    r"|`(?P<code>[^`]+)`"
    r"|\[(?P<label>[^\]]+)\]\((?P<url>[^)\s]+)\)"
    r"|(?<!\*)\*(?P<italic>[^*]+)\*(?!\*)"
)
MAX_CONTENT = 1900
MAX_BLOCKS = 100


def _text(content: str, *, bold=False, italic=False, code=False, url="") -> dict:
    item: dict = {"type": "text", "text": {"content": content[:MAX_CONTENT]}}
    if url:
        item["text"]["link"] = {"url": url}
    annotations = {"bold": bold, "italic": italic, "code": code}
    if any(annotations.values()):
        item["annotations"] = annotations
    return item


def inline(line: str) -> list[dict]:
    """A line of markdown, as Notion rich text."""
    parts: list[dict] = []
    position = 0
    for match in INLINE.finditer(line):
        if match.start() > position:
            parts.append(_text(line[position : match.start()]))
        if match.group("bold"):
            parts.append(_text(match.group("bold"), bold=True))
        elif match.group("code"):
            parts.append(_text(match.group("code"), code=True))
        elif match.group("label"):
            parts.append(_text(match.group("label"), url=match.group("url")))
        elif match.group("italic"):
            parts.append(_text(match.group("italic"), italic=True))
        position = match.end()
    if position < len(line):
        parts.append(_text(line[position:]))
    return parts or [_text("")]


def _block(kind: str, payload: dict) -> dict:
    return {"object": "block", "type": kind, kind: payload}


def to_blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = []
    lines = markdown.replace("\r\n", "\n").split("\n")
    index = 0
    while index < len(lines):
        raw = lines[index]
        line = raw.strip()
        index += 1

        if not line:
            continue

        if line.startswith("```"):
            language = ALIASES.get(line[3:].strip().lower(), line[3:].strip().lower())
            body: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                body.append(lines[index])
                index += 1
            index += 1  # the closing fence
            blocks.append(
                _block(
                    "code",
                    {
                        "rich_text": [_text("\n".join(body))],
                        "language": language if language in LANGUAGES else "plain text",
                    },
                )
            )
            continue

        if set(line) <= {"-", "*", "_"} and len(line) >= 3:
            blocks.append(_block("divider", {}))
            continue

        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            blocks.append(_block(f"heading_{level}", {"rich_text": inline(heading.group(2))}))
            continue

        todo = re.match(r"^[-*+]\s+\[([ xX])\]\s+(.*)$", line)
        if todo:
            blocks.append(
                _block(
                    "to_do",
                    {"rich_text": inline(todo.group(2)), "checked": todo.group(1).lower() == "x"},
                )
            )
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", line)
        if bullet:
            blocks.append(_block("bulleted_list_item", {"rich_text": inline(bullet.group(1))}))
            continue

        numbered = re.match(r"^\d+[.)]\s+(.*)$", line)
        if numbered:
            blocks.append(_block("numbered_list_item", {"rich_text": inline(numbered.group(1))}))
            continue

        if line.startswith("> "):
            blocks.append(_block("quote", {"rich_text": inline(line[2:])}))
            continue

        # A table would need its own block type and a fixed column count; as a
        # paragraph the row still reads, pipes and all.
        blocks.append(_block("paragraph", {"rich_text": inline(line)}))

    return blocks


def chunked(blocks: list[dict], size: int = MAX_BLOCKS) -> list[list[dict]]:
    """Notion accepts at most 100 blocks per append."""
    return [blocks[index : index + size] for index in range(0, len(blocks), size)] or [[]]


# -- and back again ----------------------------------------------------------


def _rich(block: dict, kind: str) -> str:
    """The text of one block, whichever end of the wire it came from.

    Notion hands a piece of rich text back with `plain_text` on it; a block this
    module has just *built* carries `text.content` instead. Reading both is what
    lets `plain` serve the two callers it has — flattening a page the API
    returned, and writing down blocks the live report made.
    """
    return "".join(
        part.get("plain_text") or (part.get("text") or {}).get("content", "")
        for part in block.get(kind, {}).get("rich_text", [])
    )


def plain(block: dict) -> str:
    """One Notion block, as the markdown line it came from.

    The return journey, and it lives here rather than in the client because a
    block is the shape a *page* is made of, not a shape the HTTP layer invented:
    the Notion client flattens a page with it, and a board made of files writes
    the live report's blocks down with it.

    Lossy where Notion is richer than a line of text — a toggle keeps its title
    and loses its fold, a table comes back empty — and that is the trade the
    whole conversion is: the text always reaches the reader, at worst without
    its furniture.
    """
    kind = block.get("type", "")
    if kind == "paragraph":
        return _rich(block, kind)
    if kind in ("heading_1", "heading_2", "heading_3"):
        return f"{'#' * int(kind[-1])} {_rich(block, kind)}"
    if kind == "bulleted_list_item":
        return f"- {_rich(block, kind)}"
    if kind == "numbered_list_item":
        return f"1. {_rich(block, kind)}"
    if kind == "to_do":
        done = block.get(kind, {}).get("checked")
        return f"- [{'x' if done else ' '}] {_rich(block, kind)}"
    if kind in ("quote", "callout"):
        return f"> {_rich(block, kind)}"
    if kind == "toggle":
        return _rich(block, kind)
    if kind == "code":
        language = block.get(kind, {}).get("language", "")
        return f"```{language}\n{_rich(block, kind)}\n```"
    if kind == "divider":
        return "---"
    if kind in ("image", "file", "pdf"):
        payload = block.get(kind, {})
        source = payload.get("external", {}).get("url") or payload.get("file", {}).get("url", "")
        caption = "".join(part.get("plain_text", "") for part in payload.get("caption", []))
        # The S3 URL is signed and expires: it is indicative only.
        return f"[{caption or kind} attached to the ticket: {source.split('?')[0]}]"
    if kind == "bookmark":
        return block.get(kind, {}).get("url", "")
    if kind == "child_page":
        return f"[sub-page: {block.get(kind, {}).get('title', '')}]"
    if kind in ("table", "table_row", "column_list", "column"):
        return ""
    return _rich(block, kind)
