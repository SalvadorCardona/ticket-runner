# ticket-runner

**Vos tickets Notion, joués par Claude Code.** Vous écrivez un ticket, vous le passez
en *Not started*, et quelques minutes plus tard une pull request vous attend — branche
dédiée, commits, description, et le lien de la session dans les commentaires du ticket.

Le runner tourne sur votre machine, en tâche de fond, sur **tous vos projets à la fois** :
c'est la relation `Project` du ticket qui décide dans quel dépôt il ira travailler.

```
Notion                    ticket-runner                     git
──────                    ─────────────                     ───
Not started    ──────▶    réserve le ticket
                          git worktree + branche      ──▶   ticket/supprimer-le-header-3ca45168
In progress    ◀──────    claude --print
                          commits vérifiés
Done + PR      ◀──────    push + gh pr create         ──▶   pull request à relire
```

---

## Installation

```sh
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/install.sh | sh
```

Le script vérifie les dépendances, installe la commande `ticket-runner` dans
`~/.local/bin`, vous demande votre jeton Notion, et arme un minuteur systemd qui relève
les tickets **toutes les 30 minutes**. Puis :

```sh
ticket-runner doctor
```

qui vous dit, ligne par ligne, ce qui manque encore.

Relancer la même commande **met à jour** l'installation : le code est remplacé, votre
configuration est conservée.

