"""Le prompt donné à la session Claude.

Deux choix s'y jouent, et ils déterminent la qualité de tout le système :

- **l'agent commit, il ne pousse pas.** Publier une branche et ouvrir une PR
  sont des gestes tournés vers l'extérieur ; c'est le runner qui les fait, après
  avoir vérifié qu'il y a bien quelque chose à publier ;
- **un ticket ambigu n'est pas deviné.** L'agent doit répondre `RESULT: blocked`
  et s'arrêter. Un ticket mal spécifié qui revient en `Draft` avec la question
  posée vaut mieux qu'une PR qui fait la mauvaise chose avec assurance.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT = """\
Tu traites un ticket du projet {project}, seul et sans interlocuteur : personne \
ne pourra répondre à une question pendant la session.

# Ticket — {title}

{body}

# Contexte

- Dépôt : {repo}
- Tu travailles dans un worktree git dédié, sur la branche `{branch}`, créée \
depuis `{base}`. Ta copie de travail n'est partagée avec personne.
- Ticket Notion : {url}

# Attendu

1. Lis le dépôt avant d'écrire : conventions, CLAUDE.md ou AGENTS.md s'il y en a, \
code voisin. Ton changement doit se lire comme le reste.
2. Implémente la demande, rien de plus. Pas de refactorisation opportuniste, pas \
de correction de bugs voisins : ils feront d'autres tickets.
3. Fais tourner ce que le dépôt propose pour se vérifier — lint, tests, build — et \
corrige ce que tu casses.
4. Commit dans le worktree, un message clair en français. **Ne pousse pas** et \
n'ouvre pas de pull request : c'est le rôle du runner.
5. Si la demande est trop ambiguë pour être tranchée seul, ou si le ticket ne \
correspond pas à ce dépôt, ne devine pas : ne commit rien et explique ce qui manque.

Termine par une dernière ligne, exactement l'une des deux :

RESULT: ok — <ce que tu as changé, en une phrase>
RESULT: blocked — <ce qui manque pour décider>
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
        body=body.strip() or "(le ticket n'a pas de description : tout est dans le titre)",
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
        raise FileNotFoundError(f"prompt_file introuvable : {path}")
    return path.read_text(encoding="utf-8")
