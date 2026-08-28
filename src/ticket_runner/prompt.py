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

# Context

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
) -> str:
    return template.format(
        project=project,
        title=title,
        body=body.strip() or "(the ticket has no description: everything is in the title)",
        repo=repo,
        branch=branch,
        base=base,
        url=url,
    )


def template(prompt_file: str) -> str:
    if not prompt_file:
        return DEFAULT
    path = Path(prompt_file).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"prompt_file not found: {path}")
    return path.read_text(encoding="utf-8")