> **Prérequis** — Linux avec systemd en session utilisateur, `python3` ≥ 3.11 (aucune
> dépendance à installer, tout est dans la bibliothèque standard), `git`,
> [Claude Code](https://claude.com/claude-code), et `gh` authentifié pour les pull requests.

| Variable | Effet |
| --- | --- |
| `TR_INTERVAL=15` | minutes entre deux tours (défaut : 30) |
| `TR_NO_SERVICE=1` | pas de minuteur : vous lancez `ticket-runner run` vous-même |
| `TR_SRC=.` | installer depuis un clone local, sans réseau |

---

## Le côté Notion

### 1. Une intégration

Sur [notion.so/my-integrations](https://www.notion.so/my-integrations), créez une
intégration interne et copiez son jeton (`ntn_…`). Puis, **sur la base de tickets comme
sur la base de projets** : menu `···` → *Connexions* → votre intégration. Sans ce
partage, l'API répond « object not found » et rien ne fonctionne — c'est l'oubli le plus
courant, et `ticket-runner doctor` le nomme explicitement.

### 2. La base de tickets

| Propriété | Type | Rôle |
| --- | --- | --- |
| `Name` | titre | ce que l'agent doit faire, en une ligne |
| `Status` | statut | **le moteur de tout le système** — voir plus bas |
| `Project` | relation | vers la base des projets : décide du dépôt |
| `Agent` | texte | rempli par le runner : qui a pris le ticket |
| `Pull Request` | URL | remplie par le runner à la fin |
| `Session` | texte | *optionnel* — l'ID de session, pour `claude --resume` |

Le **contenu** de la page du ticket est envoyé à l'agent comme description. Écrivez-y ce
que vous diriez à un développeur qui ne connaît pas le sujet : ce qui doit changer, où,
et à quoi on reconnaît que c'est fait.

### 3. La base de projets

Une ligne par projet. Le runner a besoin de situer le dépôt sur le disque, et il essaie
dans cet ordre :

1. une entrée `[projects]` dans votre configuration — `"Trader Ia" = "~/workspace/labo/trader-ia"` ;
2. la propriété **`github`** du projet, comparée aux `origin` de tous les dépôts trouvés
   sous `workspace_root` ;
3. à défaut, un dossier portant le nom du dépôt.

`ticket-runner projects` vous montre le résultat pour chaque projet référencé — à lancer
une fois après l'installation, c'est ce qui évite les surprises.

### 4. Les quatre statuts

C'est là que se joue votre contrôle sur le système.

| Statut | Ce qu'il veut dire |
| --- | --- |
| **Draft** | pas prêt. Le runner n'y touche pas. C'est aussi là que **retombe un ticket échoué**, avec la raison en commentaire. |
| **Not started** | prêt. La description est assez précise pour qu'un agent la traite seul. **Le seul geste qui déclenche du travail.** |
| **In progress** | réservé par le runner. Empêche le tour suivant de le reprendre. |
| **Done** | branche poussée, pull request ouverte. À vous de relire. |

Rien n'est jamais fusionné automatiquement.

---

## Utilisation

```sh
ticket-runner list         # les tickets prêts, et leur projet
ticket-runner run          # un tour tout de suite
ticket-runner run --dry-run          # ce qu'il ferait, sans rien toucher
ticket-runner run --ticket <url>     # ce ticket-là, quel que soit son statut
ticket-runner logs -f      # suivre la session en cours
ticket-runner status       # minuteur, tour en cours, derniers tickets
ticket-runner history      # ce qui a été traité, avec les PR
ticket-runner projects     # correspondance projet Notion → dépôt local
ticket-runner doctor       # diagnostic complet
ticket-runner clean --force          # supprimer les worktrees laissés par les échecs
ticket-runner disable      # arrêter le minuteur (enable pour le relancer)
```

Le premier essai gagne à être fait à la main, sur un ticket choisi :

```sh
ticket-runner run --ticket https://www.notion.so/... --dry-run   # on regarde
ticket-runner run --ticket https://www.notion.so/...             # on y va
```

---

## Ce qui protège votre code

Un agent qui travaille sans personne pour l'arrêter, ça se cadre. Cinq garde-fous, tous
dans le chemin normal du programme :

- **Le dépôt principal n'est jamais touché.** Chaque ticket obtient un `git worktree`
  jetable, sur sa propre branche. Votre copie de travail, vos fichiers non commités et
  votre branche courante restent exactement comme vous les avez laissés — et deux tickets
  du même projet peuvent avancer en même temps.
- **L'agent commit, le runner publie.** Pousser une branche et ouvrir une PR sont des
  gestes tournés vers l'extérieur : ils ont lieu après coup, une fois vérifié qu'il y a
  bien des commits. Une session qui se déclare terminée sans rien avoir commité est
  traitée comme un échec.
- **Un ticket ambigu n'est pas deviné.** Le prompt demande explicitement à l'agent de
  répondre `RESULT: blocked` et de s'arrêter plutôt que de trancher à votre place. Le
  ticket revient en *Draft* avec la question posée en commentaire.
- **Un ticket qui échoue n'emporte que lui.** Les autres du même tour continuent. Son
  worktree est conservé pour l'autopsie, et l'ID de session permet de rouvrir la
  conversation exactement là où elle s'est arrêtée : `claude --resume <id>`.
- **Deux tours ne se chevauchent jamais.** Un verrou de fichier fait qu'un tour plus long
  que l'intervalle du minuteur ne se fait pas doubler.

Reste une chose à savoir : par défaut le runner lance la session en
`permission_mode = "bypassPermissions"`, parce qu'une session sans interlocuteur ne peut
pas demander d'autorisation et se bloquerait au premier test à lancer. L'isolation vient
du worktree, pas du modèle de permissions. Si vous préférez l'inverse, `"acceptEdits"`
interdit les commandes shell non approuvées — au prix de sessions qui s'arrêtent souvent.

---

## Configuration

Tout est dans **`~/.config/ticket-runner/config.toml`** (`ticket-runner config` l'ouvre).
Les réglages qui changent quelque chose au quotidien :

| Clé | Défaut | Effet |
| --- | --- | --- |
| `runner.max_concurrent` | `2` | tickets menés de front en un tour |
| `runner.timeout_minutes` | `30` | au-delà, la session est tuée et le ticket échoue |
| `runner.model` | `""` | `"opus"`, `"sonnet"`… vide = le défaut du CLI |
| `runner.workspace_root` | `~/workspace` | où chercher les dépôts |
| `runner.base_branch` | `""` | vide = la branche par défaut de chaque dépôt |
| `runner.open_pull_request` | `true` | `false` : la branche est poussée, sans PR |
| `runner.keep_worktree_on_failure` | `true` | garder de quoi comprendre un échec |
| `runner.prompt_file` | `""` | votre propre gabarit de prompt |
| `[notion.properties]` | | si vos colonnes portent d'autres noms |
| `[notion.status]` | | si vos statuts portent d'autres noms |

Le fichier est créé en `chmod 600` : il contient votre jeton Notion.

---

## Quand ça ne marche pas

| Symptôme | Cause la plus probable |
| --- | --- |
| `object not found` sur la base | la base n'est pas partagée avec l'intégration (menu `···` → Connexions) |
| « projet non situé sur le disque » | ajoutez `"Nom Notion" = "/chemin"` sous `[projects]` |
| le minuteur ne part pas session fermée | `sudo loginctl enable-linger $USER` |
| branche poussée, pas de PR | `gh` ne trouve pas ses identifiants dans un service systemd — trousseau verrouillé. `gh auth login` avec un jeton, ou `GH_TOKEN` dans l'unité |
| `claude: command not found` dans le journal | le PATH gravé dans l'unité date d'avant un changement de version de node : relancez `install.sh` |

Les journaux de sessions sont dans `~/.local/state/ticket-runner/logs/` (un `.jsonl` par
ticket, le flux brut de la session), l'historique dans `history.jsonl`, et le journal du
minuteur dans `journalctl --user -u ticket-runner -f`.

---

## Désinstallation

```sh
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/uninstall.sh | sh
```

`TR_PURGE=1` supprime en plus la configuration, les journaux et l'historique. Les
branches déjà poussées ne sont jamais touchées.

---

## Licence

MIT.
