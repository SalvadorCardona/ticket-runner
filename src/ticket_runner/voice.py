"""What the runner says on a ticket, and the language it says it in.

Three kinds of text come out of a run, and only one of them is written here.
The **work** — a summary, a document, an answer in a thread — is written by the
session, and `prompt.py` is where it is told which language to write it in. The
**journal** on the terminal is written for whoever is watching a terminal, and
that person is standing in front of the machine. What is left is what the runner
says *on the ticket*: the report under a finished one, the question a blocked
one asks, the line that reaches a phone. That is this module.

Two decisions hold it together.

- **A language is a setting, and English is what it falls back on.**
  `runner.language` names it; a locale, a language written out in full, a
  capitalised code all read down to one of the two spoken here, and anything
  unrecognised is English rather than a failure — a typo in a language name is
  not a reason for a ticket to come back unreported. An empty setting is the
  runner as it always was, and that is the point of it being empty.
- **The first line of a comment is a notification.** Notion pushes a comment to
  the phone as it stands, cut after two or three lines, so the first line is all
  there is: it gets a mark, the verdict as an action — *to review*, *stuck* —
  and the figures that place it, and nothing else. One sentence follows, cut at
  `BRIEF` characters, then a link if there is one. What used to be under that —
  the host that wrote it, the session id, the log path — is not lost, it is read
  off the board's own columns and off the folded block the run leaves on the
  page, which is where somebody looks on the rare day a run went wrong.

One thing a report carries is deliberately not here: the note `git.add_worktree`
writes when a ticket runs a second time on a branch it already had. That
sentence is made of facts only git has, it is read by the session as much as by
you, and translating it would mean `git.py` knowing there is such a thing as a
language. It stays English until there is a reason for that module to have a
voice at all.

Adding a language is adding a column to `_SAID`. The keys stay English, because
the code that calls them is English, and a key nobody translated shows up as a
`KeyError` the first time it is said rather than as a sentence in the wrong
language six months later.
"""

from __future__ import annotations

# The two the runner speaks. English is less a default than the language the
# tool was written in: everything it says was written there first.
LANGUAGES = ("en", "fr")
DEFAULT = "en"

# What a configuration file may reasonably say for each of them.
_SPELLINGS = {
    "en": ("en", "eng", "english", "anglais"),
    "fr": ("fr", "fra", "fre", "french", "français", "francais"),
}


# How long a sentence may be under a verdict. Two hundred characters is about
# what a phone shows before it gives up, and the prompt asks for one sentence:
# this is what happens when it is answered with three.
BRIEF = 200

# The mark every report opens with, one per verdict. It is read by a person at a
# glance — green is nothing to do, the hand is a question — and by the runner, as
# the thing that tells its own comment from your answer: see `is_report`.
MARKS = {
    "review": "✅",
    "read": "✅",
    "merged": "✅",
    "published": "✅",
    "blocked": "🙋",
    "failed": "⚠️",
    "waiting": "⏸️",
    "requeued": "↩️",
}

# How every report opened until the marks arrived: `ticket-runner@<host> — `.
# Still recognised, and only recognised — nothing writes it any more. A board
# does not start over when the runner is updated, and the comments already on it
# have to keep being read as ours.
SIGNATURE = "ticket-runner@"


def is_report(text: str) -> bool:
    """Was this comment written by a run, rather than by a person?

    The honest answer is `conversation.ours`, which asks Notion who wrote it.
    This is the fallback for the boards where Notion will not say — an
    integration without *Read user information* — and it reads the only thing a
    report has that an answer does not: the mark it opens with.
    """
    said = str(text or "").lstrip()
    return said.startswith(tuple(MARKS.values())) or said.startswith(SIGNATURE)


def plain(text: str) -> str:
    """A report without the host an older run signed it with.

    Reports made before the marks open with `ticket-runner@laptop — done.`, and
    the host is exactly the part nobody needs — least of all the session about
    to read the thread back as context.
    """
    first, newline, rest = str(text or "").partition("\n")
    if first.lstrip().startswith(SIGNATURE):
        first = first.split("—", 1)[-1].strip()
    return first + newline + rest


def understood(raw: str) -> str:
    """The language a file asked for, as one of the two this speaks.

    `fr`, `FR`, `fr-FR`, `french`, `Français` all mean the same thing, and so
    does the region nobody meant to specify: only what comes before the dash is
    read. Anything else is English — see the module's second paragraph.
    """
    wanted = str(raw or "").strip().lower().replace("_", "-").split("-")[0]
    for language, spellings in _SPELLINGS.items():
        if wanted in spellings:
            return language
    return DEFAULT


