"""Matching a Notion project to a repository on disk.

Three ways, in this order, from the most explicit to the least:

1. a `[projects]` entry in the configuration — the Notion name, the path;
2. a **`path` property on the project page** in Notion, which keeps the mapping
   on the board rather than in a file on one machine;
3. the project's `github` property, matched against the `origin` remotes of the
   repositories found under `workspace_root` — under the name it declares, or
   under the name GitHub redirects that one to, for a repository renamed since
   the page was written.

A project that declares none of them has no repository, and its tickets produce
a document instead of a pull request.

A way that fails does not stop the ones after it: a `path` that points nowhere
is what a repository renamed on disk looks like, and the same page usually
still names it correctly on the next line. The ticket runs on what the next way
finds, and the project says how it was found — `Project.note` — so that the
stale declaration gets corrected rather than trusted a little less each time.

What a later way may find is bounded, though. A declaration that does not
match is an error, not an invitation to guess: a repository is only ever taken
on the strength of its `origin` remote, never because its folder happens to be
named like the project, and never when two clones answer to the same remote.
A project none of its declarations lead to is put back, with every way that
was tried and why it failed in a comment.
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
    note: str = ""

    @property
    def is_code(self) -> bool:
        """A project with a repository is worked on in git; the others are not."""
        return self.path is not None

    @property
    def is_stale(self) -> bool:
        """Found, but not by the declaration that should have found it.

        The repository is the right one — the note says which declaration on
        the project page is out of date, and what it should say instead.
        """
        return bool(self.note)


def _normalise(url: str) -> str:
    """git@github.com:user/repo.git and https://github.com/user/repo → user/repo."""
    url = url.strip().removesuffix(".git")
    url = re.sub(r"^[a-z]+://", "", url)
    url = re.sub(r"^[^@/]+@", "", url)
    url = url.replace(":", "/", 1) if "@" not in url and ":" in url else url
    parts = [part for part in url.split("/") if part]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else url.lower()


def _property(page: notion.Page, *names: str) -> object:
    """The first of those columns the project page actually carries.

    A project database is written by hand, so its columns are named by hand:
    "Repository", "repository", or the bare "github" the runner used to ask
    for. Reading them all costs nothing and spares everyone a rename.
    """
    lookup = {key.lower(): key for key in page.properties}
    for name in names:
        key = lookup.get(name.lower())
        if key is None:
            continue
        value = notion.read(page, key)
        if value not in (None, "", []):
            return value
    return None


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
        self._by_remote: dict[str, list[Path]] | None = None

    def _index(self) -> dict[str, list[Path]]:
        """Every repository under the root, by its `origin` remote.

        A list, because nothing stops two clones of one repository from sitting
        side by side — and when they do, neither is *the* one: a match against
        that remote is refused rather than settled on whichever was walked
        first. A repository with no remote is walked but indexed nowhere, since
        nothing on a project page could designate it.
        """
        if self._by_remote is None:
            self._by_remote = {}
            for repo in _walk(self._root):
                url = git.remote_url(repo)
                if url:
                    self._by_remote.setdefault(_normalise(url), []).append(repo)
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
        github = str(_property(page, "Repository", "github", "repo") or "")

        # Every way that was tried and did not lead anywhere, in order. Read
        # twice: as the note on a project a later way found, and as the whole
        # of the error on a project none did.
        failed: list[str] = []

        def found(path: Path, how: str) -> Project:
            note = ""
            if failed:
                note = (
                    f"Repository found {how}, but a more explicit declaration is wrong: "
                    + "; ".join(failed)
                    + ". Correct it: the fallback is what its tickets run on."
                )
            return Project(name, path, page_id, github, self.brief(client, page_id), note)

        for source, declared in (
            ("[projects] in your configuration", self._overrides.get(name)),
            ("the project's Path property", _property(page, "Path", "path")),
        ):
            if not declared:
                continue
            path = Path(str(declared)).expanduser()
            if git.is_repo(path):
                return found(path, f"from {source}")
            failed.append(f"{path}, from {source}, is not a git repository")

        if not github:
            if failed:
                # Something was declared and it is wrong. Not a document
                # project: a page that names a repository means one, and a
                # ticket answered on the page instead would be a silent
                # change of kind, not a fallback.
                raise LookupError(self._nowhere(name, failed))
            # Nothing declares a repository, so the project does not have one:
            # its tickets produce a document written back into Notion. Guessing
            # from the project's name would be worse than useless here — it
            # would silently turn a writing task into a commit on some repo that
            # merely happens to be named alike.
            return Project(name, None, page_id, "", self.brief(client, page_id))

        source = "the project's Repository property"
        declared = _normalise(github)
        match = self._match(declared)
        if isinstance(match, Path):
            return found(match, f"by its origin remote, {declared}")
        if match:
            # Two clones, and the declaration is not wrong: it is the disk that
            # cannot answer. No other name would make it answer better.
            raise LookupError(self._nowhere(name, [*failed, match]))
        failed.append(f"{declared}, from {source}, matches no origin remote under {self._root}")

        # GitHub redirects a renamed repository, and only GitHub knows to what.
        # Asked last, because it is the one way that leaves the machine — and
        # only about a name that already failed to match anything here.
        current = _normalise(git.current_name(declared)) if "/" in declared else ""
        if current and current != declared:
            match = self._match(current)
            if isinstance(match, Path):
                failed[-1] = f"{source} says {declared}, which GitHub has renamed {current}"
                return found(match, f"by its origin remote, {current}")
            failed.append(
                match or f"GitHub renamed it {current}, which matches no origin remote either"
            )
        elif current == declared:
            failed.append("GitHub knows it by that name and no other")
        else:
            failed.append(
                "GitHub gave no other name for it (no such repository, or gh not usable here)"
            )

        raise LookupError(self._nowhere(name, failed))

    def _match(self, remote: str) -> Path | str:
        """The one repository with that remote, or why there is not one.

        A string is a reason and nothing was found: no clone at all, or more
        than one — which is as far from an answer, since a ticket committed to
        the wrong clone is a ticket lost somewhere nobody looks.
        """
        candidates = self._index().get(remote, [])
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            return ""
        return (
            f"{remote} is the remote of {len(candidates)} repositories under {self._root}: "
            + ", ".join(str(path) for path in sorted(candidates))
        )

    def _nowhere(self, name: str, failed: list[str]) -> str:
        return (
            f"“{name}”: no repository could be found —\n"
            + "".join(f"  · {reason}\n" for reason in failed)
            + f'Add  "{name}" = "/path/to/the/repo"  under [projects], correct the '
            "project's Path or Repository property, or clear both to make it a "
            "document project."
        )
