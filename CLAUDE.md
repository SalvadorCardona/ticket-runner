# CLAUDE.md

Ce fichier oriente Claude Code (ou tout agent) dans ce dépôt. Le README fait
référence : il est très détaillé, ne le duplique pas ici et ne le résume pas —
sers-t'en pour toute question de comportement ou de configuration.

## Le projet, en deux phrases

`ticket-runner` exécute des tickets Notion avec Claude Code : un ticket passé
en *Ready* devient une session Claude, sur un `git worktree` jetable propre à
ce ticket, et revient en pull request ou en page Notion publiée. Le cœur tourne
en continu sur la machine de l'utilisateur ; un console web optionnelle et des
canaux (Telegram, Slack) permettent de suivre le travail ou d'y répondre.

## Stack et versions qui comptent

Deux mondes séparés, à ne pas mélanger :

- **Cœur** — Python 3.11+, bibliothèque standard uniquement. Aucune
  dépendance externe, aucun `pyproject.toml` : choix assumé (voir le docstring
  de `tests/run.py`) pour qu'installer le runner ne demande jamais rien de
  plus que `python3` et `git`, et que la suite de tests ne demande jamais
  d'installation.
- **`frontend/`** — sous-projet séparé : React 19, TypeScript, Vite 8,
  shadcn/ui sur Tailwind 4. Géré par npm (`package-lock.json`). Node n'est
  nécessaire que pour *modifier* la console, jamais pour l'installer ou
  l'exécuter.

## Commandes réelles

Cœur Python — pas de build, pas de lint séparé, ne pas en inventer :

```sh
python3 tests/run.py
```

Frontend, depuis `frontend/` :

```sh
npm install
npm run build   # tsc -b && vite build — écrit dans ../src/ticket_runner/web/static
npm run lint    # tsc -b --noEmit
npm run dev     # serveur de dev avec hot reload, proxy /api vers un console déjà lancé
```

## Arborescence utile

- `src/ticket_runner/` — le cœur : `runner.py` (boucle principale), `config.py`,
  `notion.py`, `git.py`, `session.py`, `channels/` (Telegram, Slack),
  `web/` (serveur de la console et API).
- `src/ticket_runner/web/static/` — **généré**, pas du code source à modifier
  à la main (voir Pièges connus).
- `frontend/` — sous-projet React/TypeScript/Vite de la console web.
- `bin/ticket-runner.in` — gabarit du script installé par `install.sh`
  (`@APP_DIR@` et `@PYTHON@` y sont substitués).
- `tests/run.py` — toute la suite de tests du cœur, sans framework.
- `systemd/` — gabarits des unités (`.service.in`, `.timer.in`) posées par
  `install.sh` pour le timer et la console.
- `desktop/` — gabarit du handler `ticket-runner://` enregistré sur le bureau.
- `diagrams/` — `ticket-runner.architecture.json` est la source du diagramme ;
  `architecture.html` et `ticket-runner.png` en sont générés, voir le README
  ("Regenerating it").

## Conventions de code et de commit

- `from __future__ import annotations` en tête de chaque module du cœur, et
  des annotations de type partout.
- Le cœur n'importe que la bibliothèque standard et ses propres modules —
  jamais de paquet tiers. Un `import` qui casserait ça n'est pas une option,
  c'est un autre projet.
- Les docstrings de module expliquent le *pourquoi* d'un choix (souvent non
  évident), pas ce que fait le fichier — voir `naming.py` ou `tests/run.py`
  pour le ton attendu. Continue dans ce style plutôt que d'ajouter des
  docstrings passe-partout.
- Messages de commit : une phrase descriptive au fil, sans préfixe imposé
  (`feat:`/`fix:`/`docs:` apparaissent parfois mais ne sont pas systématiques).
  Le dépôt mélange anglais et français selon qui a écrit le commit — reste
  cohérent avec le ticket que tu traites plutôt que de forcer une langue.
- Le frontend suit la configuration TypeScript stricte du dépôt
  (`tsc -b --noEmit` est le seul lint) et les sentences affichées passent par
  `t("...")` de `react-mini-i18n` — la phrase anglaise est la clé, la
  traduction française vit dans `frontend/src/lib/french.ts`.

## Pièges connus

- **`src/ticket_runner/web/static/` est un artefact commité, pas du code à
  éditer à la main.** Il est réécrit intégralement par `npm run build` depuis
  `frontend/` — le runner s'installe avec `python3` et `git` seulement, donc ce
  répertoire doit rester dans le dépôt et à jour à chaque changement de la
  console.
- **`diagrams/architecture.html` ne s'édite jamais directement.** Il est
  généré par l'outil `archify` à partir de
  `diagrams/ticket-runner.architecture.json`, qui est le fichier à modifier.
- **Ne jamais toucher au dépôt principal de l'utilisateur.** Chaque ticket
  travaille sur un `git worktree` jetable et sa propre branche ; le code du
  runner qui manipule des worktrees (`git.py`, `runner.py`) doit préserver
  cette isolation.
- **Deux phrases identiques, deux endroits.** Certaines chaînes affichées par
  la console (nom d'un réglage, texte d'aide) viennent de `web/settings.py`
  côté Python et sont recherchées par leur texte exact côté React — renommer
  l'une sans l'autre casse un test.
- **`config.example.toml` documente chaque clé en commentaire.** Une nouvelle
  clé de configuration sans son commentaire, ou sans mise à jour de
  `ticket-runner doctor`, part du mauvais pied.
- **Pas de `pyproject.toml` : ne pas en ajouter.** Une dépendance externe pour
  le cœur, même petite, va à l'encontre du choix documenté dans
  `tests/run.py`.
