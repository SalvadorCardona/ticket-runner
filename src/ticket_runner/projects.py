"""Matching a Notion project to a repository on disk.

Three ways, in this order, from the most explicit to the least:

1. a `[projects]` entry in the configuration — the Notion name, the path;
2. a **`path` property on the project page** in Notion, which keeps the mapping
   on the board rather than in a file on one machine;
3. the project's `github` property, matched against the `origin` remotes of the
   repositories found under `workspace_root`.

A project that declares none of them has no repository, and its tickets produce
a document instead of a pull request. A project that declares one that does not
exist is an error, not an invitation to guess: the ticket is put back with the
reason in a comment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import git, notion

SKIP = {"node_modules", "vendor", ".git", "dist", "build", ".venv", "__pycache__"}


@dataclass
class Project:
    name: str
    path: Path | None
    notion_id: str = ""
    github: str = ""
    brief: str = ""

    @property
    def is_code(self) -> bool:
        """A project with a repository is worked on in git; the others are not."""
        return self.path is not None


def _normalise(url: str) -> str:
    """git@github.com:user/repo.git and https://github.com/user/repo → user/repo."""
    url = url.strip().removesuffix(".git")
    url = re.sub(r"^[a-z]+://", "", url)
    url = re.sub(r"^[^@/]+@", "", url)
    url = url.replace(":", "/", 1) if "@" not in url and ":" in url else url
    parts = [part for part in url.split("/") if part]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else url.lower()


def _walk(root: Path, max_depth: int = 4) -> list[Path]:
    """Git repositories under root, without descending into dependency folders."""
    found: list[Path] = []
    stack = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            entries = list(directory.iterdir())
        except (PermissionError, OSError):
            continue
        if any(entry.name == ".git" for entry in entries):
            found.append(directory)
            continue  # no repository inside a repository
        for entry in entries:
            if entry.is_dir() and not entry.name.startswith(".") and entry.name not in SKIP:
                stack.append((entry, depth + 1))
    return found


class Resolver:
    def __init__(self, workspace_root: Path, overrides: dict[str, str]) -> None:
        self._root = workspace_root
        self._overrides = overrides
        self._by_remote: dict[str, Path] | None = None

    def _index(self) -> dict[str, Path]:
        if self._by_remote is None:
            self._by_remote = {}
            for repo in _walk(self._root):
                url = git.remote_url(repo)
                if url:
                    self._by_remote[_normalise(url)] = repo
                self._by_remote.setdefault(repo.name.lower(), repo)
        return self._by_remote

    def brief(self, client: notion.Client, page_id: str) -> str:
        """Whatever is written on the project page, as standing instructions.

        A project is more than a path: it has an audience, a voice, conventions,
        things never to do. Written once on the project page, they reach every
        ticket of that project without being retyped — which is what makes
        "write me a tweet" produce your tone rather than a generic one.

        An empty project page costs nothing and changes nothing.
        """
        try:
            return client.blocks_text(page_id)
        except notion.NotionError:
            return ""

    def resolve(self, client: notion.Client, page_id: str) -> Project:
        page = client.page(page_id)
        name = page.title or page_id
        github = str(notion.read(page, "github") or "")

        for source, declared in (
            ("[projects] in your configuration", self._overrides.get(name)),
            ("the project's path property", notion.read(page, "path")),
        ):
            if not declared:
                continue
            path = Path(str(declared)).expanduser()
            if not git.is_repo(path):
                raise LookupError(f"“{name}”: {path}, from {source}, is not a git repository")
            return Project(name, path, page_id, github, self.brief(client, page_id))

        if not github:
            # Nothing declares a repository, so the project does not have one:
            # its tickets produce a document written back into Notion. Guessing
            # from the project's name would be worse than useless here — it
            # would silently turn a writing task into a commit on some repo that
            # merely happens to be named alike.
            return Project(name, None, page_id, "", self.brief(client, page_id))

        index = self._index()
        match = index.get(_normalise(github))
        if match:
            return Project(name, match, page_id, github, self.brief(client, page_id))
        slug = _normalise(github).split("/")[-1]
        if slug in index:
            return Project(name, index[slug], page_id, github, self.brief(client, page_id))

        raise LookupError(
            f"“{name}”: {github} is declared but no matching repository exists "
            f"under {self._root}"
            + f'\nAdd  "{name}" = "/path/to/the/repo"  under [projects], or clear '
            "the project's github property to make it a document project."
        )
