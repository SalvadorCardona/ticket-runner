"""Naming a ticket that was written without a title.

A ticket is often written the way the thought arrives: what you want, straight
into the page, and never the title. Left as it is, that ticket travels through
the whole run under a constant — in the journal, in the notifications, in the
comments posted back, in the pull request, and, worst of all, in the branch,
where every nameless ticket looks like every other one.

So the runner names it from what it says, and writes the name **into Notion**:
a title that only ever existed in one run's memory would leave the page just as
anonymous for whoever opens it next.

Two ways of doing it, and the second is the point. A very short Claude session
reads the content and answers one line — which is what a person would have
written. When that session cannot run, or answers nothing usable, the first
significant line of the content is taken instead: it is what somebody naming
the ticket by hand would have copied anyway. Neither is ever allowed to fail a
run — a name is a comfort, the work is not.
"""

from __future__ import annotations

import re

# A title is a line, not a paragraph: it is read in a list of tickets and worn
# by a branch.
LIMIT = 60
# Naming is one sentence. A session still thinking about it after two minutes
# is a session that misunderstood the question.
TIMEOUT_MINUTES = 2

PROMPT = """\
Below is a ticket somebody wrote without giving it a title. Give it one.

Answer with the title itself and nothing else: one line, no quotes, no full \
stop, no preamble, no explanation. {limit} characters at most.

Write it in the language the content is written in, and say what the ticket \
asks for rather than describing the page — it will be read in a list of \
tickets, and carried by a git branch.

# The ticket's content

{body}
"""


def prompt(body: str) -> str:
    return PROMPT.format(limit=LIMIT, body=body.strip())


def clean(answer: str) -> str:
    """A title, out of whatever the session actually said.

    The last non-empty line rather than the first: a session that ignores "and
    nothing else" prefaces its answer far more often than it follows it with
    an afterthought.
    """
    lines = [line for line in answer.splitlines() if line.strip()]
    return _trim(lines[-1]) if lines else ""


def fallback(body: str) -> str:
    """The first line of the content that says something, cut to a title.

    What somebody naming the ticket by hand would have copied: a ticket almost
    always opens on what it is about. Headings are skipped — a template's
    "## Ce qu'il faut faire" names the template, not the ticket.
    """
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or set(stripped) <= set("-*_"):
            continue
        title = _trim(stripped)
        if title:
            return title
    return ""


def _trim(line: str) -> str:
    """One raw line, reduced to something that reads as a title."""
    line = " ".join(line.split())
    line = re.sub(r"^(?:[-*+#>]+\s*)+", "", line)  # a bullet, a heading, a quote
    line = re.sub(r"^\d+[.)]\s+", "", line)  # a numbered step
    line = line.strip(" *_`\"'“”«»").rstrip(" .,;:")
    return _cut(line)


def _cut(text: str) -> str:
    """Cut on a word, and say so: a title chopped mid-word reads as a bug."""
    if len(text) <= LIMIT:
        return text
    cut = text[:LIMIT].rsplit(" ", 1)[0].rstrip(" .,;:—-")
    return f"{cut or text[:LIMIT]}…"
