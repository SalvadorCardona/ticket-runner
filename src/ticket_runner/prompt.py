"""The prompt handed to the Claude session.

Two choices are made here, and they decide the quality of the whole system:

- **the agent commits, it does not push.** Publishing a branch and opening a PR
  are outward-facing gestures; the runner performs them, once it has checked
  there is actually something to publish;
- **an ambiguous ticket is not guessed.** The agent must answer `RESULT: blocked`
  and stop. A badly specified ticket coming back as a draft with the question
  asked beats a pull request that confidently does the wrong thing.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT = """\
You are working through a ticket for the {project} project, alone and with \
nobody to talk to: no one can answer a question while the session runs.

# Ticket — {title}

{body}

{brief}# Context

- Repository: {repo}
- You are in a dedicated git worktree, on branch `{branch}`, created from \
`{base}`. Your working copy is shared with no one.
- Notion ticket: {url}

# What is expected

1. Read the repository before writing: its conventions, its CLAUDE.md or \
AGENTS.md if it has one, the neighbouring code. Your change must read like the rest.
2. Implement what is asked, and nothing more. No opportunistic refactoring, no \
fixing nearby bugs: those are other tickets.
3. Run whatever the repository offers to check itself — lint, tests, build — and \
fix what you break.
4. Commit inside the worktree, with a clear message written in the language the \
repository already uses. **Do not push** and do not open a pull request: that is \
the runner's job.
5. If the request is too ambiguous to settle alone, or if the ticket does not \
match this repository, do not guess: commit nothing and explain what is missing.

End with a final line, exactly one of these two:

RESULT: ok — <what you changed, in one sentence>
RESULT: blocked — <what is missing to decide>
"""


DOCUMENT = """\
You are handling a Notion ticket {scope}, alone and with nobody to talk to: no \
one can answer a question while the session runs.

There is no code repository here. What the ticket asks for is a document, and \
your answer will be written back into the Notion ticket itself.

# Ticket — {title}

{body}

{brief}# Context

- Working directory: {repo} — empty and disposable, it is yours to use.
- Notion ticket: {url}

# What is expected

1. Do the work properly before writing: read what the ticket points at, and \
search the web where the answer depends on facts you cannot know. Prefer \
primary sources.
2. Write the deliverable to a file named `ANSWER.md` in your working directory. \
That file is what gets published to the ticket, so it must stand on its own: no \
"as discussed above", no reference to this prompt.
3. Write it in the language the ticket is written in.
4. Markdown, and only what Notion renders: headings, bullet and numbered lists, \
checkboxes, quotes, code fences, links, bold and italic. No HTML, no tables.
5. **Match the shape of what is asked, not a default shape.** A procedure wants \
ordered steps with costs, durations and where each one happens. A short piece — \
a post, an email, a headline — wants the text itself, ready to copy, respecting \
the length its channel imposes; if a choice of angle matters, give two or three \
variants and say in one line what separates them. Do not wrap a two-line \
deliverable in five headings, and do not answer a research question with a slogan.
6. Where facts, prices, deadlines or official procedures are involved, verify \
them and cite the source. Say what could not be verified rather than filling \
the gap.
7. If the request is too ambiguous to answer usefully, do not pad: write no \
`ANSWER.md` and explain what is missing.

End with a final line, exactly one of these two:

RESULT: ok — <what you produced, in one sentence>
RESULT: blocked — <what is missing to decide>
"""


def build(
    template: str,
    *,
    project: str,
    title: str,
    body: str,
    repo: str,
    branch: str,
    base: str,
    url: str,
    brief: str = "",
) -> str:
    # A ticket may have no project at all: the sentence has to read either way.
    scope = f"for the {project} project" if project else "that belongs to no project"
    # Standing instructions from the project page, if it has any. They come
    # before the context so they read as the frame, not as an afterthought.
    heading = f"# About {project}\n\n{brief.strip()}\n\n" if brief.strip() else ""
    return template.format(
        project=project or "no project",
        scope=scope,
        brief=heading,
        title=title,
        body=body.strip() or "(the ticket has no description: everything is in the title)",
        repo=repo,
        branch=branch,
        base=base,
        url=url,
    )


def template(prompt_file: str, fallback: str = DEFAULT) -> str:
    if not prompt_file:
        return fallback
    path = Path(prompt_file).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
