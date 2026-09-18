/* The console in French.
 *
 * One entry per sentence the console says, keyed by the sentence itself — the
 * key is the English source, so a key nobody has translated is drawn as it was
 * written rather than as a name nobody meant to read. See `i18n.ts`.
 *
 * Three kinds of entry live here, and they are kept apart on purpose:
 *
 * - the words the packages under the console say, which are theirs;
 * - the words the console itself says;
 * - the words `web/settings.py` writes about the configuration, which travel
 *   from the server to the settings page and are translated on arrival. A test
 *   holds that last list to the file it comes from: a setting whose sentence
 *   is rewritten in Python and not here would quietly go back to English.
 */
export const FRENCH: Record<string, string> = {
  /* -- what the packages say ---------------------------------------------- */
  // react-resource-view and react-data-form draw a board, a form and a panel,
  // and say a few things of their own along the way. A word they already say
  // in French is absent from this list: an untranslated key is drawn as it
  // stands, which is the French they were written in.
  "No data yet": "Rien sur le tableau.",
  // What a list with a `noResult` of its own never says — and what the tables
  // in the settings fall back on.
  "No results yet": "Rien pour l'instant",
  "Nothing matched your search. Try different criteria, or come back later.":
    "Rien ne correspond. Changez de critères, ou revenez plus tard.",
  "Nothing here": "rien",
  Saved: "Déplacé",
  create: "Nouveau ticket",
  read: "Ouvrir",
  update: "modifier",
  delete: "retirer",
  Cancel: "Annuler",
  "Search...": "Rechercher…",
  "Select...": "Choisir…",
  "Nothing found.": "Rien trouvé.",
  "Nothing found yet": "Rien trouvé pour l'instant",
  "Nothing selected": "Rien de sélectionné",
  "Pick an item from the list to see its details":
    "Choisissez un élément dans la liste pour en voir le détail",
  "View details": "Voir le détail",
  "Clear the search": "Effacer la recherche",
  "This cannot be undone.": "C'est sans retour.",
  "Your changes have been saved": "Vos modifications ont été enregistrées",
  Deleted: "Supprimé",
  "The item has been removed": "L'élément a été supprimé",
  "The item could not be removed": "L'élément n'a pas pu être supprimé",
  "Deletion is not possible": "La suppression est impossible",
  // A value the package prints as it holds it, in the one layout that shows a
  // checkbox without a form around it: the calendar's preview of a schedule.
  true: "oui",
  false: "non",
  /* The calendar, which the schedules are laid out in: the days of its week,
     and the button that walks back through them. `Today`, `Jour`, `Semaine` and
     `Mois` are the package's own French; only what it says in English needs an
     entry here. */
  monday: "lundi",
  tuesday: "mardi",
  wednesday: "mercredi",
  thursday: "jeudi",
  friday: "vendredi",
  saturday: "samedi",
  sunday: "dimanche",
  Previous: "Précédent",
  Today: "Aujourd'hui",
  // The two lines a form ends on, set from `i18n.ts` rather than read from a
  // declaration: they are handed to a toast as they stand.
  // Not `Saved`, which the package already says — and says on a card dropped in
  // another column, where it means "moved".
  Written: "Écrit",
  "Some fields need another look": "Quelques champs demandent une relecture",

  /* -- where you are ------------------------------------------------------- */
  workspace: "espace de travail",
  board: "tableau",
  table: "liste",
  live: "en direct",
  schedules: "récurrences",
  settings: "réglages",
  "the console": "la console",
  "the discussion": "la discussion",
  "the workspace": "l'espace de travail",
  "the ticket": "le ticket",
  "the console's language": "la langue de la console",
  "This browser's, and this browser's only: it is not written to the file. Left alone, the console reads the one your browser asks for.":
    "Celle de ce navigateur, et de lui seul : elle ne s'écrit pas dans le fichier. Sans réponse, la console lit celle que votre navigateur demande.",
  // The bubble in the bottom corner, and what it opens: the ticket's
  // discussion where there is one, the workspace's own everywhere else.
  "open {{pane}}": "ouvrir {{pane}}",
  "A sentence talks to your workspace; a line that starts with > runs a command.":
    "Une phrase parle à votre espace de travail ; une ligne qui commence par > lance une commande.",
  "No such page.": "Cette page n'existe pas.",

  /* -- the menu ------------------------------------------------------------ */
  Board: "Tableau",
  Live: "En direct",
  Schedules: "Récurrences",
  Settings: "Réglages",
  Refresh: "Relire",
  Light: "Clair",
  Dark: "Sombre",
  "go light": "passer au clair",
  "go dark": "passer au sombre",
  "reread the board now": "relire le tableau maintenant",
  "event stream": "flux d'événements",
  "connecting…": "connexion…",
  "reconnecting…": "reconnexion…",
  // The menu is a name and a count; the sentences that used to sit under each
  // name are gone, and the words they were made of with them.
  "{{count}} turn(s)": "{{count}} tour(s)",
  "no conversation yet": "aucune conversation",
  // At the foot of the menu, where the stream's own dot is: the version, and
  // the one day it matters, that a newer one is waiting. The row of pills it
  // used to be said this beside four other things nobody was reading.
  "the version this console runs": "la version que fait tourner cette console",
  "v{{version}} — {{waiting}} is waiting, run: ticket-runner update":
    "v{{version}} — {{waiting}} attend, lancez : ticket-runner update",

  /* -- the board and a ticket ---------------------------------------------- */
  // The columns as the runner names them, for a board that has not named them
  // itself. A board that has is repeated in its own words.
  Ready: "Prêt",
  "In progress": "En cours",
  "In review": "En revue",
  Validated: "Validé",
  Blocked: "Bloqué",
  Failed: "Échoué",
  Done: "Terminé",
  Elsewhere: "Ailleurs",
  "Your board, live. Drop a card in another column and the runner is told.":
    "Votre tableau, en direct. Déposez une carte dans une autre colonne et le runner en est averti.",
  "Nothing on the board yet — a ticket moved to the ready column is a session that starts.":
    "Rien sur le tableau — un ticket déposé dans la colonne prête, c'est une session qui démarre.",
  "New ticket": "Nouveau ticket",
  Ticket: "Ticket",
  Title: "Titre",
  "The brief": "Le brief",
  Project: "Projet",
  Status: "Statut",
  Priority: "Priorité",
  Model: "Modèle",
  Cost: "Coût",
  Took: "Durée",
  Scheduled: "Prévu",
  "Ready to run": "Prêt à tourner",
  Create: "Créer",
  "What has to be done, in one line. It is what the board shows.":
    "Ce qu'il y a à faire, en une ligne. C'est ce que le tableau montre.",
  "The whole of what the runner is told. Written on the ticket's page, and read from there.":
    "Tout ce que le runner reçoit. Écrit sur la page du ticket, et lu depuis là.",
  "What must change, where, and how you will know it is done.":
    "Ce qui doit changer, où, et à quoi vous verrez que c'est fait.",
  "A project with a repository gets a pull request; none at all gets a document.":
    "Un projet avec un dépôt donne une pull request ; aucun projet donne un document.",
  "Off, and the ticket is a draft the runner leaves alone.":
    "Décoché, le ticket est un brouillon auquel le runner ne touche pas.",
  "no project — a document": "aucun projet — un document",
  "no project": "aucun projet",
  "open in Notion": "ouvrir dans Notion",
  "pull request": "pull request",
  session: "session",
  "just now": "à l'instant",
  "{{count}} min ago": "il y a {{count}} min",
  "{{count}}h ago": "il y a {{count}} h",
  "{{count}}d ago": "il y a {{count}} j",
  "{{count}}mo ago": "il y a {{count}} mois",
  "Scroll to the last message": "Aller au dernier message",
  "{{count}} min": "{{count}} min",
  "{{count}} h": "{{count}} h",
  "run again": "relancer",
  "make ready": "rendre prêt",
  validate: "valider",
  done: "terminé",
  hold: "mettre en attente",
  project: "projet",
  priority: "priorité",
  model: "modèle",
  spent: "dépensé",
  took: "durée",
  "taken by": "pris par",
  created: "créé",
  scheduled: "prévu",
  "the brief": "le brief",
  "The page is empty: the title is the whole brief.":
    "La page est vide : le titre est tout le brief.",
  "This ticket could not be read.": "Ce ticket n'a pas pu être lu.",
  "Ticket created": "Ticket créé",
  "could not move “{{title}}”": "impossible de déplacer « {{title}} »",

  /* -- a ticket's terminal -------------------------------------------------- */
  "Talking to": "Discussion avec",
  "No ticket open": "Aucun ticket ouvert",
  "Everything said on the ticket, oldest first. What you type is a comment on it.":
    "Tout ce qui s'est dit sur le ticket, du plus ancien au plus récent. Ce que vous écrivez est un commentaire sur celui-ci.",
  "Open a ticket from the board.": "Ouvrez un ticket depuis le tableau.",
  "Nothing has been said on this ticket yet.": "Rien n'a encore été dit sur ce ticket.",
  "reading the discussion…": "lecture de la discussion…",
  "an answer to its question runs it again": "une réponse à sa question le relance",
  "asks it for words instead": "lui demande des mots plutôt que du travail",
  "Answer the ticket, or ask it something": "Répondez au ticket, ou demandez-lui quelque chose",
  "read the discussion again": "relire la discussion",
  "reading…": "lecture…",
  reread: "relire",
  "sending…": "envoi…",
  "not written: {{why}}": "non écrit : {{why}}",
  "could not read the discussion: {{why}}": "impossible de lire la discussion : {{why}}",
  you: "vous",
  problem: "problème",
  command: "commande",
  "the runner": "le runner",

  /* -- the workspace console ------------------------------------------------ */
  "Talking to your machine": "Parler à votre machine",
  "A sentence reaches your repositories and the board; a line that starts with":
    "Une phrase atteint vos dépôts et le tableau ; une ligne qui commence par",
  "reaches the CLI.": "atteint le CLI.",
  "a ticket-runner command": "une commande ticket-runner",
  "a sentence talks to your workspace · > runs a ticket-runner command":
    "une phrase parle à votre espace de travail · > lance une commande ticket-runner",
  "Ask the workspace, or type >status": "Demandez à l'espace de travail, ou tapez >status",
  "Ask me anything about your workspace — I can read your repositories, look at the board and create tickets. Type > followed by a command (>status, >list, >run) to use the CLI directly.":
    "Demandez-moi ce que vous voulez sur votre espace de travail — je peux lire vos dépôts, regarder le tableau et créer des tickets. Tapez > suivi d'une commande (>status, >list, >run) pour passer directement par le CLI.",
  Send: "Envoyer",
  "working…": "en cours…",
  "new conversation": "nouvelle conversation",
  "start a new conversation": "démarrer une nouvelle conversation",
  "exit {{code}}": "sortie {{code}}",

  /* -- live ------------------------------------------------------------------ */
  "See the work happen.": "Voyez le travail se faire.",
  "What the running tickets are doing, straight from their session logs — without asking the board.":
    "Ce que font les tickets en cours, directement depuis leurs journaux de session — sans rien demander au tableau.",
  "writing now": "en train d'écrire",
  quiet: "calme",
  sessions: "sessions",
  "{{count}} ticket(s) in progress": "{{count}} ticket(s) en cours",
  "nothing in progress": "rien en cours",
  timer: "minuterie",
  "timer {{state}}": "minuterie {{state}}",
  off: "arrêtée",
  "between two runs": "entre deux passes",
  handled: "traités",
  "${{amount}} spent so far": "{{amount}} $ dépensés jusqu'ici",
  "{{count}} step(s)": "{{count}} étape(s)",
  "Out of credit until {{at}}. The subscription's window is spent: tickets stay where they are, and the first run after that takes them again.":
    "Crédits épuisés jusqu'à {{at}}. La fenêtre de l'abonnement est consommée : les tickets restent où ils sont, et la première passe après ce moment les reprend.",
  "`claude` was not found on this machine: no session can start.":
    "`claude` est introuvable sur cette machine : aucune session ne peut démarrer.",
  "Nothing is running. A session that starts writes here as it works.":
    "Rien ne tourne. Une session qui démarre écrit ici au fil de son travail.",

  /* -- what comes back on its own -------------------------------------------- */
  /* `Cadence`, `Model` and `Priority` are already said above, where the
     configuration says them; `table` is said where the board says it. */
  Schedule: "Récurrence",
  calendar: "calendrier",
  "A row says what to make and how often; when the moment comes the runner writes the ticket into the ready column and steps back.":
    "Une ligne dit quoi faire et à quelle fréquence ; le moment venu, le runner écrit le ticket dans la colonne prête et se retire.",
  "{{count}} of {{total}} on": "{{count}} sur {{total}} active(s)",
  "nothing yet": "rien pour l'instant",
  "Nothing repeats here": "Rien ne se répète ici",
  "This workspace has no “{{page}}” page.":
    "Cet espace de travail n'a pas de page « {{page}} ».",
  "builds it.": "la construit.",
  "Nothing repeats here yet": "Rien ne se répète encore ici",
  "A row in the “{{page}}” database is a ticket that comes back.":
    "Une ligne de la base « {{page}} », c'est un ticket qui revient.",
  "none of this runs.": "rien de tout cela ne tourne.",
  "This schedule is no longer on the board.": "Cette récurrence n'est plus sur le tableau.",
  // The columns of the list, and the fields of the form that writes a row.
  At: "À",
  Day: "Jour",
  On: "Active",
  Next: "Prochaine",
  Last: "Dernière",
  Problem: "Problème",
  "New schedule": "Nouvelle récurrence",
  "A ticket that comes back": "Un ticket qui revient",
  "nothing said": "rien de précisé",
  "What the ticket it makes will be called. Every occurrence carries this name.":
    "Le nom du ticket qu'elle produit. Chaque occurrence porte ce nom.",
  "Weekly dependency review": "Revue hebdomadaire des dépendances",
  "The hour, written 09:00. Empty, and the hour the pass runs at answers.":
    "L'heure, écrite 09:00. Vide, c'est l'heure de la passe qui répond.",
  "Which day a weekly or monthly one lands on.":
    "Le jour où tombe une récurrence hebdomadaire ou mensuelle.",
  "Monday, or 1 to 31": "Lundi, ou 1 à 31",
  "Off, and nothing is born — the row is kept, and the hours with it.":
    "Décochée, rien ne naît — la ligne est gardée, et ses horaires avec.",
  "Created unticked: nothing is born until you turn it on.":
    "Créée décochée : rien ne naît tant que vous ne l'activez pas.",
  "A schedule needs a name": "Une récurrence a besoin d'un nom",

  /* -- the projects ----------------------------------------------------------- */
  /* `Projects`, `Project`, `Repository`, `Where it is` and `The brief` are
     already said above, where the board and the configuration say them. */
  "What the tickets are about.": "Ce dont parlent les tickets.",
  "What the tickets are about: where the work happens, and what conventions hold there. One with no repository is not a mistake — its tickets come back as a document.":
    "Ce dont parlent les tickets : où se fait le travail, et quelles conventions y règnent. Un projet sans dépôt n'est pas une erreur — ses tickets reviennent sous forme de document.",
  "A project says where the work happens and what conventions hold there. One with no repository is not a mistake: its tickets come back as a document.":
    "Un projet dit où se fait le travail et quelles conventions y règnent. Un projet sans dépôt n'est pas une erreur : ses tickets reviennent sous forme de document.",
  cards: "cartes",
  Kind: "Nature",
  Repository: "Dépôt",
  "On this machine": "Sur cette machine",
  Tickets: "Tickets",
  "code work": "travail de code",
  "document work": "travail de rédaction",
  "{{count}} ticket(s)": "{{count}} ticket(s)",
  repository: "dépôt",
  "on this machine": "sur cette machine",
  "wherever the clone is": "là où se trouve le clone",
  "Nothing declares a repository, so its tickets produce a document rather than a pull request.":
    "Rien ne déclare de dépôt : ses tickets produisent un document plutôt qu'une pull request.",
  "from the configuration": "depuis la configuration",
  "path set in the configuration": "chemin fixé dans la configuration",
  "{{count}} of {{total}} on a repository": "{{count}} sur {{total}} sur un dépôt",
  "Reading the projects…": "Lecture des projets…",
  "No project yet — a ticket without one comes back as a document.":
    "Aucun projet pour l'instant — un ticket sans projet revient sous forme de document.",
  "is where a repository is looked for, and cloned into when it is nowhere.":
    "est l'endroit où un dépôt est cherché, et cloné quand il n'est nulle part.",
  "This project could not be read.": "Ce projet n'a pas pu être lu.",
  "No project called “{{name}}”.": "Aucun projet ne s'appelle « {{name}} ».",
  "Nothing is written on this page, so its tickets are told about the workspace and nothing about the project.":
    "Rien n'est écrit sur cette page : ses tickets reçoivent le contexte de l'espace de travail et rien sur le projet.",
  "This project is a line in config.toml and has no page: the board has never heard of it, so there is nothing here to write a brief on.":
    "Ce projet est une ligne de config.toml et n'a pas de page : le tableau n'en a jamais entendu parler, il n'y a donc rien ici sur quoi écrire un brief.",
  "Change its path in the settings.": "Changez son chemin dans les réglages.",
  "This project is a line in config.toml; it is changed in the settings.":
    "Ce projet est une ligne de config.toml ; il se modifie dans les réglages.",
  "What the board calls it. A ticket points at this page, not at this name.":
    "Le nom que lui donne le tableau. Un ticket pointe vers cette page, pas vers ce nom.",
  "owner/repo, or the clone URL. Empty, and its tickets come back as a document.":
    "propriétaire/dépôt, ou l'URL du clone. Vide, ses tickets reviennent sous forme de document.",
  "Only needed where the repository cannot be found on its own. Worktrees are made beside it, never in it.":
    "Utile seulement quand le dépôt ne se trouve pas tout seul. Les worktrees sont créés à côté, jamais dedans.",
  "The audience, the voice, the conventions, the things never to do. Every ticket of this project is told it before it is told the ticket.":
    "Le public, le ton, les conventions, ce qu'il ne faut jamais faire. Chaque ticket de ce projet le reçoit avant de recevoir le ticket.",
  "Write it as you would brief somebody joining the project.":
    "Écrivez-le comme à quelqu'un qui arrive sur le projet.",

  /* -- the standing context --------------------------------------------------- */
  Context: "Contexte",
  "What every ticket is told first.": "Ce qu'on dit d'abord à chaque ticket.",
  "Before the project's brief and before the ticket itself. It is what makes an answer sound like you rather than like nobody — and you pay for it on every single ticket.":
    "Avant le brief du projet et avant le ticket lui-même. C'est ce qui fait qu'une réponse vous ressemble plutôt que de ne ressembler à personne — et vous le payez sur chaque ticket.",
  "{{count}} characters in every prompt": "{{count}} caractères dans chaque prompt",
  Reread: "Relire",
  "Saving…": "Enregistrement…",
  "Reading the context…": "Lecture du contexte…",
  "This workspace has no “{{page}}” page, so there is nowhere to write.":
    "Cet espace de travail n'a pas de page « {{page}} » : il n'y a nulle part où écrire.",
  "Who you are, what the team does, the stack, the conventions, the things never to do. Keep it to one screen.":
    "Qui vous êtes, ce que fait l'équipe, la stack, les conventions, ce qu'il ne faut jamais faire. Tenez-vous à un écran.",
  "saved to the “{{page}}” page, and read again on the next run.":
    "enregistré dans la page « {{page}} », relu à la prochaine passe.",
  "The context is saved": "Le contexte est enregistré",
  "Every ticket from here on is told this.": "Chaque ticket à partir de maintenant le reçoit.",
  "The context was not saved": "Le contexte n'a pas été enregistré",

  /* -- the settings page, in its own words ----------------------------------- */
  "Configure the runner.": "Configurez le runner.",
  "A field left blank says nothing, and the runner’s own default answers — shown greyed beside it. Your tokens stay on the machine: they are never sent to this page.":
    "Un champ laissé vide ne dit rien, et c'est la valeur par défaut du runner qui répond — affichée en gris à côté. Vos jetons restent sur la machine : ils ne sont jamais envoyés à cette page.",
  "Reading the configuration…": "Lecture de la configuration…",
  "could not read the configuration: {{why}}": "impossible de lire la configuration : {{why}}",
  "default · {{value}}": "défaut · {{value}}",
  yes: "oui",
  no: "non",
  nothing: "rien",
  "not set": "non renseigné",
  "set · ends {{preview}}": "renseigné · finit par {{preview}}",
  forget: "oublier",
  "takes effect once": "prend effet une fois que",
  "Written to the file": "Écrit dans le fichier",
  "nothing typed here": "rien de tapé ici",

  /* -- the two `name = value` tables, each a resource of its own -------------
     `Projects`, `Project` and the two section blurbs are already said where
     `web/settings.py` describes the file; only what the rows add is here. */
  "Where it is": "Où il se trouve",
  "Spelled as the project page is, or the ticket finds no repository.":
    "Écrit comme la page du projet l'écrit, sinon le ticket ne trouve aucun dépôt.",
  "The repository itself. Worktrees are made beside it, never in it.":
    "Le dépôt lui-même. Les worktrees sont créés à côté, jamais dedans.",
  "A row with no name maps nothing.": "Une ligne sans nom ne fait correspondre rien.",
  "A project mapped to nothing is a row to remove.":
    "Un projet qui ne mène nulle part est une ligne à retirer.",
  "No mapping here — the project pages carry it.":
    "Aucune correspondance ici — ce sont les pages de projet qui la portent.",
  "add a project": "ajouter un projet",
  "Remove this project": "Retirer ce projet",
  Accounts: "Comptes",
  Owner: "Propriétaire",
  Account: "Compte",
  "As GitHub spells it in the URL of a repository, before the slash.":
    "Tel que GitHub l'écrit dans l'URL d'un dépôt, avant la barre oblique.",
  "The account gh auth status names — logged in once with gh auth login.":
    "Le compte que nomme gh auth status — connecté une fois avec gh auth login.",
  "A row with no owner names nobody.": "Une ligne sans propriétaire ne nomme personne.",
  "An owner mapped to nothing is a row to remove.":
    "Un propriétaire qui ne mène nulle part est une ligne à retirer.",
  "One GitHub here — everything goes out as whoever gh is signed in as.":
    "Un seul GitHub ici — tout part sous le compte auquel gh est connecté.",
  "add an account": "ajouter un compte",
  "Remove this account": "Retirer ce compte",
  "one change, unsaved": "une modification non enregistrée",
  "{{count}} changes, unsaved": "{{count}} modifications non enregistrées",
  revert: "annuler",
  Save: "Enregistrer",
  "saving…": "enregistrement…",
  "one setting": "un réglage",
  "{{count}} settings": "{{count}} réglages",
  "Saved {{how}}: {{names}}.": "Enregistré {{how}} : {{names}}.",
  "Takes effect once {{after}}.": "Prend effet une fois que {{after}}.",
  "Nothing to save — the file already said that.":
    "Rien à enregistrer — le fichier le disait déjà.",
  "Not saved: {{why}}": "Non enregistré : {{why}}",
  "does that token reach your board?": "est-ce que ce jeton atteint votre tableau ?",
  "send yourself a test message": "envoyez-vous un message de test",
  "apply the interval to the timer": "appliquer l'intervalle à la minuterie",

  /* -- the settings page, as `web/settings.py` describes the file ------------- */
  // The server sends one entry per key of `config.toml` — a title, a sentence
  // of help, what has to happen for a change to count — and they arrive in the
  // words that file is written in. Held to it by the test suite.
  Notion: "Notion",
  "The board, and the integration that reads it. `ticket-runner init <page-url>` fills these in by building the databases for you; this is where you look when it has to be done by hand.":
    "Le tableau, et l'intégration qui le lit. `ticket-runner init <page-url>` remplit tout cela en construisant les bases pour vous ; c'est ici que l'on regarde quand il faut le faire à la main.",
  "Integration token": "Jeton d'intégration",
  "The `ntn_…` secret of your internal integration. The board has to be shared with it — a token alone sees nothing.":
    "Le secret `ntn_…` de votre intégration interne. Le tableau doit être partagé avec elle — un jeton seul ne voit rien.",
  "Workspace page": "Page de l'espace de travail",
  "The page that holds Tickets, Projects, Agents and Context. A Notion URL does: only the identifier in it is kept.":
    "La page qui contient Tickets, Projects, Agents et Context. Une URL Notion convient : seul l'identifiant qu'elle contient est gardé.",
  "Tickets database": "Base des tickets",
  "Only if you name no workspace page — the ticket database on its own.":
    "Seulement si vous ne nommez aucune page d'espace de travail — la base des tickets toute seule.",
  "How you call it": "Comment vous l'appelez",
  "The word that asks it to answer in a comment rather than to work. Its own integration name always works too.":
    "Le mot qui lui demande de répondre en commentaire plutôt que de travailler. Le nom de son intégration marche toujours aussi.",

  "The run": "La passe",
  "How often the board is read, how many tickets may run at once, and how long one of them is allowed to take.":
    "À quelle fréquence le tableau est lu, combien de tickets peuvent tourner à la fois, et combien de temps l'un d'eux a le droit de prendre.",
  "Workspace root": "Racine de l'espace de travail",
  "Where your repositories live. Worktrees are made beside them, never in them.":
    "Là où vivent vos dépôts. Les worktrees sont créés à côté d'eux, jamais dedans.",
  "Between two runs (seconds)": "Entre deux passes (secondes)",
  "How long the timer waits before looking at the board again.":
    "Combien de temps la minuterie attend avant de regarder le tableau à nouveau.",
  "`ticket-runner enable` writes it into the systemd timer":
    "`ticket-runner enable` l'écrit dans la minuterie systemd",
  "Tickets at once": "Tickets à la fois",
  "Two sessions on one laptop is already a lot of machine.":
    "Deux sessions sur un portable, c'est déjà beaucoup de machine.",
  "A ticket may take (minutes)": "Un ticket peut prendre (minutes)",
  "Past this, the session is killed and the ticket is put back with the reason.":
    "Passé ce délai, la session est tuée et le ticket est remis en place avec la raison.",
  "Wait when the credits run out": "Attendre quand les crédits sont épuisés",
  "A subscription is metered in windows. When one is spent, the ticket goes back where it came from and nothing is run until the window rolls over — off, an exhausted quota fails every ticket it touches.":
    "Un abonnement se compte par fenêtres. Quand l'une est consommée, le ticket retourne d'où il vient et plus rien ne tourne jusqu'à la fenêtre suivante — désactivé, un quota épuisé fait échouer chaque ticket qu'il touche.",
  "Keep for yourself (%)": "Garder pour vous (%)",
  "The share of each window the runner refuses to touch. At 5 it starts nothing past 95 % of the session or the week — what is already running finishes, and the tickets it did not start stay where they are, ticked as waiting for credit. 0 spends the lot.":
    "La part de chaque fenêtre à laquelle le runner ne touche pas. À 5, il ne lance plus rien au-delà de 95 % de la session ou de la semaine — ce qui tourne déjà va au bout, et les tickets qu'il n'a pas démarrés restent où ils sont, cochés en attente de crédit. 0 consomme tout.",
  "Empty: whatever Claude Code is set to. A ticket's own Model column wins over this one.":
    "Vide : ce que Claude Code utilise. La colonne Model d'un ticket l'emporte sur celui-ci.",
  "Answer in": "Répondre en",
  "The language the runner writes its reports in, and the one a session is asked to answer in. Empty: it reports in English, and each session keeps writing in the language it was written to.":
    "La langue dans laquelle le runner écrit ses comptes rendus, et celle dans laquelle on demande à une session de répondre. Vide : il rend compte en anglais, et chaque session continue d'écrire dans la langue qu'on lui a adressée.",
  "Permission mode": "Mode de permission",
  "How much a ticket's session may do without asking. Nobody is watching it: anything but `bypassPermissions` is a session that will sit waiting.":
    "Ce que la session d'un ticket a le droit de faire sans demander. Personne ne la regarde : autre chose que `bypassPermissions`, c'est une session qui restera à attendre.",
  "Dry run": "À blanc",
  "Say what would happen and touch nothing — no branch, no commit, no Notion write. The one switch to leave on while you are still deciding.":
    "Dire ce qui se passerait et ne toucher à rien — pas de branche, pas de commit, rien d'écrit dans Notion. L'interrupteur à laisser actif tant que vous hésitez encore.",
  "Keep session logs (days)": "Garder les journaux de session (jours)",
  "0 keeps them forever.": "0 les garde pour toujours.",

  "Every other model": "Tous les autres modèles",
  "One key in front of every provider there is. It goes into each session's environment as `OPENROUTER_API_KEY`, so the work itself can call whatever model it needs — a GPT, an image, a transcription, a video — and pay for it. Running the sessions themselves on it is the second switch, and it changes who answers them.":
    "Une seule clé devant tous les fournisseurs qui existent. Elle entre dans l'environnement de chaque session sous le nom `OPENROUTER_API_KEY`, pour que le travail lui-même puisse appeler le modèle dont il a besoin — un GPT, une image, une transcription, une vidéo — et le payer. Faire tourner les sessions elles-mêmes dessus, c'est le second interrupteur, et il change qui leur répond.",
  "OpenRouter key": "Clé OpenRouter",
  "The `sk-or-…` one, from openrouter.ai/keys. On its own it only makes the key reachable from a session; nothing about the runner changes.":
    "Celle en `sk-or-…`, depuis openrouter.ai/keys. Seule, elle rend simplement la clé accessible depuis une session ; rien ne change pour le runner.",
  "Run the sessions on it": "Faire tourner les sessions dessus",
  "Claude Code then talks to OpenRouter rather than to Anthropic, and every model named — a ticket's Model column, an agent's, the one above — becomes an OpenRouter slug: `openai/gpt-5`, `anthropic/claude-sonnet-4.5`. Two things go with it: the CLI is no longer signed in as you, so Claude in Chrome does not load, and the bill is OpenRouter's rather than your subscription's — there is no window left to wait for.":
    "Claude Code parle alors à OpenRouter plutôt qu'à Anthropic, et chaque modèle nommé — la colonne Model d'un ticket, celle d'un agent, celui ci-dessus — devient un identifiant OpenRouter : `openai/gpt-5`, `anthropic/claude-sonnet-4.5`. Deux choses vont avec : le CLI n'est plus connecté en votre nom, donc Claude in Chrome ne se charge pas, et la facture est celle d'OpenRouter plutôt que celle de votre abonnement — il n'y a plus de fenêtre à attendre.",
  Endpoint: "Point d'accès",
  "Where that key is spent. Only worth touching for a gateway of your own that speaks the same API.":
    "Là où cette clé est dépensée. Ne vaut la peine d'être changé que pour une passerelle à vous qui parle la même API.",

  "Git and pull requests": "Git et pull requests",
  "What a ticket with a repository turns into, and how it is accepted.":
    "Ce que devient un ticket avec un dépôt, et comment il est accepté.",
  "Branch prefix": "Préfixe de branche",
  "`ticket/` gives `ticket/1a2b3c4d-remove-the-header`.":
    "`ticket/` donne `ticket/1a2b3c4d-remove-the-header`.",
  "Base branch": "Branche de base",
  "Empty: whatever the repository's HEAD points at.": "Vide : ce que le HEAD du dépôt désigne.",
  "Fetch before branching": "Fetch avant de brancher",
  "So a ticket does not start from last week.":
    "Pour qu'un ticket ne parte pas de la semaine dernière.",
  "Push the branch": "Pousser la branche",
  "Open a pull request": "Ouvrir une pull request",
  "Needs `gh` to be installed and logged in.": "Demande que `gh` soit installé et connecté.",
  "Replay the branch before the pull request": "Rejouer la branche avant la pull request",
  "A session takes an hour and the base branch does not wait for it. The branch is put back on top of it before the push, and a validated merge refused for being behind is retried once after the same gesture.":
    "Une session prend une heure et la branche de base ne l'attend pas. La branche est remise par-dessus avant le push, et une fusion validée refusée pour retard est retentée une fois après le même geste.",
  "Merge a validated ticket by": "Fusionner un ticket validé par",
  "What `gh pr merge` is told when you move a ticket to Validated.":
    "Ce qu'on dit à `gh pr merge` quand vous déplacez un ticket vers Validé.",
  "Keep the worktree on failure": "Garder le worktree en cas d'échec",
  "The state a failed session died in, for you to look at. `ticket-runner clean --force` sweeps them.":
    "L'état dans lequel une session échouée est morte, pour que vous puissiez le regarder. `ticket-runner clean --force` fait le ménage.",

  "What comes back on its own": "Ce qui revient tout seul",
  "The Schedules database, read in the same pass that reads the board. A row there describes a ticket and how often it is born; everything after that is an ordinary ticket. Catching up creates one occurrence, never the twelve a machine that was off has missed.":
    "La base Schedules, lue dans la même passe que le tableau. Une ligne y décrit un ticket et la fréquence à laquelle il naît ; tout le reste est un ticket ordinaire. Le rattrapage crée une occurrence, jamais les douze qu'une machine éteinte a manquées.",
  "Let schedules make tickets": "Laisser les récurrences créer des tickets",
  "Off: the database is read by nobody, and no row has to be unticked. A workspace with no schedules page never had any of this anyway.":
    "Désactivé : la base n'est lue par personne, et aucune ligne n'a besoin d'être décochée. Un espace de travail sans page de récurrences n'avait de toute façon rien de tout cela.",

  "While it runs": "Pendant que ça tourne",
  "The parts that report as the work happens: the Progress column, the session links, and the answers written under a ticket's comments.":
    "Les parties qui rendent compte au fil du travail : la colonne Progress, les liens de session, et les réponses écrites sous les commentaires d'un ticket.",
  "Write progress into the ticket": "Écrire l'avancement dans le ticket",
  "The board's live column: what the session is doing, as it does it.":
    "La colonne vivante du tableau : ce que fait la session, pendant qu'elle le fait.",
  "Progress cadence (seconds)": "Cadence de l'avancement (secondes)",
  "The floor is five: below it, two tickets at once spend the integration's rate limit on saying what they are about to do.":
    "Le plancher est à cinq : en dessous, deux tickets à la fois dépensent la limite de l'intégration à dire ce qu'ils s'apprêtent à faire.",
  "Link the session on the ticket": "Lier la session sur le ticket",
  "A `ticket-runner://` link that reopens the very session in a terminal.":
    "Un lien `ticket-runner://` qui rouvre exactement cette session dans un terminal.",
  "Session host": "Machine de la session",
  "Set it when the runner is not on the machine you click from — the link then says which machine to open it on.":
    "À renseigner quand le runner n'est pas sur la machine depuis laquelle vous cliquez — le lien dit alors sur quelle machine l'ouvrir.",
  "Answer in the comments": "Répondre dans les commentaires",
  "A comment under one of its reports is answered, in the thread, by something that has read the ticket and the repository.":
    "Un commentaire sous l'un de ses comptes rendus reçoit une réponse, dans le fil, de quelque chose qui a lu le ticket et le dépôt.",
  "Look for comments every (seconds)": "Chercher les commentaires toutes les (secondes)",
  "Tickets scanned for comments": "Tickets scrutés pour les commentaires",
  "An answer may take (minutes)": "Une réponse peut prendre (minutes)",
  "Permission mode for answers": "Mode de permission des réponses",
  "`plan` is the guardrail: a conversation that quietly edited a repository is the one thing nobody would expect of it.":
    "`plan` est le garde-fou : une conversation qui modifierait discrètement un dépôt est bien la seule chose que personne n'attend d'elle.",

  Prompts: "Prompts",
  "The three briefs the runner writes, each replaceable by a file of your own. Leave them empty to keep the ones built in.":
    "Les trois briefs que le runner écrit, chacun remplaçable par un fichier à vous. Laissez-les vides pour garder ceux d'origine.",
  "A ticket with a repository": "Un ticket avec un dépôt",
  "A ticket without one": "Un ticket sans dépôt",
  "A validated ticket, being published": "Un ticket validé, en cours de publication",

  "Being told": "Être prévenu",
  "Where the runner reaches you, and whether it listens for an answer. What you reply on Telegram or Slack becomes a comment on the ticket, which is already what wakes a blocked one.":
    "Où le runner vous joint, et s'il écoute une réponse. Ce que vous répondez sur Telegram ou Slack devient un commentaire sur le ticket, ce qui est déjà ce qui réveille un ticket bloqué.",
  "Notify this machine's screen": "Prévenir sur l'écran de cette machine",
  "Read what you write back": "Lire ce que vous répondez",
  "Off: it still tells you things, it just never listens.":
    "Désactivé : il continue de vous dire les choses, il n'écoute simplement jamais.",
  "Worth a message": "Mérite un message",
  "`blocked` is the one that expects something back from you; `done` is the pull request waiting; `failed` is a log to read.":
    "`blocked` est celui qui attend quelque chose de vous ; `done`, c'est la pull request qui patiente ; `failed`, c'est un journal à lire.",
  "Telegram bot token": "Jeton du bot Telegram",
  "From @BotFather. `ticket-runner notify --pair` then finds the chat id.":
    "Chez @BotFather. `ticket-runner notify --pair` trouve ensuite l'identifiant de conversation.",
  "Telegram chat id": "Identifiant de conversation Telegram",
  "Only that chat is ever read: a bot token is a public address.":
    "Seule cette conversation est lue : un jeton de bot est une adresse publique.",
  "Slack bot token": "Jeton du bot Slack",
  "The `xoxb-…` one. Scopes: `chat:write`, and `channels:history` (`groups:history`, `im:history`) to read your replies.":
    "Celui en `xoxb-…`. Scopes : `chat:write`, et `channels:history` (`groups:history`, `im:history`) pour lire vos réponses.",
  "Slack channel id": "Identifiant de canal Slack",
  "··· → View channel details, at the bottom. And `/invite @your-bot` in the channel — the step everyone forgets.":
    "··· → Afficher les détails du canal, tout en bas. Et `/invite @votre-bot` dans le canal — l'étape que tout le monde oublie.",

  "This console": "Cette console",
  "Behind this port sits a runner that starts Claude Code sessions with `bypassPermissions`. Anything that can reach it can run code on this machine, as you — which is why the bind is loopback and why widening it is a decision you have to take on purpose, token included.":
    "Derrière ce port se tient un runner qui démarre des sessions Claude Code en `bypassPermissions`. Tout ce qui peut l'atteindre peut exécuter du code sur cette machine, en votre nom — c'est pourquoi l'écoute est en loopback, et pourquoi l'ouvrir plus largement est une décision à prendre exprès, jeton compris.",
  "Bind address": "Adresse d'écoute",
  "Anything but `127.0.0.1` is refused unless a token, or a sign-in, is set below. The answer that does not depend on a secret never leaking is an ssh tunnel: `ssh -L 8787:127.0.0.1:8787 <this machine>`.":
    "Tout autre chose que `127.0.0.1` est refusé tant qu'aucun jeton, ni aucune connexion, n'est renseigné plus bas. La réponse qui ne dépend pas d'un secret qui ne fuite jamais, c'est un tunnel ssh : `ssh -L 8787:127.0.0.1:8787 <cette machine>`.",
  "the console has to be restarted": "la console doit être redémarrée",
  Port: "Port",
  "Console token": "Jeton de la console",
  "Empty: one is drawn once and kept in `~/.local/state/ticket-runner/web/token`. Setting one here is what allows a non-loopback bind.":
    "Vide : un jeton est tiré une fois et gardé dans `~/.local/state/ticket-runner/web/token`. En renseigner un ici est ce qui autorise une écoute hors loopback.",
  "the console has to be restarted, and this page reopened with the new token":
    "la console doit être redémarrée, et cette page rouverte avec le nouveau jeton",
  "Sign in with this email": "Se connecter avec cette adresse e-mail",
  "Set it with a password and the console asks for the two instead of for the token — a page you open from a bookmark rather than from a secret. `TICKET_RUNNER_WEB_EMAIL` says the same thing and wins over this.":
    "Renseignez-la avec un mot de passe et la console demande les deux plutôt que le jeton — une page qu'on ouvre depuis un marque-page et non depuis un secret. `TICKET_RUNNER_WEB_EMAIL` dit la même chose et l'emporte sur ce champ.",
  "And this password": "Et ce mot de passe",
  "Kept in the file beside the other secrets, or in `TICKET_RUNNER_WEB_PASSWORD`, which wins over it. Changing it signs out every browser at once; the token keeps working, for scripts.":
    "Gardé dans le fichier à côté des autres secrets, ou dans `TICKET_RUNNER_WEB_PASSWORD`, qui l'emporte sur lui. Le changer déconnecte tous les navigateurs d'un coup ; le jeton, lui, continue de marcher, pour les scripts.",
  "Reread the board every (seconds)": "Relire le tableau toutes les (secondes)",
  "Only while a browser is connected.": "Seulement tant qu'un navigateur est connecté.",
  "A chat turn may take (minutes)": "Un tour de conversation peut prendre (minutes)",

  "Staying up to date": "Rester à jour",
  "A run asks the remote whether the installed code is still the newest.":
    "Une passe demande au dépôt distant si le code installé est encore le plus récent.",
  "Update itself between two runs": "Se mettre à jour entre deux passes",
  "Ask at most every (seconds)": "Demander au plus toutes les (secondes)",
  "One desktop notification per ticket": "Une notification bureau par ticket",
  "The old switch, kept: “Notify this machine's screen” above defaults to it.":
    "L'ancien interrupteur, conservé : « Prévenir sur l'écran de cette machine » ci-dessus s'y replie par défaut.",

  "Where the board lives": "Où vit le tableau",
  "Notion is the default and changes nothing. Markdown is the same board as files on disk, and never asks Notion anything — no token, no sharing, no network. Both keeps the two in step.":
    "Notion est le choix par défaut et ne change rien. Markdown, c'est le même tableau sous forme de fichiers, sans jamais rien demander à Notion — ni jeton, ni partage, ni réseau. Both tient les deux au même pas.",
  "The board": "Le tableau",
  "`notion` reads and writes Notion, as it always has. `markdown` reads and writes files. `both` does the two, and reconciles them.":
    "`notion` lit et écrit dans Notion, comme toujours. `markdown` lit et écrit des fichiers. `both` fait les deux, et les réconcilie.",
  "Where the files are": "Où sont les fichiers",
  "One directory, with `tickets/`, `projects/`, `agents/`, `schedules/` and `context.md` in it. A directory you can put under git, which is most of the point.":
    "Un répertoire, avec `tickets/`, `projects/`, `agents/`, `schedules/` et `context.md` dedans. Un répertoire que vous pouvez mettre sous git, ce qui est presque tout l'intérêt.",
  "When the two disagree": "Quand les deux divergent",
  "A page changed on both sides since the last reconciliation. `newest` keeps the later of the two — and writes the other into the journal, so nothing is lost quietly.":
    "Une page modifiée des deux côtés depuis la dernière réconciliation. `newest` garde la plus récente — et écrit l'autre dans le journal, pour que rien ne se perde en silence.",
  "Reconcile before every pass": "Réconcilier avant chaque passe",
  "Off, and the two boards only meet when you run `ticket-runner sync`.":
    "Désactivé, les deux tableaux ne se rencontrent que lorsque vous lancez `ticket-runner sync`.",

  Projects: "Projets",
  "A Notion project, and the repository it means on this machine. Only needed when the project page says nothing: a `path` or a `github` property on the page keeps the mapping on the board, where every machine can read it.":
    "Un projet Notion, et le dépôt qu'il désigne sur cette machine. Utile seulement quand la page du projet ne dit rien : une propriété `path` ou `github` sur la page garde la correspondance sur le tableau, où toutes les machines peuvent la lire.",

  "Your GitHub accounts": "Vos comptes GitHub",
  "One machine often answers to two GitHubs — your own and a client's — and `gh` only ever has one of them active, so a pull request on the other is refused for reasons that read like a bug. On the left the owner, as GitHub spells it in a repository's URL; on the right the account, as `gh auth status` lists it. Log each one in once with `gh auth login` and they stay signed in side by side. An owner nobody names here is worked under whichever account `gh` is active as, which is what one GitHub has always done.":
    "Une machine répond souvent à deux GitHub — le vôtre et celui d'un client — et `gh` n'en a jamais qu'un d'actif : une pull request sur l'autre est refusée pour des raisons qui ressemblent à un bug. À gauche le propriétaire, tel que GitHub l'écrit dans l'URL d'un dépôt ; à droite le compte, tel que `gh auth status` le liste. Connectez chacun une fois avec `gh auth login` et ils restent connectés côte à côte. Un propriétaire que personne ne nomme ici est travaillé sous le compte actif de `gh`, ce qu'un seul GitHub a toujours fait.",

  "The columns of your board": "Les colonnes de votre tableau",
  "What each moment is called in your Notion. Empty means the default, and the defaults are not arbitrary: leaving `blocked` unset while naming `failed` is how you say your board has one column for both.":
    "Comment chaque moment s'appelle dans votre Notion. Vide signifie la valeur par défaut, et les valeurs par défaut ne sont pas arbitraires : laisser `blocked` vide tout en nommant `failed`, c'est dire que votre tableau n'a qu'une colonne pour les deux.",
  ready: "prêt",
  "the column the runner claims from": "la colonne dans laquelle le runner se sert",
  running: "en cours",
  "where it puts a ticket it has taken": "où il met un ticket qu'il a pris",
  review: "en revue",
  "a pull request is waiting for you": "une pull request vous attend",
  validated: "validé",
  "you accepted it — the runner merges, or publishes":
    "vous l'avez accepté — le runner fusionne, ou publie",
  "in, and closed": "rentré, et clos",
  failed: "échoué",
  "something broke; there is a log to read": "quelque chose a cassé ; il y a un journal à lire",
  blocked: "bloqué",
  "it asked you something and is waiting": "il vous a demandé quelque chose et attend",

  "The columns of the ticket database": "Les colonnes de la base des tickets",
  "What each property is called. The optional ones change nothing by their absence: a database without a Cost column is a database that is not told what a ticket cost.":
    "Comment chaque propriété s'appelle. Les facultatives ne changent rien par leur absence : une base sans colonne Cost est une base à qui l'on ne dit pas ce qu'un ticket a coûté.",
  status: "statut",
  required: "obligatoire",
  "relation to the projects database": "relation vers la base des projets",
  agent: "agent",
  "which machine took the ticket": "quelle machine a pris le ticket",
  "written back when one is opened": "réécrite quand une pull request est ouverte",
  "the link that reopens the session": "le lien qui rouvre la session",
  "per-ticket model, overriding the one above":
    "modèle par ticket, qui l'emporte sur celui ci-dessus",
  "which ready ticket goes first": "quel ticket prêt passe en premier",
  cost: "coût",
  "written back, in dollars": "réécrit, en dollars",
  duration: "durée",
  "written back, in minutes": "réécrite, en minutes",
  progress: "avancement",
  "what the session is doing right now": "ce que la session est en train de faire",
  due: "échéance",
  "a date here holds the ticket until that moment":
    "une date ici retient le ticket jusqu'à ce moment",
  waiting: "en attente",
  "ticked while the credit is out — it comes back on its own":
    "cochée tant que le crédit est épuisé — il repart tout seul",
  role: "rôle",
  "relation to the agents database": "relation vers la base des agents",
  cadence: "cadence",
  "schedules: Hourly, Daily, Weekly or Monthly":
    "récurrences : Hourly, Daily, Weekly ou Monthly",
  at: "heure",
  "schedules: the hour, written 09:00": "récurrences : l'heure, écrite 09:00",
  day: "jour",
  "schedules: Monday, or 1 to 31": "récurrences : Monday, ou 1 à 31",
  active: "active",
  "schedules: unticked stops it, deleting nothing":
    "récurrences : décochée, elle s'arrête sans rien supprimer",
  "next run": "prochaine passe",
  "schedules: written back — the next birth": "récurrences : réécrite — la prochaine naissance",
  "last run": "dernière passe",
  "schedules: written back — the last one": "récurrences : réécrite — la dernière",
  "last ticket": "dernier ticket",
  "schedules: written back — what the last occurrence made":
    "récurrences : réécrit — ce qu'a produit la dernière occurrence",

  "The rows of the workspace page": "Les lignes de la page d'espace de travail",
  "The titles the runner looks for under your workspace page. Only Tickets is required; the others change nothing by their absence.":
    "Les titres que le runner cherche sous votre page d'espace de travail. Seule Tickets est obligatoire ; les autres ne changent rien par leur absence.",
  tickets: "tickets",
  projects: "projets",
  "a ticket's repository is found through it": "c'est par elle qu'on trouve le dépôt d'un ticket",
  agents: "agents",
  "the crafts a ticket can be handled by": "les métiers par lesquels un ticket peut être traité",
  context: "contexte",
  "who the work is for, read into every prompt":
    "pour qui le travail est fait, lu dans chaque prompt",
  "what repeats — absent means nothing does":
    "ce qui se répète — absente, rien ne se répète",
}