# One entry per thing the runner has to say, in every language it says it in.
# Grouped as a run goes: the verdict a report opens with, the facts that place
# it, what a failure is called, and what reaches a phone.
_SAID: dict[str, dict[str, str]] = {
    # -- the verdict, which is the notification -------------------------------
    # One word each, and each one says what is expected *of you*: “done” was
    # true and useless, since it left the reader to work out whether anything
    # was being asked. Every one of these is preceded by its mark — see `MARKS`
    # — and followed by the figures that place it.
    "verdict-review": {"en": "To review", "fr": "À relire"},
    "verdict-read": {"en": "To read", "fr": "À lire"},
    "verdict-merged": {"en": "Merged", "fr": "Fusionnée"},
    "verdict-published": {"en": "Published", "fr": "Publié"},
    "verdict-blocked": {"en": "Stuck", "fr": "Bloqué"},
    "verdict-failed": {"en": "Failed", "fr": "Échec"},
    "verdict-waiting": {"en": "Waiting", "fr": "En attente"},
    "verdict-requeued": {"en": "Back in the queue", "fr": "Remis dans la file"},
    # -- the facts that go on the same line -----------------------------------
    # Short enough to be read in a row, and in the order somebody reads them:
    # where the work is, how much of it there is, what it took.
    "pull-request": {"en": "PR #{number}", "fr": "PR #{number}"},
    "on-branch": {"en": "branch `{branch}`", "fr": "branche `{branch}`"},
    "in-the-page": {"en": "answer in the page", "fr": "réponse dans la page"},
    "merged-with": {"en": "{method} merge", "fr": "fusion en {method}"},
    "merged-before": {"en": "already merged", "fr": "déjà fusionnée"},
    "credits-out": {
        "en": "out of credit, back in “{status}” until {when}",
        "fr": "crédits épuisés, retour dans « {status} » jusqu'à {when}",
    },
    "abandoned": {
        "en": "nobody was working on it any more, {minutes} after the last trace",
        "fr": "plus personne ne s'en occupait, {minutes} après la dernière trace",
    },
    # -- the one sentence under a verdict -------------------------------------
    "answer-here": {
        "en": "An answer here or on your phone — yes, no, or a sentence — and it runs "
        "again on the next pass.",
        "fr": "Une réponse ici ou sur ton téléphone — oui, non, ou une phrase — et il "
        "repart au prochain passage.",
    },
    "trace-in-page": {
        "en": "What it did is in the folded block at the bottom of the page.",
        "fr": "Ce qu'il a fait est dans le bloc replié en bas de la page.",
    },
    "trace": {
        "en": "To pick the session back up: `{resume}`{picker}. Its log is `{log}`.",
        "fr": "Pour reprendre la session : `{resume}`{picker}. Son journal est `{log}`.",
    },
    "trace-picker": {
        "en": ", or from `claude` in `{home}`",
        "fr": ", ou depuis `claude` dans `{home}`",
    },
    # -- a ticket that did not ------------------------------------------------
    "no-project": {
        "en": "I could not find its project on this machine",
        "fr": "je n'ai pas trouvé son projet sur cette machine",
    },
    "unreadable": {
        "en": "I could not read what the ticket says",
        "fr": "je n'ai pas réussi à lire ce que dit le ticket",
    },
    "empty-ticket": {
        "en": "there is nothing here to work from — no title, and no description",
        "fr": "il n'y a rien pour commencer — ni titre, ni description",
    },
    "empty-ticket-detail": {
        "en": "A title, or the template's headings filled in, and back to the ready column.",
        "fr": "Un titre, ou les rubriques du modèle remplies, et retour dans la colonne prête.",
    },
    "no-session": {
        "en": "the Claude session would not start",
        "fr": "la session Claude n'a pas voulu démarrer",
    },
    "no-worktree": {
        "en": "I could not make the worktree to work in",
        "fr": "je n'ai pas pu créer le worktree pour travailler",
    },
    "asked-something": {
        "en": "the session stopped to ask you something",
        "fr": "la session s'est arrêtée pour poser une question",
    },
    "session-failed": {
        "en": "the session did not make it to the end",
        "fr": "la session n'est pas allée au bout",
    },
    "no-answer": {
        "en": "the session stopped without writing an answer",
        "fr": "la session s'est arrêtée sans écrire de réponse",
    },
    "no-answer-detail": {
        "en": "{summary}\n\nNothing was written to ANSWER.md.",
        "fr": "{summary}\n\nRien n'a été écrit dans ANSWER.md.",
    },
    "nothing-committed": {
        "en": "the session called itself done without committing anything",
        "fr": "la session s'est déclarée terminée sans un seul commit",
    },
    "push-refused": {
        "en": "the commits are there, but pushing them was refused",
        "fr": "les commits sont là, mais leur push a été refusé",
    },
    "push-refused-detail": {
        "en": "The branch `{branch}` is kept here, so nothing is lost.",
        "fr": "La branche `{branch}` est conservée ici, donc rien n'est perdu.",
    },
    "answer-not-written": {
        "en": "I could not write the answer into the ticket",
        "fr": "je n'ai pas pu écrire la réponse dans le ticket",
    },
    "answer-on-disk": {
        "en": "It is still on disk, at `{path}`.",
        "fr": "Elle est toujours sur le disque, dans `{path}`.",
    },
    "not-published": {
        "en": "it was validated, but publishing it did not work",
        "fr": "il a été validé, mais la publication n'a pas fonctionné",
    },
    "pull-request-closed": {
        "en": "it was validated, but its pull request was closed rather than merged",
        "fr": "il a été validé, mais sa pull request a été fermée au lieu d'être fusionnée",
    },
    "pull-request-closed-detail": {
        "en": "{url}\n\nReopen it, or bring the ticket back to the ready column.",
        "fr": "{url}\n\nÀ rouvrir, ou à ramener le ticket dans la colonne prête.",
    },
    "pull-request-closed-question": {
        "en": "Its pull request was closed rather than merged: {url}",
        "fr": "Sa pull request a été fermée au lieu d'être fusionnée : {url}",
    },
    "merge-refused": {
        "en": "the pull request would not merge",
        "fr": "la pull request n'a pas voulu fusionner",
    },
    "merge-refused-question": {
        "en": "GitHub refused the merge: {error}",
        "fr": "GitHub a refusé la fusion : {error}",
    },
    "no-pull-request": {
        "en": "it was validated, but there is no pull request to merge",
        "fr": "il a été validé, mais il n'y a aucune pull request à fusionner",
    },
    "no-pull-request-detail": {
        "en": (
            "Its project — {project} — is a repository, so there is nothing to publish "
            "either. Was the pull request ever opened?"
        ),
        "fr": (
            "Son projet — {project} — est un dépôt, donc il n'y a rien à publier non "
            "plus. La pull request a-t-elle seulement été ouverte ?"
        ),
    },
    "no-pull-request-question": {
        "en": "This ticket was validated but carries no pull request.",
        "fr": "Ce ticket a été validé mais ne porte aucune pull request.",
    },
    "worktree-kept": {
        "en": "The worktree is kept as it was left: `{path}`, on branch `{branch}`.",
        "fr": "Le worktree est conservé tel quel : `{path}`, sur la branche `{branch}`.",
    },
    "workdir-kept": {
        "en": "The working directory is kept as it was left: `{path}`.",
        "fr": "Le répertoire de travail est conservé tel quel : `{path}`.",
    },
    "no-pull-request-opened": {
        "en": "The pull request could not be opened: {error}",
        "fr": "La pull request n'a pas pu être ouverte : {error}",
    },
    # -- a run with nothing left to spend -------------------------------------
    "credit-spent-kept": {
        "en": "What the session had already committed is kept on `{branch}`.",
        "fr": "Ce que la session avait déjà commité est conservé sur `{branch}`.",
    },
    # -- a run that died in the middle ---------------------------------------
    "abandoned-requeued": {
        "en": "I am picking it up again from the start.",
        "fr": "Je le reprends depuis le début.",
    },
    # -- talking in a thread --------------------------------------------------
    "no-reply": {
        "en": "I could not answer this one: {error}.\nIts log is `{log}`.",
        "fr": "Je n'ai pas réussi à répondre à celle-ci : {error}.\nSon journal est `{log}`.",
    },
    "said-nothing": {
        "en": "the session ended without saying anything",
        "fr": "la session s'est terminée sans rien dire",
    },
    # -- what reaches a phone -------------------------------------------------
    # The title of a desktop or Telegram notification, where the ticket has to
    # be named — Notion puts the page's own name above the comment, and these
    # two have nothing but what they are handed. The words are the verdicts'.
    "headline": {"en": "{verdict} · {title}", "fr": "{verdict} · {title}"},
    "publication-interrupted": {
        "en": "its publication was interrupted — did it go out? If not, back to “{origin}”",
        "fr": "sa publication a été interrompue — est-elle partie ? Sinon, retour "
        "dans « {origin} »",
    },
    # -- answering from Telegram or Slack -------------------------------------
    "noted": {
        "en": "✓ noted on “{title}” — it runs again in a moment.",
        "fr": "✓ noté sur « {title} » — il repart dans un instant.",
    },
    "nothing-waiting": {
        "en": (
            "Nothing here is waiting on an answer — reply under the question itself, "
            "or name the ticket."
        ),
        "fr": (
            "Rien n'attend de réponse ici — répondre sous la question elle-même, "
            "ou nommer le ticket."
        ),
    },
    "notion-refused": {
        "en": "Notion refused that answer: {error}",
        "fr": "Notion a refusé cette réponse : {error}",
    },
    # -- counted things -------------------------------------------------------
    # Both languages happen to make their plural the same way here, which is
    # luck and not a rule: the day one of them does not, this is where it says so.
    "commit": {"en": "{count} commit", "fr": "{count} commit"},
    "commits": {"en": "{count} commits", "fr": "{count} commits"},
    "block": {"en": "{count} block", "fr": "{count} bloc"},
    "blocks": {"en": "{count} blocks", "fr": "{count} blocs"},
    "step": {"en": "{count} step", "fr": "{count} étape"},
    "steps": {"en": "{count} steps", "fr": "{count} étapes"},
    "minute": {"en": "{count} minute", "fr": "{count} minute"},
    "minutes": {"en": "{count} minutes", "fr": "{count} minutes"},
    "under-a-minute": {"en": "under a minute", "fr": "moins d'une minute"},
    # -- the folded block a run leaves on the page ----------------------------
    # Its title, while the session runs and once it is over. A failed run calls
    # it a trace, because that is what somebody opens it for.
    "live": {"en": "Live", "fr": "En cours"},
    "live-trace": {"en": "Trace", "fr": "Trace"},
    "live-interrupted": {"en": "interrupted", "fr": "interrompu"},
    "live-stopped": {"en": "stopped", "fr": "arrêté"},
    "live-blocked": {"en": "it asked a question", "fr": "il a posé une question"},
    "live-waiting": {
        "en": "out of credit — it will be picked up again",
        "fr": "crédits épuisés — il sera repris",
    },
    # -- what the session is told to write in ---------------------------------
    # Not a report: the sentence handed to `prompt.build`, which is why it is
    # written *to* the session and not about it — and why both rows are in
    # English. A prompt is written in one language whatever it asks for, and a
    # brief that switched languages halfway would be one more thing for the
    # session to interpret.
    "instruction": {
        "en": (
            "Write in English — your report, the final line below, and anything you "
            "write back into the ticket. Code, commit messages and identifiers keep the "
            "language the repository already uses."
        ),
        "fr": (
            "Write in French — your report, the final line below, and anything you write "
            "back into the ticket. Code, commit messages and identifiers keep the "
            "language the repository already uses."
        ),
    },
    "instruction-reply": {
        "en": "Answer in English, whatever language the message you are answering is in.",
        "fr": "Answer in French, whatever language the message you are answering is in.",
    },
}


