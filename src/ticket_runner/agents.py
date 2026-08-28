"""The role a ticket is handled by.

A project says *where* the work happens and *what conventions* hold there. It
says nothing about **who** does it — and "fix this regression" and "write this
announcement" are not the same craft, even on the same repository.

So a ticket may point at an agent, and the agent is a page: its body is the
role, in prose, exactly as a project's page is its brief. It can also name a
model, which is how a rewriting ticket runs on a cheaper one than a refactor.

Everything here is optional twice over: a database without the relation column
behaves as it always has, and a ticket that names no agent is handled by the
runner's own prompt. What an agent must never do is loosen the frame — the
guardrails live in the template, above whatever the page says.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import notion


@dataclass
class Agent:
    name: str = ""
    brief: str = ""
    model: str = ""

    def __bool__(self) -> bool:
        return bool(self.name)


def resolve(client: notion.Client, page_id: str, model_property: str = "Model") -> Agent:
    """The agent a ticket points at. An unreadable page is no agent at all.

    Failing a ticket because the page describing its tone could not be fetched
    would trade a whole run for an accessory — the same call the project brief
    already makes.
    """
    try:
        page = client.page(page_id)
    except notion.NotionError:
        return Agent()
    name = page.title.strip()
    if not name:
        return Agent()
    try:
        brief = client.blocks_text(page_id)
    except notion.NotionError:
        brief = ""
    return Agent(name, brief, str(notion.read(page, model_property) or "").strip())
