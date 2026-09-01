"""The little bit of git and gh the runner needs.

One rule, and it is not negotiable: **a ticket is never worked on in the main
repository**. Every ticket gets a `git worktree` on its own branch, which lets
two tickets of the same project move at once and leaves your working copy
exactly as you left it.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    pass


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def run(args: list[str], cwd: Path | str | None = None, timeout: int = 300) -> Result:
    process = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return Result(process.returncode, process.stdout.strip(), process.stderr.strip())


def git(args: list[str], cwd: Path | str, timeout: int = 300) -> Result:
    return run(["git", *args], cwd=cwd, timeout=timeout)


def is_repo(path: Path) -> bool:
    return (path / ".git").exists()


def remote_url(repo: Path) -> str:
    result = git(["remote", "get-url", "origin"], repo)
    return result.out if result.ok else ""


def default_branch(repo: Path) -> str:
    """The branch the origin declares as default, else main/master."""
    result = git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], repo)
    if result.ok and "/" in result.out:
        return result.out.rsplit("/", 1)[-1]
    for candidate in ("main", "master"):
        if git(["rev-parse", "--verify", "--quiet", candidate], repo).ok:
            return candidate
    result = git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    return result.out or "main"


def fetch(repo: Path) -> None:
    git(["fetch", "--quiet", "origin"], repo, timeout=180)


def add_worktree(repo: Path, path: Path, branch: str, base: str) -> None:
    """Create the worktree on a fresh branch, off the latest state of `base`."""
    start = base
    if git(["rev-parse", "--verify", "--quiet", f"origin/{base}"], repo).ok:
        start = f"origin/{base}"
    if git(["rev-parse", "--verify", "--quiet", branch], repo).ok:
        raise GitError(f"branch {branch} already exists — ticket already handled?")
    path.parent.mkdir(parents=True, exist_ok=True)
    result = git(["worktree", "add", "-b", branch, str(path), start], repo)
    if not result.ok:
        raise GitError(f"git worktree add: {result.err or result.out}")


def remove_worktree(repo: Path, path: Path) -> None:
    git(["worktree", "remove", "--force", str(path)], repo)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    git(["worktree", "prune"], repo)


def has_ref(repo: Path, reference: str) -> bool:
    return git(["rev-parse", "--verify", "--quiet", reference], repo).ok


def delete_branch(repo: Path, branch: str) -> Result:
    """Drop a branch whose worktree has just been removed.

    Forced, because the caller has already established that the branch carries
    nothing of its own — and `--delete` alone answers a different question than
    the one that was asked: it compares the branch with whatever the main
    checkout happens to be sitting on, which is nobody's base branch in
    particular.
    """
    return git(["branch", "--delete", "--force", branch], repo)


def commits_ahead(worktree: Path, base: str) -> int:
    for reference in (f"origin/{base}", base):
        result = git(["rev-list", "--count", f"{reference}..HEAD"], worktree)
        if result.ok and result.out.isdigit():
            return int(result.out)
    return 0


def is_dirty(worktree: Path) -> bool:
    return bool(git(["status", "--porcelain"], worktree).out)


def push(worktree: Path, branch: str) -> Result:
    return git(["push", "--set-upstream", "origin", branch], worktree, timeout=300)


def open_pull_request(worktree: Path, title: str, body: str, base: str) -> str:
    """Open the PR through gh and return its URL. Opening it merges nothing."""
    if not shutil.which("gh"):
        raise GitError("gh not found — cannot open the pull request")
    result = run(
        ["gh", "pr", "create", "--base", base, "--title", title, "--body", body],
        cwd=worktree,
        timeout=180,
    )
    if result.ok:
        for line in reversed(result.out.splitlines()):
            if line.startswith("http"):
                return line.strip()
        return result.out
    existing = run(["gh", "pr", "view", "--json", "url", "-q", ".url"], cwd=worktree)
    if existing.ok and existing.out.startswith("http"):
        return existing.out
    raise GitError(f"gh pr create: {result.err or result.out}")


MERGE_FLAGS = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}


def merge_pull_request(url: str, method: str = "squash") -> str:
    """Merge that pull request through `gh`. Returns what `gh` said of it.

    The one outward-facing gesture the runner makes on its own — and it makes it
    only because it was asked twice: once by the ticket having a pull request at
    all, once by somebody moving that ticket into the validated column. Anything
    GitHub refuses — a conflict, a check still red, a review still required — is
    raised as it came, because the wording is the answer.

    `--auto` is deliberately not used: a merge that lands quietly twenty minutes
    later, when a check goes green, is a merge nobody watched.
    """
    if not shutil.which("gh"):
        raise GitError("gh not found — cannot merge the pull request")
    result = run(["gh", "pr", "merge", url, MERGE_FLAGS.get(method, "--squash")], timeout=300)
    if result.ok:
        return (result.out or f"merged ({method})").strip()
    raise GitError(f"gh pr merge: {result.err or result.out}")


def pull_request_on(repo: Path, branch: str) -> str:
    """The URL of an open pull request made from that branch, or nothing.

    Nothing also means the question could not be asked — `gh` missing, not
    authenticated, no network. That is deliberately not distinguished here: this
    is never the only thing a caller looks at before touching a branch.
    """
    if not shutil.which("gh"):
        return ""
    result = run(
        ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url", "-q", ".[0].url"],
        cwd=repo,
        timeout=60,
    )
    return result.out if result.ok else ""


def pull_request_state(url: str) -> str:
    """What GitHub says of that pull request: MERGED, OPEN, CLOSED — or nothing.

    Nothing means the question could not be asked: `gh` missing, not
    authenticated, the pull request deleted. A ticket is never moved on an
    answer we did not get — the next run asks again.

    The URL carries its repository, so this needs no worktree: the ticket's own
    one is long gone by the time anyone merges.
    """
    if not shutil.which("gh"):
        return ""
    result = run(["gh", "pr", "view", url, "--json", "state", "-q", ".state"], timeout=60)
    return result.out if result.ok else ""
