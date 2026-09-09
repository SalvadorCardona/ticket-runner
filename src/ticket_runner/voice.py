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
- **It says what happened, not what it ran.** A report used to read
  “Branch `x` · 3 commit(s) · <url>”, which is a row of facts with the sentence
  taken out. The facts are the same here; what changed is that they are said.
  The plumbing — the session id, the log path — comes last and in one sentence,
  because it is what you need on the rare day something went wrong, not what you
  came to the ticket to read.

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
# Grouped as a run goes: how a report opens, how a finished ticket reads, what a
# failure is called, and what reaches a phone.
_SAID: dict[str, dict[str, str]] = {
    # -- how a report opens --------------------------------------------------
    # The host label in front of these is what every reader of the board — and
    # `web.api._voice` — recognises the runner by, so only the words after the
    # dash are ever translated.
    "done": {"en": "done.", "fr": "c'est fait."},
    "failed": {"en": "that did not work.", "fr": "ça n'a pas marché."},
    "blocked": {"en": "I am stuck.", "fr": "je suis bloqué."},
    "requeued": {"en": "back in the queue.", "fr": "remis dans la file."},
    # -- a ticket that got somewhere -----------------------------------------
    "after-code": {
        "en": "{commits} on `{branch}`, and the pull request is waiting to be read: {url}",
        "fr": "{commits} sur `{branch}`, et la pull request attend une relecture : {url}",
    },
    "after-code-alone": {
        "en": "{commits} on `{branch}`. No pull request, so the branch is where to look.",
        "fr": "{commits} sur `{branch}`. Pas de pull request : tout est sur la branche.",
    },
    "after-document": {
        "en": "The answer is in the page above, {blocks} of it.",
        "fr": "La réponse est dans la page ci-dessus, {blocks} en tout.",
    },
    "after-publication": {
        "en": "Validated, so it went out. {summary}",
        "fr": "Validé, donc c'est parti. {summary}",
    },
    "after-merge": {
        "en": "Validated, so the pull request went in: {url}",
        "fr": "Validé, donc la pull request est passée : {url}",
    },
    "merged-already": {
        "en": "It had already been merged — there was nothing left to do.",
        "fr": "Elle avait déjà été fusionnée — il n'y avait plus rien à faire.",
    },
    "merged-now": {
        "en": "Merged with a {method}.\n{said}",
        "fr": "Fusionnée en {method}.\n{said}",
    },
    "merged-elsewhere": {
        "en": "Its pull request has been merged, so this one is closed: {url}",
        "fr": "Sa pull request a été fusionnée, donc le ticket est clos : {url}",
    },
    "spent": {
        "en": "That took {minutes} and {turns}, and cost {cost}.",
        "fr": "Ça a pris {minutes} et {turns}, pour {cost}.",
    },
    "spent-freely": {
        "en": "That took {minutes} and {turns}.",
        "fr": "Ça a pris {minutes} et {turns}.",
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
    # -- a run that died in the middle ---------------------------------------
    "abandoned": {
        "en": (
            "Nobody was working on this any more, {minutes} after it was last touched: "
            "its run was stopped, or it died in the middle of a session."
        ),
        "fr": (
            "Plus personne ne s'en occupait, {minutes} après la dernière trace : son run "
            "a été arrêté, ou il est mort en cours de session."
        ),
    },
    "abandoned-requeued": {
        "en": "I am picking it up again from the start.",
        "fr": "Je le reprends depuis le début.",
    },
    "abandoned-publishing": {
        "en": (
            "It was being published at the time, having been validated, so I am not "
            "trying again on my own: it may well have gone out just before the run died. "
            "Worth a look — and back to “{origin}” if it did not."
        ),
        "fr": (
            "Il était en cours de publication, après avoir été validé, donc je ne "
            "recommence pas de moi-même : il est peut-être parti juste avant que le run "
            "ne meure. À vérifier — et à remettre dans « {origin} » si ce n'est pas le cas."
        ),
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
    "headline-blocked": {"en": "Stuck · {title}", "fr": "Bloqué · {title}"},
    "headline-failed": {"en": "Failed · {title}", "fr": "En échec · {title}"},
    "headline-review": {"en": "Ready to read · {title}", "fr": "À relire · {title}"},
    "headline-published": {"en": "Published · {title}", "fr": "Publié · {title}"},
    "written-into-notion": {
        "en": "The answer is in the Notion ticket.",
        "fr": "La réponse est dans le ticket Notion.",
    },
    "branch-only": {
        "en": "{commits} on the branch {branch}.",
        "fr": "{commits} sur la branche {branch}.",
    },
    "publication-interrupted": {
        "en": "Its publication was interrupted. Did it go out? If not, back to “{origin}”.",
        "fr": "Sa publication a été interrompue. Est-elle partie ? Sinon, retour dans « {origin} ».",
    },
    "invitation": {
        "en": "\n\nAn answer here — yes, no, or a sentence — and it runs again on the next pass.",
        "fr": "\n\nUne réponse ici — oui, non, ou une phrase — et il repart au prochain passage.",
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
    "turn": {"en": "{count} turn", "fr": "{count} échange"},
    "turns": {"en": "{count} turns", "fr": "{count} échanges"},
    "minute": {"en": "{count} minute", "fr": "{count} minute"},
    "minutes": {"en": "{count} minutes", "fr": "{count} minutes"},
    "under-a-minute": {"en": "under a minute", "fr": "moins d'une minute"},
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

    def report(self, label: str, event: str, *parts: object) -> str:
        """One comment: who is speaking, then what happened, a paragraph each.

        The label is the host the runner signs with, and it stays in front
        whatever the language: it is what tells a reader — and the next run —
        that this comment is the runner's own rather than somebody's answer.
        """
        return f"{label} — {self.say(event)}\n" + self.paragraphs(*parts)

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

    def spent(self, turns: int, seconds: float, cost: float) -> str:
        """What the run cost, in the three units anybody actually compares."""
        counted = {"minutes": self.minutes(seconds), "turns": self.count(turns, "turn")}
        if not cost:
            return self.say("spent-freely", **counted)
        return self.say("spent", **counted, cost=self.money(cost))

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
