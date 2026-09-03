"""The prompt handed to the Claude session.

Two choices are made here, and they decide the quality of the whole system:

- **the agent commits, it does not push.** Publishing a branch and opening a PR
  are outward-facing gestures; the runner performs them, once it has checked
  there is actually something to publish;
- **an ambiguous ticket is not guessed.** The agent must answer `RESULT: blocked`
  and stop. A badly specified ticket coming back as a draft with the question
  asked beats a pull request that confidently does the wrong thing.

What surrounds the ticket is composed from the widest frame to the narrowest —
who you are, then the project, then the task — so that the specific is read last
and wins when the two disagree.

A third template answers a comment rather than doing a ticket, and its one rule
is the mirror of the first: **it talks, it does not work.** A conversation that
quietly edited a repository would be the least expected thing this tool could
do, so the frame says so, and the runner runs it in a permission mode that
cannot write.

A fourth one publishes what a ticket already holds, once a human has validated
it, and its rule is the third of the family: **it publishes, it does not
produce.** What goes out is what was read and accepted, unimproved — a session
that rewrote it on the way would be publishing something nobody validated.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT = """\
You are working through a ticket for the {project} project, alone and with \
nobody to talk to: no one can answer a question while the session runs.

# Ticket — {title}

{body}

{comments}{context}{brief}{agent}# Context

- Repository: {repo}
- You are in a dedicated git worktree, on branch `{branch}`, created from \
`{base}`. Your working copy is shared with no one.
{resumed}- Notion ticket: {url}

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

{comments}{context}{brief}{agent}# Context

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

DELIVERY = """\
A ticket {scope} has been validated: a human read what came back and said yes. \
What is left is to carry it out — to put it where it was meant to go.

**You are publishing, not producing.** What the ticket asked for already \
exists: it is in the page below, written by an earlier session and accepted \
since. Do not rewrite it, do not tighten it, do not decide it reads better \
slightly differently. What was validated is what goes out, word for word.

# Ticket — {title}

{body}

{comments}{context}{brief}{agent}# Context

- Working directory: {repo} — empty and disposable, it is yours to use.
- Notion ticket: {url}

# What is expected

1. Work out from the ticket what publishing it means here — posting it to an \
account, sending it, filing it, deploying it — and where. The ticket says; do \
not invent a destination it does not name.
2. Do it with the tools you actually have. If the account, the credential or \
the tool is not one of them, that is not something to work around: say what is \
missing and stop. Publishing something to the wrong place is worse than not \
publishing it.
3. Do it once. Check first whether it is already out there — a run that was \
interrupted may have got there — and if it is, say where rather than doing it \
again.
4. Nothing else. No file to fix, no adjacent improvement, no follow-up you \
thought of: those are other tickets.

End with a final line, exactly one of these two:

RESULT: ok — <what you published and where, with the link if there is one>
RESULT: blocked — <what stopped you, or what is missing to do it>
"""


CONVERSATION = """\
Someone has written to you in the comments of a Notion ticket {scope}. You are \
answering them, here, in that thread.

**You are talking, not working.** Nothing you say changes anything, and neither \
do you: no file written, no command that modifies, no commit, no branch, no \
pull request. If what is being asked needs work doing, say what it would take \
and say that it belongs in a ticket — the person you are talking to is one \
click away from making one.

# The ticket you are talking about — {title}

{body}

{comments}{context}{brief}{agent}# Context

- {where}
- Notion ticket: {url}

{thread}# The message to answer

{message}

# What is expected

1. Answer that message, and nothing else. Read whatever you need in order to \
answer honestly — the repository, the ticket, what was said before — and say \
you do not know rather than inventing something plausible.
2. Write in the language the message is written in.
3. Write for a comment thread: a few sentences. No heading, no preamble, no \
sign-off, no restating of the question. Long enough to be true, short enough to \
read on a phone.
4. Plain text. A short list is fine, a name in backticks is fine; nothing that \
needs rendering to mean anything.
5. No RESULT line and no report — everything you write is posted as the reply, \
exactly as you write it.
"""


