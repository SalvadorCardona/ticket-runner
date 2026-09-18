"""The first connection: the console asking once for everything it needs.

Until now the only way into a fresh installation was a secret found on disk —
`serve --print-token`, or the line the installer printed and you scrolled past.
That is the wrong order. A token protects an installation that is already set
up; a fresh one has nothing to protect yet, and what it actually needs is for
somebody to say who opens it from now on.

So a console **nobody can sign into and whose token nobody chose** is
*unclaimed*, and what it serves is this form rather than a demand for a secret.
Filling it in is the whole installation, in the order somebody would say it: the
email and password that open the console from here on — which is also what
closes this door behind them — then the Notion integration and the page to build
the board under, the rules every ticket is written against, and the Telegram bot
that reaches your phone. Nothing here is new configuration: every value written
is a key of `config.toml` you could have typed yourself, saved through the same
`config.edit` the Settings tab saves through.

Two things are worth saying out loud.

- **The first browser to arrive claims the console.** An unclaimed console is
  necessarily on loopback — `serve` refuses to start on any other host without a
  token or a sign-in — so "the first browser" means "somebody sitting at this
  machine". On a machine you share with other people, set `web.token`, or the
  sign-in, before starting the console: both are a decision, and claiming is
  what happens when nobody took one.
- **It is not one transaction, and it does not pretend to be.** The credentials
  are written in a single edit: all of them or none. What comes after them
  creates pages in somebody's Notion, and no undo of that is possible or wanted
  — so a step that fails is said in the report and leaves everything before it
  standing. That is the rule `ticket-runner init` already follows, where running
  it again is how you finish the job; the Settings tab is the other way.
"""

from __future__ import annotations

from .. import channels, notion, provision, store
from .. import config as config_module
from ..channels import telegram as telegram_channel
from .api import Api

# Behind this port sits a runner that starts Claude Code sessions with
# `bypassPermissions`, and a password is guessable in a way a 32-character token
# is not. Eight characters and a second per wrong attempt (see `_sign_in`) is
# the floor; the field says so before it refuses, rather than after.
SHORTEST_PASSWORD = 8


def _text(payload: dict, key: str) -> str:
    return str(payload.get(key, "") or "").strip()


def apply(api: Api, payload: dict) -> dict:
    """Do the first connection, and say what it did, step by step.

    Returns the report the page draws — `steps` in the order they happened, and
    `problem` for the one that did not. Raises only for what can be refused
    *before* anything is written: everything past the credentials is reported.
    """
    email = _text(payload, "email")
    password = str(payload.get("password", ""))
    confirm = str(payload.get("confirm", password))
    if "@" not in email:
        raise ValueError("an email address is what the console will ask you for")
    if len(password) < SHORTEST_PASSWORD:
        raise ValueError(
            f"a password of {SHORTEST_PASSWORD} characters at the least — behind this "
            "port sits a runner that runs code on this machine"
        )
    if password != confirm:
        raise ValueError("the two passwords are not the same")

    page = _text(payload, "notion_page")
    page_id = config_module.identifier(page)
    if page and not config_module.is_identifier(page_id):
        raise ValueError(f"“{page}” does not contain a Notion page ID")

    bot = _text(payload, "telegram_token")
    chat = _text(payload, "telegram_chat")

    report = provision.Report()
    values: dict[str, object] = {"web.email": email, "web.password": password}
    for name, value in (
        ("notion.token", _text(payload, "notion_token")),
        ("notify.telegram.token", bot),
        ("notify.telegram.chat", chat),
    ):
        if value:
            values[name] = value
    api.save_settings({"settings": values})
    report.note("created", f"this console opens as {email} from now on")

    # The rules are written *into* the context page, so they wait on the board
    # having been built. The chat id does not wait on anything: it is read back
    # from the bot, and a Notion that refused is no reason to leave it unpaired.
    problem = _notion(api, report, page_id) if page_id else ""
    if not problem:
        problem = _rules(api, report, str(payload.get("rules", "")))
    paired = _telegram(api, report, bot) if bot and not chat else ""
    return {
        "steps": [list(step) for step in report.steps],
        "problem": problem or paired,
        "email": email,
    }


def _notion(api: Api, report: provision.Report, page_id: str) -> str:
    """Build the board under the page that was shared, and point the file at it.

    `provision` is the same code `ticket-runner init` runs, which is the point:
    a board built from a browser and a board built from a terminal are the same
    five databases, with the same columns spelled the same way.
    """
    token = api.config.notion.token
    if not token or token == config_module.PLACEHOLDER:
        return "a page without a token: nothing was built under it"
    try:
        built = provision.provision(notion.Client(token), api.config.notion, page_id)
    except store.StoreError as error:
        return f"Notion: {str(error).splitlines()[0]}"
    report.steps.extend(built.steps)
    api.save_settings({"settings": {"notion.workspace": built.workspace}})
    report.note("created", f"the board is {built.workspace} — written to the configuration")
    return ""


def _rules(api: Api, report: provision.Report, rules: str) -> str:
    """The standing context, which is the one text worth typing here.

    Not a nicety: it reaches every prompt before the project's brief and before
    the ticket, and it is what makes an answer sound like you rather than like
    nobody. Written as *the* context rather than appended to the seed `init`
    leaves — a first connection is the moment that page has nothing to keep.
    """
    if not rules.strip():
        return ""
    try:
        # The context page is a page of the board, so there has to be a board.
        # Said here rather than discovered as a 401 from Notion, which is what
        # asking a placeholder token to write somewhere would produce.
        api.config.require_usable()
    except config_module.ConfigError:
        return "nowhere to write the rules yet: fill Notion in, then the Context pane"
    try:
        api.save_context(rules)
    except (ValueError, store.StoreError) as error:
        return f"the rules: {str(error).splitlines()[0]}"
    report.note("created", "the rules — read into every ticket, before the ticket")
    return ""


def _telegram(api: Api, report: provision.Report, token: str) -> str:
    """The chat id, found by reading who has written to the bot.

    The one value of this configuration nobody can look up, and the usual advice
    is to paste your token into somebody else's bot — which is handing them the
    channel. `notify --pair` reads it back from your own bot instead, and this
    is that gesture, taken while the token is still in front of you.
    """
    try:
        found = telegram_channel.chats(token)
    except channels.ChannelError as error:
        return f"Telegram refused: {error}"
    if not found:
        return "nobody has written to that bot yet: say anything to it, then fill in the chat id"
    if len(found) > 1:
        return "several chats have written to that bot — pick one in the settings"
    identifier, name = found[0]
    api.save_settings({"settings": {"notify.telegram.chat": identifier}})
    report.note("created", f"Telegram is paired with “{name}” ({identifier})")
    return ""
