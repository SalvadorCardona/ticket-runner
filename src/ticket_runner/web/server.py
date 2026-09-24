"""The console's HTTP layer: `http.server`, and nothing else.

A tool whose whole claim is "no dependency to install" does not get to grow a
web framework the day it grows a web page. What is here is what the standard
library already offers — a threading HTTP server, a handler, and Server-Sent
Events, which are eight lines and exactly the shape of the problem.

**What is on the other side of this port matters more than the port.** The
runner starts Claude Code sessions with `bypassPermissions`; so does the chat.
Anything that can talk to this server can run code on this machine as you. That
is why:

- the default bind is `127.0.0.1`, and a non-loopback host without a configured
  token — or a configured sign-in — is refused rather than served;
- every request carries a token — as a header, as the cookie the first `?token=`
  sets, or as the cookie signing in with an email and a password sets;
- until somebody has said how this console is opened, there is nothing to carry:
  a console nobody claimed serves the first connection instead (see `setup`),
  and the password typed there is what closes that door;
- a request from a browser page that is not the console is rejected: writes
  demand a header a cross-origin form cannot set, and the `Host` header must
  name the address the console was reached on, which is what stops a hostile
  page from resolving its own domain to 127.0.0.1 and talking to you through it.
"""

from __future__ import annotations

import errno
import hashlib
import hmac
import html
import json
import mimetypes
import queue
import re
import secrets
import socket
import threading
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse

from .. import config as config_module
from .. import store, voice
from ..config import Config, state_dir
from . import setup
from .api import Api

STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "ticket_runner_token"

# A header no cross-origin form, image or script tag can set. Its presence is
# what tells "the console asked this" from "some page you had open asked this".
GUARD_HEADER = "X-Ticket-Runner"

# Bodies are small — a ticket, a message, a command. Anything larger is a
# mistake, and reading it would be the mistake becoming ours.
MAX_BODY = 256 * 1024

LOOPBACK = ("127.0.0.1", "::1", "localhost", "[::1]")


def token_path() -> Path:
    path = state_dir() / "web"
    path.mkdir(parents=True, exist_ok=True)
    return path / "token"


def token(config: Config) -> str:
    """The console's token: the configured one, or one drawn once and kept.

    Kept on disk rather than drawn per start, because a token that changed on
    every restart would make the bookmark useless — and a console you reach by
    pasting a fresh secret every morning is a console you stop opening.
    """
    if config.web.token:
        return config.web.token
    path = token_path()
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    fresh = secrets.token_urlsafe(24)
    path.write_text(fresh + "\n", encoding="utf-8")
    path.chmod(0o600)
    return fresh


def landing(query: str) -> str:
    """Where a `?token=…` address goes once the token is in a cookie.

    Everything the address carried except the token, because the rest of it is
    not a secret, it is a destination: `serve` prints `/?token=…` and a deep
    link is shared as `/?token=…&view=console/projects/list`. Redirecting both
    to a bare `/` put the second one on the board.
    """
    rest = urlencode([pair for pair in parse_qsl(query) if pair[0] != "token"])
    return f"/?{rest}" if rest else "/"


@dataclass(frozen=True)
class SignIn:
    """An email, a password, and the cookie a browser that typed them carries.

    The cookie is *derived* from the two rather than drawn at random, and that
    is the whole of the session handling: a console that restarts — and its unit
    restarts with the machine — does not sign you out, while changing the
    password signs out every browser that ever held one, without anything to
    keep or to expire. It is an HMAC under the console's own token, so the value
    in the cookie says nothing about the password it came from.
    """

    email: str
    password: str
    cookie: str


def sign_in(config: Config, secret: str) -> SignIn | None:
    """How this console is opened, when it is not opened with its token.

    None unless both halves are set: an email without a password is somebody
    half-way through configuring one, and it must not be a way in.
    """
    email = config.web.email.strip()
    password = config.web.password
    if not email or not password:
        return None
    proof = hmac.new(
        secret.encode(), f"{email.lower()}\n{password}".encode(), hashlib.sha256
    ).hexdigest()
    return SignIn(email=email, password=password, cookie=proof)


def claimable(config: Config, entry: SignIn | None) -> bool:
    """Has anybody decided how this console is opened? — see `setup`.

    Two ways of deciding it, and neither has been taken: a sign-in, which is
    `None` until an email *and* a password are set, in the file or in the
    environment; or a token written in the configuration on purpose. The token
    drawn on first start is not a decision — it is what the console does when
    nobody has said anything, and it is the state the first connection is for.
    """
    return entry is None and not config.web.token


