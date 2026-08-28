"""Faire correspondre un projet Notion à un dépôt sur le disque.

Trois façons, dans cet ordre, de la plus explicite à la plus devinée :

1. une entrée `[projects]` dans la configuration — le nom Notion, le chemin ;
2. la propriété `github` du projet, confrontée aux `origin` des dépôts trouvés
   sous `workspace_root` ;
3. à défaut, un dossier portant le nom du dépôt.

La première suffit toujours ; les deux autres évitent d'avoir à déclarer chaque
projet à la main. Un projet qu'on ne sait pas situer n'est jamais deviné à
moitié : le ticket est reposé avec la raison en commentaire.
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
    path: Path
    notion_id: str = ""
    github: str = ""


def _normalise(url: str) -> str:
    """git@github.com:user/repo.git et https://github.com/user/repo → user/repo."""
    url = url.strip().removesuffix(".git")
    url = re.sub(r"^[a-z]+://", "", url)
    url = re.sub(r"^[^@/]+@", "", url)
    url = url.replace(":", "/", 1) if "@" not in url and ":" in url else url
    parts = [part for part in url.split("/") if part]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else url.lower()


def _walk(root: Path, max_depth: int = 4) -> list[Path]:
    """Les dépôts git sous root, sans descendre dans les dossiers de dépendances."""
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
            continue  # pas de dépôt dans un dépôt
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

    def resolve(self, client: notion.Client, page_id: str) -> Project:
        page = client.page(page_id)
        name = page.title or page_id
        github = str(notion.read(page, "github") or "")

        override = self._overrides.get(name)
        if override:
            path = Path(override)
            if not git.is_repo(path):
                raise LookupError(f"« {name} » : {path} n'est pas un dépôt git")
            return Project(name, path, page_id, github)

        index = self._index()
        if github:
            match = index.get(_normalise(github))
            if match:
                return Project(name, match, page_id, github)
            slug = _normalise(github).split("/")[-1]
            if slug in index:
                return Project(name, index[slug], page_id, github)

        guess = index.get(name.lower().replace(" ", "-"))
        if guess:
            return Project(name, guess, page_id, github)

        raise LookupError(
            f"« {name} » : aucun dépôt trouvé sous {self._root}"
            + (f" pour {github}" if github else " (propriété github vide)")
            + f'\nAjoutez  "{name}" = "/chemin/vers/le/depot"  sous [projects].'
        )