class Voice:
    """The runner's own words, in the language the configuration asked for.

    Built from what the file literally says rather than from the language that
    was read out of it, because those are two different questions: `fr` and `en`
    both name a language, while *nothing at all* also says the sessions were
    never told what to write in — see `instruction`.
    """

    def __init__(self, language: str = "") -> None:
        self.asked = str(language or "").strip()
        self.language = understood(self.asked)

    # -- the sentence itself -------------------------------------------------

    def say(self, key: str, **values: object) -> str:
        """One thing the runner has to say, filled in."""
        return _SAID[key][self.language].format(**values)

    def count(self, number: int, thing: str) -> str:
        """“3 commits”, “1 commit” — the noun's key is its singular."""
        return self.say(thing if abs(number) == 1 else f"{thing}s", count=number)

    def minutes(self, seconds: float) -> str:
        """How long something took, said the way a person would.

        “18.2 min” is a measurement; nobody reports their afternoon to the tenth
        of a minute. Under a minute it stops being a number at all.
        """
        if seconds < 60:
            return self.say("under-a-minute")
        return self.count(round(seconds / 60), "minute")

    def money(self, dollars: float) -> str:
        """A price, with the currency where each language puts it."""
        if self.language == "fr":
            return f"{dollars:.2f} $".replace(".", ",")
        return f"${dollars:.2f}"

    # -- a report under a ticket ---------------------------------------------

    def facts(self, *facts: object) -> str:
        """The figures that place a verdict, in the order somebody reads them.

        Where the work is, how much of it there is, what it took — separated by
        a middle dot, because a comma would read as a sentence and this is a
        row of labels.
        """
        return " · ".join(said for fact in facts if (said := str(fact or "").strip()))

    def verdict(self, name: str, *facts: object) -> str:
        """The first line of a report, which is the notification.

        A mark, one word saying what is expected of you, and the figures. It has
        about eighty characters before a phone stops showing it, so nothing else
        goes here — and nothing at all goes in front of it, which is the whole
        difference with the reports that opened on the name of a machine.
        """
        said = f"{MARKS[name]} {self.say('verdict-' + name)}"
        placed = self.facts(*facts)
        return f"{said} — {placed}" if placed else said

    def headline(self, name: str, title: str) -> str:
        """A notification's title: the same verdict, and what it is about.

        Notion writes the page's name above the comment it pushes; a desktop
        notification and a Telegram message have only what they are handed, so
        the ticket is named here — and named with the verdict the comment opens
        on, so that the two read as one thing said twice.
        """
        return self.say("headline", verdict=self.say("verdict-" + name), title=title)

    def report(self, headline: str, *lines: object) -> str:
        """One comment: the verdict, one sentence, one link. In that order.

        Three lines, and the order is the point — a reader who stops after the
        first has the decision, one who stops after the second has the story,
        and the third is where they go. A run that went wrong is allowed one
        more, saying where the rest of it is, because that is the day somebody
        needs it.
        """
        return "\n".join(said for line in (headline, *lines) if (said := str(line or "").strip()))

    def brief(self, text: object, limit: int = BRIEF) -> str:
        """What the session said, cut on a word rather than mid-syllable.

        The prompt asks for one sentence and mostly gets one; asking is not
        enforcing, and a report is not the place to find out. Cut here, once,
        rather than by whatever is showing it.
        """
        flat = " ".join(str(text or "").split())
        if len(flat) <= limit:
            return flat
        return flat[:limit].rsplit(" ", 1)[0].rstrip(" ,;:—-") + "…"

    def paragraphs(self, *parts: object) -> str:
        """Whatever is worth saying, one paragraph each, blanks dropped.

        Most of what goes under a report is optional — a note, a kept worktree,
        a price — and a message assembled with f-strings around things that may
        be empty ends up with the blank lines to prove it.
        """
        return "\n\n".join(said for part in parts if (said := str(part or "").strip()))

    def sentence(self, text: str) -> str:
        """A reason, read as a sentence rather than as a label.

        The reasons are written lowercase and unpunctuated because that is how
        they read in the journal — “✗ Le header — the session did not make it to
        the end”. On a ticket they are the first thing said, and the first thing
        said is a sentence.
        """
        text = text.strip()
        if not text:
            return ""
        return text[:1].upper() + text[1:] + ("" if text[-1] in ".!?…" else ".")

    def spent(self, seconds: float, cost: float) -> tuple[str, ...]:
        """What the run took, as facts for a verdict line rather than a sentence.

        Two of them, not three: the turn count is on the board already, in its
        own column, and a notification has room for what changes a decision.
        """
        return (self.minutes(seconds), self.money(cost) if cost else "")

    def trace(self, resume: str, log: object, home: object = "") -> str:
        """Where to go when the report is not enough: the session, then the log."""
        picker = self.say("trace-picker", home=home) if home else ""
        return self.say("trace", resume=resume, picker=picker, log=log)

    # -- what the session is told --------------------------------------------

    def instruction(self, *, reply: bool = False) -> str:
        """The language a session is told to write in, or nothing at all.

        Nothing when the configuration says nothing, and that is the whole of
        the default: a runner nobody has configured behaves exactly as it did,
        which for a session means the rule its prompt already carries — write in
        the language of the ticket, of the message, of whoever is being answered.

        `reply` is the same sentence for a session that is talking rather than
        working: it has no report to write and no ticket to write back into, and
        the one thing it has to be told is the one thing that is otherwise
        decided by the message it answers.
        """
        if not self.asked:
            return ""
        return self.say("instruction-reply" if reply else "instruction")
