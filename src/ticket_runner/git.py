"""Le peu de git et de gh dont le runner a besoin.

Une règle, et elle n'est pas négociable : **le travail d'un ticket n'a jamais
lieu dans le dépôt principal**. Chaque ticket obtient un `git worktree` sur sa
propre branche, ce qui permet à deux tickets du même projet d'avancer en même
temps et laisse votre copie de travail exactement comme vous l'avez laissée.
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
    """La branche par défaut telle que l'origine la déclare, sinon main/master."""
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
    """Crée le worktree sur une branche neuve, partant du dernier état de `base`."""
    start = base
    if git(["rev-parse", "--verify", "--quiet", f"origin/{base}"], repo).ok:
        start = f"origin/{base}"
    if git(["rev-parse", "--verify", "--quiet", branch], repo).ok:
        raise GitError(f"la branche {branch} existe déjà — ticket déjà traité ?")
    path.parent.mkdir(parents=True, exist_ok=True)
    result = git(["worktree", "add", "-b", branch, str(path), start], repo)
    if not result.ok:
        raise GitError(f"git worktree add : {result.err or result.out}")


def remove_worktree(repo: Path, path: Path) -> None:
    git(["worktree", "remove", "--force", str(path)], repo)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    git(["worktree", "prune"], repo)


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
    """Ouvre la PR via gh et renvoie son URL. La PR n'est jamais fusionnée."""
    if not shutil.which("gh"):
        raise GitError("gh introuvable — impossible d'ouvrir la pull request")
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
    raise GitError(f"gh pr create : {result.err or result.out}")
