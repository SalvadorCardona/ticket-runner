"""The little bit of git and gh the runner needs.

One rule, and it is not negotiable: **a ticket is never worked on in the main
repository**. Every ticket gets a `git worktree` on its own branch, which lets
two tickets of the same project move at once and leaves your working copy
exactly as you left it.

A second rule follows from the first: **a ticket that has run before is picked
up, not refused**. Its branch is named after its ID, so the branch a failed
session left behind is the same one the next attempt asks for — that branch is
checked out again and replayed on top of the newest base, rather than standing
in the way of the ticket for good.
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


@dataclass
class Worktree:
    """What making the ticket's worktree took, when it took anything.

    `note` is what the ticket's comment should say about it, empty when the
    branch was drawn fresh — which is the ordinary case, and says nothing worth
    reading. `reused` says the branch was already there: whatever is under it
    now is a history the last attempt left, replayed, so the push that follows
    is no longer a fast-forward of what origin holds.
    """

    note: str = ""
    reused: bool = False


def _held_at(repo: Path, branch: str) -> str:
    """The worktree that has this branch checked out, as git spells the path."""
    result = git(["worktree", "list", "--porcelain"], repo)
    if not result.ok:
        return ""
    path = ""
    for line in result.out.splitlines():
        if line.startswith("worktree "):
            path = line.split(" ", 1)[1]
        elif line == f"branch refs/heads/{branch}":
            return path
    return ""


def _same(one: str, other: Path) -> bool:
    try:
        return Path(one).resolve() == other.resolve()
    except OSError:  # a path nobody can resolve is not the one we are after
        return False


def rebase(worktree: Path, onto: str) -> str:
    """Replay the branch on top of `onto`. Says why it could not, or nothing.

    `--autostash` because a worktree kept from a failed session usually holds
    changes that were never committed, and those are exactly what the next
    session is meant to carry on from — refusing to rebase over them would put
    us back where we started.

    A rebase that stops is aborted rather than left half-applied: an agent that
    opens on a conflicted index reads it as the state of the world and starts
    resolving somebody else's merge instead of doing the ticket. The branch goes
    back to what it was, the session runs on it, and the conflict is a line in
    the ticket's comment.
    """
    result = git(["rebase", "--autostash", onto], worktree)
    if result.ok:
        return ""
    git(["rebase", "--abort"], worktree)
    lines = [line.strip() for line in (result.out + "\n" + result.err).splitlines() if line.strip()]
    conflict = next((line for line in lines if line.startswith("CONFLICT")), "")
    return conflict or (lines[0] if lines else f"git rebase {onto} failed")


def add_worktree(repo: Path, path: Path, branch: str, base: str) -> Worktree:
    """The ticket's worktree, on its own branch, off the latest state of `base`.

    A branch is named after the ticket's ID, so every attempt at one ticket asks
    for the same branch — and one left behind by a session that failed, or by a
    pull request nobody merged, used to refuse that ticket for good. Refusing is
    the wrong answer to "this ticket has run before": the branch is picked up
    instead, replayed on top of the newest base, and the session carries on from
    where the last one stopped. Nothing is thrown away to make room, and nothing
    that another worktree is holding is touched.
    """
    start = base
    if git(["rev-parse", "--verify", "--quiet", f"origin/{base}"], repo).ok:
        start = f"origin/{base}"
    # Registrations for directories somebody deleted by hand: git still counts
    # those as holding their branch, and would refuse to check it out again.
    git(["worktree", "prune"], repo)

    local = git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], repo).ok
    remote = git(["rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], repo).ok
    path.parent.mkdir(parents=True, exist_ok=True)

    if not local and not remote:
        _make_room(repo, path, base)
        result = git(["worktree", "add", "-b", branch, str(path), start], repo)
        if not result.ok:
            raise GitError(f"git worktree add: {result.err or result.out}")
        return Worktree()

    held = _held_at(repo, branch)
    if held and not _same(held, path):
        raise GitError(
            f"branch {branch} is checked out in {held} — another attempt at this "
            f"ticket is either running or was kept for a post-mortem.\n"
            f"  git -C {repo} worktree remove {held}   once you are done with it"
        )
    if held:
        kept = "its worktree was still there"
    else:
        _make_room(repo, path, base)
        add = (
            ["worktree", "add", str(path), branch]
            if local
            else ["worktree", "add", "--track", "-b", branch, str(path), f"origin/{branch}"]
        )
        result = git(add, repo)
        if not result.ok:
            raise GitError(f"git worktree add: {result.err or result.out}")
        kept = "an earlier attempt left it" if local else "it was pushed but never merged"

    carried = commits_ahead(path, base)
    commits = f"{carried} commit(s)" if carried else "no commit of its own"
    was = f"Branch `{branch}` was already there ({kept}, {commits})"
    if failure := rebase(path, start):
        return Worktree(
            note=(
                f"{was} and is reused as it stands: it does not replay onto `{start}` "
                f"— {failure}. Whatever it is behind on is for this session to deal with."
            ),
            reused=True,
        )
    return Worktree(
        note=f"{was}, rebased onto `{start}` and picked up where it stopped.",
        reused=True,
    )


def _make_room(repo: Path, path: Path, base: str) -> None:
    """Clear the ticket's directory, unless what is in it is somebody's work.

    Only ever the leavings of an earlier attempt at this same ticket: the path
    is made of the project and the ticket's ID, and nothing else writes there.
    A worktree with commits of its own or changes never committed is not ours to
    remove, and it is the one case where the ticket still has to stop.
    """
    if not path.exists():
        return
    if (path / ".git").exists() and (commits_ahead(path, base) or is_dirty(path)):
        raise GitError(
            f"{path} still holds work from an earlier attempt.\n"
            "  ticket-runner clean --force   removes it, and says so when it would not"
        )
    remove_worktree(repo, path)


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


def push(worktree: Path, branch: str, force: bool = False) -> Result:
    """Push the ticket's branch, forcing only when its history was replayed.

    `force` comes from the branch having been picked up from an earlier attempt
    and rebased: origin holds the version from before the rebase, so an ordinary
    push is refused as not being a fast-forward. `--force-with-lease` is what
    makes that safe to answer automatically — it still refuses if origin has
    moved since the fetch this run started with, which is the only case where
    somebody else's commit could be under there.
    """
    force_flag = ["--force-with-lease"] if force else []
    return git(
        ["push", "--set-upstream", *force_flag, "origin", branch], worktree, timeout=300
    )


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