class Console(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self, address, handler, api: Api, secret: str, entry: SignIn | None = None
    ) -> None:
        super().__init__(address, handler)
        self.api = api
        self.secret = secret
        self.entry = entry


class Handler(BaseHTTPRequestHandler):
    server_version = "ticket-runner"
    protocol_version = "HTTP/1.1"

    # -- plumbing -------------------------------------------------------------

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return  # a console is not a web server; its log is the terminal it runs in

    @property
    def api(self) -> Api:
        return self.server.api  # type: ignore[attr-defined]

    @property
    def entry(self) -> SignIn | None:
        return self.server.entry  # type: ignore[attr-defined]

    def _send(self, code: int, body: bytes, kind: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        # Nothing here is meant to be cached, framed, sniffed or embedded.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(), "application/json")

    def _fail(self, code: int, message: str) -> None:
        self._json({"error": message}, code)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length > MAX_BODY:
            self.close_connection = True
            return {}
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- who is asking --------------------------------------------------------

    def _host_is_ours(self) -> bool:
        """The `Host` header names the address this console is served on.

        Without this, any web page could point a domain of its own at 127.0.0.1
        and have your browser talk to the console as if it were the console.
        """
        configured = self.api.config.web.host
        if configured not in LOOPBACK:
            # A wider bind was asked for on purpose, and is reached under a name
            # or address this process cannot enumerate — a LAN IP, a tailnet
            # name, whatever the tunnel calls it. The token is the guard there;
            # this check exists for the loopback case, which is the one a page
            # in another tab can actually reach.
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        expected = {"127.0.0.1", "::1", "localhost", str(self.server.server_address[0]), configured}
        try:
            expected.add(socket.gethostname())
        except OSError:
            pass
        return host in expected

    def _presented(self) -> str:
        header = self.headers.get("Authorization") or ""
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        if self.headers.get("X-Token"):
            return str(self.headers.get("X-Token")).strip()
        cookies = SimpleCookie(self.headers.get("Cookie") or "")
        if COOKIE in cookies:
            return cookies[COOKIE].value
        return ""

    def _authorised(self, query: dict) -> bool:
        """The token, or the cookie a sign-in left. Either is this console's.

        The token does not go away when an email and a password are set: it is
        what a script, the dev server's proxy and `--print-token` carry. What
        changes is that a person no longer has to.
        """
        offered = (query.get("token") or [""])[0] or self._presented()
        if not offered:
            return False
        known = [self.server.secret]  # type: ignore[attr-defined]
        if self.entry:
            known.append(self.entry.cookie)
        # Compared as bytes: `compare_digest` refuses two strings when either
        # holds a character outside ASCII, and what is offered here came from a
        # browser — a cookie somebody pasted an accent into would be a 500
        # rather than the "no" it is.
        return any(hmac.compare_digest(offered.encode(), value.encode()) for value in known)

    # -- routing --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        route = parsed.path.rstrip("/") or "/"

        if not self._host_is_ours():
            return self._fail(421, "this console is not served under that name")
        if not self._authorised(query):
            return self._unauthorised(route)

        # The token arrived in the URL: put it in a cookie and get it out of the
        # address bar, where it would otherwise sit in the history and in every
        # screenshot of the console. The token, and nothing else: the rest of
        # the address says *where* — `?token=…&view=console/projects/list` is
        # how a deep link is shared — and a redirect to a bare `/` would strip
        # the destination along with the secret and land on the board.
        if query.get("token") and route == "/":
            return self._send(
                303,
                b"",
                "text/plain",
                {
                    "Location": landing(parsed.query),
                    "Set-Cookie": (
                        f"{COOKIE}={query['token'][0]}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"
                    ),
                },
            )

        # The way in, for somebody who already has one: a console still
        # unclaimed has a password waiting to be set, and whoever opened it with
        # its token would otherwise never be shown where.
        if route == "/setup" and claimable(self.api.config, self.entry):
            return self._send(200, setup_page(self._language()).encode(), "text/html; charset=utf-8")

        if route == "/":
            return self._static("index.html")
        if route.startswith("/static/"):
            return self._static(route[len("/static/") :])
        if route == "/api/events":
            return self._stream()

        try:
            if route == "/api/state":
                return self._json(self.api.state())
            if route == "/api/board":
                return self._json(self.api.board())
            if route == "/api/projects":
                return self._json(self.api.all_projects())
            if match := re.fullmatch(r"/api/projects/([0-9a-fA-F-]{32,36})", route):
                return self._json(self.api.project(match.group(1)))
            if route == "/api/context":
                return self._json(self.api.context())
            if route == "/api/schedules":
                return self._json(self.api.schedules())
            if match := re.fullmatch(r"/api/schedules/([0-9a-fA-F-]{32,36})", route):
                return self._json(self.api.schedule(match.group(1)))
            if route == "/api/history":
                return self._json(self.api.history())
            if route == "/api/chat":
                return self._json({"messages": self.api.chat.history(), **self.api.chat.state()})
            if route == "/api/settings":
                return self._json(self.api.settings())
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})", route):
                return self._json(self.api.ticket(match.group(1)))
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/talk", route):
                return self._json(self.api.talk(match.group(1)))
            if route == "/api/logs":
                return self._json(self.api.logs())
            if match := re.fullmatch(r"/api/logs/([\w.\-]+)", route):
                return self._json(self.api.log(match.group(1)))
        except store.StoreError as error:
            return self._fail(502, f"the board: {str(error).splitlines()[0]}")
        except LookupError as error:
            return self._fail(404, str(error))
        except Exception as error:  # noqa: BLE001
            return self._fail(500, str(error).splitlines()[0])

        return self._fail(404, f"no such route: {route}")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if not self._host_is_ours():
            return self._fail(421, "this console is not served under that name")
        # Two writes cannot be authorised beforehand, because they are what
        # produces the authorisation: signing in, and — on a console nobody has
        # claimed — the first connection that gives it a password to sign in
        # with. Everything else about them holds: the name they are reached
        # under, and the header below.
        signing_in = route == "/api/login"
        opening = signing_in or route == "/api/setup"
        if not opening and not self._authorised(parse_qs(parsed.query)):
            return self._fail(401, "token missing or wrong")
        # A cookie alone is not consent: a page you have open elsewhere can post
        # a form to this port with your cookie attached, but it cannot set a
        # header of its own without a preflight this server never answers.
        if self.headers.get(GUARD_HEADER) != "1":
            return self._fail(403, "this request did not come from the console")

        payload = self._body()
        if signing_in:
            return self._sign_in(payload)
        try:
            if route == "/api/setup":
                return self._setup(payload)
            if route == "/api/tickets":
                return self._json(
                    self.api.create_ticket(
                        str(payload.get("title", "")),
                        str(payload.get("body", "")),
                        str(payload.get("project", "")),
                        bool(payload.get("ready", True)),
                    )
                )
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/status", route):
                return self._json(
                    self.api.set_status(match.group(1), str(payload.get("column", "")))
                )
            if match := re.fullmatch(r"/api/tickets/([0-9a-fA-F-]{32,36})/talk", route):
                return self._json(self.api.tell(match.group(1), str(payload.get("text", ""))))
            if route == "/api/command":
                return self._json(self.api.commands.start(str(payload.get("line", ""))))
            if route == "/api/chat":
                return self._json(self.api.chat.send(str(payload.get("text", ""))))
            if route == "/api/chat/reset":
                return self._json(self.api.chat.reset())
            if match := re.fullmatch(r"/api/projects/([0-9a-fA-F-]{32,36})", route):
                return self._json(self.api.save_project(match.group(1), payload))
            if route == "/api/settings":
                return self._json(self.api.save_settings(payload))
            if route == "/api/context":
                return self._json(self.api.save_context(str(payload.get("text", ""))))
            if route == "/api/schedules":
                return self._json(
                    self.api.create_schedule(str(payload.get("name", "")), payload)
                )
            if match := re.fullmatch(r"/api/schedules/([0-9a-fA-F-]{32,36})", route):
                return self._json(self.api.save_schedule(match.group(1), payload))
            if route == "/api/refresh":
                self.api.forget()
                self.api.watch.nudge()
                return self._json({"ok": True})
        except config_module.ConfigError as error:
            return self._fail(400, str(error).splitlines()[0])
        except ValueError as error:
            return self._fail(400, str(error))
        except RuntimeError as error:
            return self._fail(409, str(error))
        except FileNotFoundError as error:
            return self._fail(503, str(error))
        except store.StoreError as error:
            return self._fail(502, f"the board: {str(error).splitlines()[0]}")
        except Exception as error:  # noqa: BLE001
            return self._fail(500, str(error).splitlines()[0])

        return self._fail(404, f"no such route: {route}")

    # -- the three kinds of response ------------------------------------------

    def _static(self, name: str) -> None:
        target = (STATIC / name).resolve()
        if not str(target).startswith(str(STATIC)) or not target.is_file():
            return self._fail(404, f"no such file: {name}")
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind == "application/javascript":
            kind = f"{kind}; charset=utf-8"
        self._send(200, target.read_bytes(), kind)

    def _sign_in(self, payload: dict) -> None:
        """An email and a password against the configured ones. Nothing else."""
        entry = self.entry
        if entry is None:
            return self._fail(404, "this console is opened with its token")
        email = str(payload.get("email", "")).strip().lower()
        password = str(payload.get("password", ""))
        # Both compared before either is looked at: an early return here would
        # answer "that email does not exist" by taking less time to say so. And
        # as bytes, because a password with an accent in it is a password.
        known_email = hmac.compare_digest(email.encode(), entry.email.lower().encode())
        known_password = hmac.compare_digest(password.encode(), entry.password.encode())
        if not (known_email and known_password):
            # Behind this port sits `bypassPermissions`, and a password is
            # guessable in a way a 32-character token is not. A second per
            # attempt is nothing to type through and a wall to grind against.
            time.sleep(1)
            return self._fail(401, "wrong email or password")
        self._send(
            200,
            b'{"ok": true}',
            "application/json",
            {
                "Set-Cookie": (
                    f"{COOKIE}={entry.cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"
                )
            },
        )

    def _setup(self, payload: dict) -> None:
        """The first connection: everything at once, and a way in at the end.

        Signing the browser in rather than sending it back to the door it has
        just built: the password was typed one second ago, and asking for it
        again would be the token all over again. The console keeps its new
        sign-in on the server object, because that is where the way in is read
        from — a restart would find the same one in the file.
        """
        if not claimable(self.api.config, self.entry):
            return self._fail(404, "this console has already been set up")
        result = setup.apply(self.api, payload)
        entry = sign_in(self.api.config, self.server.secret)  # type: ignore[attr-defined]
        if entry is None:  # the write went through and said nothing: refuse to guess
            return self._fail(500, "the credentials were not written")
        self.server.entry = entry  # type: ignore[attr-defined]
        self._send(
            200,
            json.dumps(result, ensure_ascii=False).encode(),
            "application/json",
            {
                "Set-Cookie": (
                    f"{COOKIE}={entry.cookie}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"
                )
            },
        )

    def _unauthorised(self, route: str) -> None:
        if route.startswith("/api/"):
            return self._fail(401, "token missing or wrong")
        language = self._language()
        if claimable(self.api.config, self.entry):
            page = setup_page(language)
        elif self.entry:
            page = sign_in_page(language)
        else:
            page = gate_page(language, self._token_whereabouts())
        self._send(401, page.encode(), "text/html; charset=utf-8")

    def _language(self) -> str:
        return language_of(self.headers.get("Accept-Language") or "")

    def _token_whereabouts(self) -> str:
        """Where this console's token can be read, on this machine, as HTML."""
        configuration = self.api.config
        if configuration.web.token:
            return _words(self._language())(
                "<code>web.token</code> of <code>{path}</code>"
            ).format(path=html.escape(str(configuration.path)))
        return f"<code>{html.escape(str(state_dir() / 'web' / 'token'))}</code>"

    def _stream(self) -> None:
        """One Server-Sent Events connection, for as long as the tab is open."""
        try:
            after = int(self.headers.get("Last-Event-ID") or 0)
        except ValueError:
            after = 0
        channel = self.api.hub.subscribe(after)
        self.api.watch.ensure_running()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            # No length and no chunking: the stream ends when the socket does,
            # so the connection has to be announced as closing. EventSource
            # reconnects on its own — with the last id it saw, which is the
            # whole reason the events are numbered.
            self.send_header("Connection", "close")
            self.close_connection = True
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = channel.get(timeout=15)
                except queue.Empty:
                    # A comment, not an event: it keeps the connection from
                    # being reaped by anything in between, and tells the browser
                    # nothing happened.
                    self.wfile.write(b": still here\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(event.encode().encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the tab was closed, which is the normal way this ends
        finally:
            self.api.hub.unsubscribe(channel)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()


# -- the three pages a browser sees before it is in ---------------------------

# Accent and ladder are the console's own (see `frontend/src/index.css`): the
# lime on near-black it is drawn in, and its light translation for a browser
# that asked for one. The door and the room behind it are the same colour.
_STYLE = """<style>
 :root{--bg:#0e0f13;--card:#16181e;--field:#1a1d24;--line:#262a34;--fg:#f1f2f4;--muted:#8d95a5;
       --accent:#d5f95a;--on-accent:#14180b;--bad:#f2685f;--good:#b8f24a;color-scheme:dark}
 @media (prefers-color-scheme: light){
  :root{--bg:#fbfbf9;--card:#fff;--field:#f4f5f1;--line:#e4e5e0;--fg:#14161a;--muted:#5b6170;
        --accent:#46600f;--on-accent:#f4ffe0;--bad:#c8332a;--good:#4d7a10;color-scheme:light}
 }
 body{background:var(--bg);color:var(--fg);font:15px/1.6 "DM Sans",ui-sans-serif,system-ui,sans-serif;
      display:grid;place-items:center;min-height:100vh;margin:0}
 form{width:min(28rem,90vw);background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1.6rem}
 h1{font-size:1.1rem;margin:0 0 .4rem} p{color:var(--muted);margin:.2rem 0 1.2rem;font-size:.9rem}
 label{display:block;font-size:.85rem;font-weight:600;margin:.8rem 0 .3rem}
 input{width:100%;box-sizing:border-box;background:var(--field);border:1px solid var(--line);color:inherit;
       border-radius:9px;padding:.7rem .8rem;font:inherit}
 input:focus-visible,textarea:focus-visible,button:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
 button{margin-top:1.1rem;width:100%;background:var(--accent);color:var(--on-accent);border:0;border-radius:9px;
        padding:.7rem;font:inherit;font-weight:600;cursor:pointer}
 code{background:var(--field);padding:.15rem .4rem;border-radius:6px;color:var(--fg);word-break:break-all}
 .said{color:var(--bad);margin:.9rem 0 0;min-height:1.2em}
</style>
"""

# What these pages say, in the two languages the console speaks. The key is
# the English, as it is in `frontend/src/lib/french.ts`: a sentence nobody
# translated is drawn as it was written rather than as a name.
_FRENCH = {
    "token": "jeton",
    "sign in": "connexion",
    "first connection": "première connexion",
    "Token": "Jeton",
    "Email": "E-mail",
    "Password": "Mot de passe",
    "Open the console": "Ouvrir la console",
    "Sign in to open the console.": "Connectez-vous pour ouvrir la console.",
    "wrong email or password": "e-mail ou mot de passe incorrect",
    "This console needs its token. <code>ticket-runner serve --print-token</code> prints it, "
    "and it is written in {where}.":
        "Cette console demande son jeton. <code>ticket-runner serve --print-token</code> "
        "l'affiche, et il est écrit dans {where}.",
    "<code>web.token</code> of <code>{path}</code>": "le <code>web.token</code> de <code>{path}</code>",
    "Nobody has claimed this console yet. What you fill in here is written into "
    "your <code>config.toml</code>, and the first two lines are how you open it "
    "from now on — this page does not come back.":
        "Personne n'a encore pris cette console. Ce que vous remplissez ici est écrit "
        "dans votre <code>config.toml</code>, et les deux premières lignes sont ce qui "
        "l'ouvrira désormais — cette page ne reviendra pas.",
    "You": "Vous",
    "The email and the password the console will ask for instead of its token.":
        "L'e-mail et le mot de passe que la console demandera à la place de son jeton.",
    "The same password again": "Le même mot de passe, encore",
    "— or leave it for later": "— ou plus tard",
    "Create an internal integration on <code>notion.so/my-integrations</code>, share one "
    "page with it — the <code>···</code> menu → <em>Connections</em> — and paste the two "
    "here. The board, its five databases and their columns are built under that page.":
        "Créez une intégration interne sur <code>notion.so/my-integrations</code>, partagez "
        "une page avec elle — menu <code>···</code> → <em>Connexions</em> — et collez les deux "
        "ici. Le tableau, ses cinq bases et leurs colonnes sont construits sous cette page.",
    "Integration token": "Jeton d'intégration",
    "Link of the page you shared": "Lien de la page partagée",
    "Your rules": "Vos règles",
    "— read into every ticket": "— lues dans chaque ticket",
    "Who you are, what the stack is, how you like things written. It reaches every "
    "session before the project's brief and before the ticket itself, which is what "
    "makes an answer sound like you. One screen: you pay for it on every ticket. "
    "What you write here <em>replaces</em> the Context page; left empty, it is left alone.":
        "Qui vous êtes, quelle est la stack, comment vous aimez qu'on écrive. Chaque "
        "session le lit avant le brief du projet et avant le ticket lui-même : c'est ce "
        "qui fait qu'une réponse sonne comme vous. Un écran au plus : vous le payez à "
        "chaque ticket. Ce que vous écrivez ici <em>remplace</em> la page Context ; vide, "
        "elle n'est pas touchée.",
    "Rules": "Règles",
    "I am …, I work on …, never …": "Je suis …, je travaille sur …, jamais …",
    "— optional": "— facultatif",
    "Where a blocked ticket asks its question, and what you answer lands on the ticket. "
    "@BotFather → <code>/newbot</code>, then say anything to your new bot: the chat id is "
    "read back from it, so leave it empty unless you know it.":
        "Là où un ticket bloqué pose sa question, et ce que vous répondez arrive sur le "
        "ticket. @BotFather → <code>/newbot</code>, puis écrivez n'importe quoi à votre "
        "nouveau bot : l'identifiant de discussion est relu depuis lui, laissez-le vide "
        "sauf si vous le connaissez.",
    "Bot token": "Jeton du bot",
    "Chat id": "Identifiant de discussion",
    "found on its own": "trouvé tout seul",
    "Set it up": "Tout configurer",
    "Setting it up…": "Configuration…",
    "that did not work": "ça n'a pas marché",
    "Set up — one thing did not work": "Configuré — une chose n'a pas marché",
    "Open the console →": "Ouvrir la console →",
}


def language_of(header: str) -> str:
    """The language a browser reads, from its `Accept-Language`.

    The console decides the same way — the browser's own list, in its order —
    and these pages have to agree with it: a sign-in in English opening onto a
    board in French reads as two products. The first tag that is one of the two
    spoken here wins; `voice.understood` reads it, as it reads the file's.
    """
    for part in (header or "").split(","):
        tag = part.split(";")[0].strip()
        if tag.split("-")[0].lower() in voice.LANGUAGES:
            return voice.understood(tag)
    return voice.DEFAULT


def _words(language: str):
    table = _FRENCH if language == "fr" else {}
    return lambda text: table.get(text, text)


def _page(title: str, body: str, style: str = "", language: str = "en") -> str:
    """The way in, drawn by this server rather than by the bundle.

    A browser that has not got in cannot load the console, so these three pages
    are the only HTML written in Python — and, like everything else served
    here, they reach for nothing that is not on this machine.
    """
    return (
        f'<!doctype html>\n<html lang="{language}">\n<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{html.escape(title)} · ticket-runner</title>\n" + _STYLE + style + body
    )


def gate_page(language: str = "en", where: str = "") -> str:
    """Asked for the token — and told where to find it, as this machine has it.

    `where` is the real place: the `web.token` line of the file in use when the
    token was chosen there, or the file it was drawn into — under
    `$XDG_STATE_HOME` when that is set, which a path printed as a constant got
    wrong on every machine that sets it.
    """
    say = _words(language)
    where = where or f"<code>{html.escape(str(state_dir() / 'web' / 'token'))}</code>"
    return _page(
        say("token"),
        f"""<form onsubmit="location='/?token='+encodeURIComponent(this.t.value.trim());return false">
  <h1>ticket-runner</h1>
  <p>{say("This console needs its token. <code>ticket-runner serve --print-token</code> prints it, "
          "and it is written in {where}.").format(where=where)}</p>
  <label for="t">{say("Token")}</label>
  <input id="t" name="t" autofocus autocomplete="off" spellcheck="false">
  <button type="submit">{say("Open the console")}</button>
</form>
""",
        language=language,
    )


def sign_in_page(language: str = "en") -> str:
    """The same door, with a lock somebody can remember.

    It posts rather than navigates — a form that navigated could not set the
    header that tells a request from the console apart from a request from a
    page you had open.
    """
    say = _words(language)
    return _page(
        say("sign in"),
        f"""<form onsubmit="enter(this);return false">
  <h1>ticket-runner</h1>
  <p>{say("Sign in to open the console.")}</p>
  <label for="email">{say("Email")}</label>
  <input id="email" name="email" type="email" autofocus autocomplete="username" spellcheck="false">
  <label for="password">{say("Password")}</label>
  <input id="password" name="password" type="password" autocomplete="current-password">
  <button type="submit">{say("Open the console")}</button>
  <p class="said" id="said" role="alert"></p>
</form>
<script>
const WRONG = {json.dumps(say("wrong email or password"), ensure_ascii=False)};
async function enter(form){{
  const said = document.getElementById('said');
  said.textContent = '';
  try {{
    const answer = await fetch('/api/login', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json', '{GUARD_HEADER}': '1'}},
      body: JSON.stringify({{email: form.email.value, password: form.password.value}}),
    }});
    if (answer.ok) {{ location = '/'; return; }}
    const body = await answer.json().catch(() => ({{}}));
    said.textContent = answer.status === 401 ? WRONG : (body.error || WRONG);
  }} catch (error) {{
    said.textContent = String(error);
  }}
}}
</script>
""",
        language=language,
    )


# The first connection. One page, in the order somebody would say it: who opens
# this console, then the board, then the words every ticket is written against,
# then the phone. Everything but the first pair may be left empty and set later
# in the Settings tab — the password is the only thing that cannot wait, since
# it is what shuts this door.
_SETUP_STYLE = """<style>
 body{place-items:start center;padding:3rem 0}
 form{width:min(36rem,92vw)}
 fieldset{border:1px solid var(--line);border-radius:11px;padding:.9rem 1rem 1.1rem;margin:0 0 1rem}
 legend{color:var(--fg);font-weight:600;padding:0 .4rem}
 legend span{color:var(--muted);font-weight:400}
 fieldset p{margin:0 0 .4rem}
 fieldset label:first-of-type{margin-top:.4rem}
 label small{color:var(--muted);font-weight:400}
 textarea{width:100%;box-sizing:border-box;background:var(--field);border:1px solid var(--line);color:inherit;
          border-radius:9px;padding:.7rem .8rem;font:inherit;min-height:7rem;resize:vertical}
 button[disabled]{background:var(--line);color:var(--muted);cursor:progress}
 ul{margin:1rem 0 0;padding-left:1.1rem;color:var(--muted);font-size:.9rem}
 li b{color:var(--good);font-weight:600}
 a{color:var(--accent)}
</style>
"""


def setup_page(language: str = "en") -> str:
    say = _words(language)
    words = json.dumps(
        {
            key: say(key)
            for key in ("Set it up", "Setting it up…", "that did not work", "Set up — one thing did not work")
        },
        ensure_ascii=False,
    )
    return _page(
        say("first connection"),
        f"""<form onsubmit="start(this);return false">
  <h1>ticket-runner</h1>
  <p>{say("Nobody has claimed this console yet. What you fill in here is written into "
          "your <code>config.toml</code>, and the first two lines are how you open it "
          "from now on — this page does not come back.")}</p>

  <fieldset>
    <legend>{say("You")}</legend>
    <p>{say("The email and the password the console will ask for instead of its token.")}</p>
    <label for="email">{say("Email")}</label>
    <input id="email" name="email" type="email" autofocus autocomplete="username" spellcheck="false">
    <label for="password">{say("Password")}</label>
    <input id="password" name="password" type="password" autocomplete="new-password">
    <label for="confirm">{say("The same password again")}</label>
    <input id="confirm" name="confirm" type="password" autocomplete="new-password">
  </fieldset>

  <fieldset>
    <legend>Notion <span>{say("— or leave it for later")}</span></legend>
    <p>{say("Create an internal integration on <code>notion.so/my-integrations</code>, share one "
             "page with it — the <code>···</code> menu → <em>Connections</em> — and paste the two "
             "here. The board, its five databases and their columns are built under that page.")}</p>
    <label for="notion_token">{say("Integration token")}</label>
    <input id="notion_token" name="notion_token" placeholder="ntn_…" autocomplete="off" spellcheck="false">
    <label for="notion_page">{say("Link of the page you shared")}</label>
    <input id="notion_page" name="notion_page" placeholder="https://www.notion.so/…"
           autocomplete="off" spellcheck="false">
  </fieldset>

  <fieldset>
    <legend>{say("Your rules")} <span>{say("— read into every ticket")}</span></legend>
    <p>{say("Who you are, what the stack is, how you like things written. It reaches every "
            "session before the project's brief and before the ticket itself, which is what "
            "makes an answer sound like you. One screen: you pay for it on every ticket. "
            "What you write here <em>replaces</em> the Context page; left empty, it is left alone.")}</p>
    <label for="rules">{say("Rules")}</label>
    <textarea id="rules" name="rules" placeholder="{html.escape(say("I am …, I work on …, never …"))}"></textarea>
  </fieldset>

  <fieldset>
    <legend>Telegram <span>{say("— optional")}</span></legend>
    <p>{say("Where a blocked ticket asks its question, and what you answer lands on the ticket. "
            "@BotFather → <code>/newbot</code>, then say anything to your new bot: the chat id is "
            "read back from it, so leave it empty unless you know it.")}</p>
    <label for="telegram_token">{say("Bot token")}</label>
    <input id="telegram_token" name="telegram_token" autocomplete="off" spellcheck="false">
    <label for="telegram_chat">{say("Chat id")} <small>— {say("found on its own")}</small></label>
    <input id="telegram_chat" name="telegram_chat" autocomplete="off" spellcheck="false">
  </fieldset>

  <button type="submit">{say("Set it up")}</button>
  <p class="said" id="said" role="alert"></p>
  <ul id="steps"></ul>
  <p id="after" hidden><a href="/">{say("Open the console →")}</a></p>
</form>
<script>
const WORDS = {words};
async function start(form){{
  const said = document.getElementById('said');
  const steps = document.getElementById('steps');
  const after = document.getElementById('after');
  const button = form.querySelector('button');
  said.textContent = '';
  steps.textContent = '';
  const body = {{}};
  for (const field of form.elements) if (field.name) body[field.name] = field.value;
  button.disabled = true;
  button.textContent = WORDS['Setting it up…'];
  try {{
    const answer = await fetch('/api/setup', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json', '{GUARD_HEADER}': '1'}},
      body: JSON.stringify(body),
    }});
    const payload = await answer.json().catch(() => ({{}}));
    if (!answer.ok) {{
      said.textContent = payload.error || WORDS['that did not work'];
      button.disabled = false;
      button.textContent = WORDS['Set it up'];
      return;
    }}
    for (const step of payload.steps || []) {{
      const line = document.createElement('li');
      const verb = document.createElement('b');
      verb.textContent = step[0] + ' ';
      line.appendChild(verb);
      line.appendChild(document.createTextNode(step[1]));
      steps.appendChild(line);
    }}
    /* A step that failed is said, and the console is opened all the same: the
       sign-in is already yours, and the rest is the Settings tab's to finish. */
    if (payload.problem) {{
      said.textContent = payload.problem;
      button.textContent = WORDS['Set up — one thing did not work'];
      after.hidden = false;
      return;
    }}
    location = '/';
  }} catch (error) {{
    said.textContent = String(error);
    button.disabled = false;
    button.textContent = WORDS['Set it up'];
  }}
}}
</script>
""",
        _SETUP_STYLE,
        language,
    )


# The English pages, as they stand: what a test reads, and what a browser that
# says nothing about its language is given.
GATE = gate_page()
SIGN_IN = sign_in_page()
SETUP = setup_page()


def serve(
    config: Config,
    *,
    host: str = "",
    port: int = 0,
    announce: bool = True,
) -> int:
    """Run the console until interrupted. Returns a process exit code."""
    host = host or config.web.host
    port = port or config.web.port
    secret = token(config)
    entry = sign_in(config, secret)

    if host not in LOOPBACK and not config.web.token and entry is None:
        print(
            f"refusing to listen on {host}: behind this port sits a runner that starts\n"
            "Claude Code sessions with bypassPermissions, and a generated token is not a\n"
            "decision you took. Either keep the default 127.0.0.1 and reach it over ssh\n"
            "  ssh -L 8787:127.0.0.1:8787 <this machine>\n"
            "or say so on purpose: web.token, or web.email and web.password."
        )
        return 2

    # What to print as the way in. A console with a sign-in is opened by typing
    # an address, which is the whole point of having one — putting the token
    # back in that line would be telling you to paste a secret anyway. And one
    # nobody has claimed is opened by the address alone: the first connection is
    # what it serves, and asking for a token to reach it would be the circle
    # that page exists to break.
    def opening(address: str) -> str:
        if entry:
            return f"{address}  —  sign in as {entry.email}"
        if claimable(config, entry):
            return f"{address}  —  not set up yet: the first browser to open it sets its password"
        return f"{address}/?token={secret}"

    api = Api(config)
    try:
        server = Console((host, port), Handler, api, secret, entry)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            # The console's unit starts with the machine, so a taken port is the
            # ordinary answer to `serve` rather than a failure: somebody typing
            # it wants the console, and the one already listening is it.
            print(f"already listening on http://{host}:{port} — the console is running")
            print(f"  open  {opening(f'http://{host}:{port}')}")
            print("  stop  systemctl --user stop ticket-runner-web")
            return 0
        print(f"cannot listen on {host}:{port} — {error}")
        return 1

    address = server.server_address
    shown = f"http://{address[0]}:{address[1]}"
    if announce:
        print(f"ticket-runner console on {shown}")
        print(f"  open  {opening(shown)}")
        print(f"  stop  Ctrl-C\n")

    thread = threading.Thread(target=server.serve_forever, name="tr-console", daemon=True)
    thread.start()
    try:
        while thread.is_alive():
            thread.join(1)
    except KeyboardInterrupt:
        if announce:
            print("\nstopping")
    finally:
        api.watch.stop()
        server.shutdown()
        server.server_close()
    return 0
