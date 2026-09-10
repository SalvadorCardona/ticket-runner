"""One key, and every model behind it.

What the runner drives is Claude Code, and Claude Code talks to Anthropic. That
is one family of models on one subscription — so a ticket that wants GPT to
write the copy, a transcription of an audio file, or a video made from a prompt,
has nowhere to go and no way of paying for it.

OpenRouter is one key in front of every provider there is. Configured here, it
reaches a session in two ways, and they are not the same gesture.

**The key, in the session's environment.** `OPENROUTER_API_KEY` is the name
every library and every snippet already looks for, so the work can call whatever
model it needs — a GPT, an image, a video — without anything in the runner
having to know what a video model is. Nothing else changes: the agent doing the
work is the one you have always had, it simply now has an account.

**The sessions themselves, run on it.** Off by default, and it is the switch to
think about: Claude Code then speaks to OpenRouter's Anthropic-compatible
endpoint instead of to Anthropic, and every model named anywhere — a ticket's
Model column, an agent's, `runner.model` — becomes an OpenRouter slug,
`openai/gpt-5` or `anthropic/claude-sonnet-4.5`. Two things travel with that,
and neither is a detail. The CLI is no longer signed in as you but as a bearer
token, so Claude in Chrome does not load (session.py says why). And the bill is
OpenRouter's rather than the subscription's, so there is no window to wait for
and `runner.wait_for_credits` has nothing left to hold (credits.py says why).

An empty key is the whole of the old behaviour: nothing here is added to
anything, and a session starts exactly as it used to.
"""

from __future__ import annotations

from .config import OPENROUTER_URL, OpenRouter


def environment(settings: OpenRouter) -> dict[str, str]:
    """What a session is started with, on top of the environment it inherits."""
    if not settings.key:
        return {}
    base = settings.base_url.rstrip("/") or OPENROUTER_URL
    variables = {"OPENROUTER_API_KEY": settings.key, "OPENROUTER_BASE_URL": base}
    if settings.route_sessions:
        # `ANTHROPIC_AUTH_TOKEN` and not `ANTHROPIC_API_KEY`: the first is sent
        # as a bearer token, which is what a gateway in front of the Messages
        # API expects, and it is the one Claude Code documents for exactly this.
        variables["ANTHROPIC_BASE_URL"] = base
        variables["ANTHROPIC_AUTH_TOKEN"] = settings.key
    return variables