FOLLOW_UP = """\
A new message in the same thread, on the same ticket. Same rules: you are \
talking, not working — answer it, change nothing, stay in its language, keep it \
to a comment.

{message}
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
    context: str = "",
    agent_name: str = "",
    agent_brief: str = "",
    comments: list[str] | None = None,
    resumed: str = "",
) -> str:
    scope, frame, heading, role, discussion = _frames(
        project, context, brief, agent_name, agent_brief, comments
    )
    return template.format(
        project=project or "no project",
        scope=scope,
        context=frame,
        brief=heading,
        agent=role,
        comments=discussion,
        title=title,
        body=body.strip() or "(the ticket has no description: everything is in the title)",
        repo=repo,
        branch=branch,
        base=base,
        url=url,
        resumed=resumed,
    )


def conversation(
    template: str,
    *,
    project: str,
    title: str,
    body: str,
    where: str,
    url: str,
    message: str,
    thread: list[str] | None = None,
    brief: str = "",
    context: str = "",
    agent_name: str = "",
    agent_brief: str = "",
    comments: list[str] | None = None,
) -> str:
    """The prompt that answers one comment.

    The same frames as a ticket, in the same order — who you are, the project,
    the role — because the thing answering is the same thing that does the work
    and should sound like it. What differs is what sits closest to the answer:
    the thread it is being written into.
    """
    scope, frame, heading, role, discussion = _frames(
        project, context, brief, agent_name, agent_brief, comments
    )
    # The thread is nearer than the page's discussion: it is the conversation
    # being had, where the rest is the ticket's history.
    said = ""
    if thread:
        said = (
            "# This thread so far\n\n"
            "Oldest first. “you” is what you said in it.\n\n"
            + "\n".join(f"- {line}" for line in thread)
            + "\n\n"
        )
    return template.format(
        project=project or "no project",
        scope=scope,
        context=frame,
        brief=heading,
        agent=role,
        comments=discussion,
        thread=said,
        title=title,
        body=body.strip() or "(the ticket has no description: everything is in the title)",
        where=where,
        url=url,
        message=message.strip(),
    )


def _frames(
    project: str,
    context: str,
    brief: str,
    agent_name: str,
    agent_brief: str,
    comments: list[str] | None,
) -> tuple[str, str, str, str, str]:
    """The blocks that surround a ticket, widest first. Shared by both prompts."""
    # A ticket may have no project at all: the sentence has to read either way.
    scope = f"for the {project} project" if project else "that belongs to no project"
    # Who the work is for: the workspace's context page, the same on every
    # ticket of every project. It matters most on a document ticket, where the
    # agent starts in an empty directory and has nothing else to go on.
    frame = f"# Who you are working for\n\n{context.strip()}\n\n" if context.strip() else ""
    # Standing instructions from the project page, if it has any. They come
    # before the `# Context` block so they read as the frame, not as an
    # afterthought — and after the page above, which frames them in turn.
    heading = f"# About {project}\n\n{brief.strip()}\n\n" if brief.strip() else ""
    # The role, narrower than the project and narrower than you: a project says
    # where the work happens, an agent says what craft it takes.
    role = ""
    if agent_brief.strip():
        role = f"# Your role — {agent_name}\n\n{agent_brief.strip()}\n\n"
    # What was said on the ticket sits with the ticket, not with the frames:
    # a question asked by a previous run and answered since is part of the ask.
    discussion = ""
    if comments:
        discussion = (
            "# What has already been said on this ticket\n\n"
            "Oldest first. An earlier run may have asked a question here and been "
            "answered since — that answer is part of what you are being asked.\n\n"
            + "\n".join(f"- {line}" for line in comments)
            + "\n\n"
        )
    return scope, frame, heading, role, discussion


def template(prompt_file: str, fallback: str = DEFAULT) -> str:
    if not prompt_file:
        return fallback
    path = Path(prompt_file).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
