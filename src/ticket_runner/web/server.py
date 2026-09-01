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
  token is refused rather than served;
- every request carries a token — as a header, or as the cookie the first
  `?token=` sets;
- a request from a browser page that is not the console is rejected: writes
  demand a header a cross-origin form cannot set, and the `Host` header must
  name the address the console was reached on, which is what stops a hostile
  page from resolving its own domain to 127.0.0.1 and talking to you through it.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import queue
import re
import secrets
import socket
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import config as config_module
from .. import notion
from ..config import Config, state_dir
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


class Console(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, api: Api, secret: str) -> None:
        super().__init__(address, handler)
        self.api = api
        self.secret = secret


class Handler(BaseHTTPRequestHandler):
    server_version = "ticket-runner"
    protocol_version = "HTTP/1.1"

    # -- plumbing -------------------------------------------------------------

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return  # a console is not a web server; its log is the terminal it runs in

    @property
    def api(self) -> Api:
        return self.server.api  # type: ignore[attr-defined]

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
        secret = self.server.secret  # type: ignore[attr-defined]
        offered = (query.get("token") or [""])[0] or self._presented()
        return bool(offered) and hmac.compare_digest(offered, secret)

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
        # screenshot of the console.
        if query.get("token") and route == "/":
            return self._send(
                303,
                b"",
                "text/plain",
                {
                    "Location": "/",
                    "Set-Cookie": (
                        f"{COOKIE}={query['token'][0]}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000"
                    ),
                },
            )

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
                return self._json({"projects": sorted(
                    self.api.projects().values(), key=lambda item: item["name"].lower()
                )})
            if route == "/api/history":
                return self._json(self.api.history())
            if route == "/api/chat":
                return self._json({"messages": self.api.chat.history(), **self.api.chat.state()})
            if route == "/api/settings":
                return self._json(self.api.settings())
            if route == "/api/logs":
                return self._json(self.api.logs())
            if match := re.fullmatch(r"/api/logs/([\w.\-]+)", route):
                return self._json(self.api.log(match.group(1)))
        except notion.NotionError as error:
            return self._fail(502, f"Notion: {str(error).splitlines()[0]}")
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
        if not self._authorised(parse_qs(parsed.query)):
            return self._fail(401, "token missing or wrong")
        # A cookie alone is not consent: a page you have open elsewhere can post
        # a form to this port with your cookie attached, but it cannot set a
        # header of its own without a preflight this server never answers.
        if self.headers.get(GUARD_HEADER) != "1":
            return self._fail(403, "this request did not come from the console")

        payload = self._body()
        try:
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
            if route == "/api/command":
                return self._json(self.api.commands.start(str(payload.get("line", ""))))
            if route == "/api/chat":
                return self._json(self.api.chat.send(str(payload.get("text", ""))))
            if route == "/api/chat/reset":
                return self._json(self.api.chat.reset())
            if route == "/api/settings":
                return self._json(self.api.save_settings(payload))
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
        except notion.NotionError as error:
            return self._fail(502, f"Notion: {str(error).splitlines()[0]}")
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

    def _unauthorised(self, route: str) -> None:
        if route.startswith("/api/"):
            return self._fail(401, "token missing or wrong")
        self._send(401, GATE.encode(), "text/html; charset=utf-8")

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


GATE = """<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ticket-runner — token</title>
<style>
 body{background:#0f1115;color:#e7e9ee;font:15px/1.6 ui-sans-serif,system-ui,sans-serif;
      display:grid;place-items:center;min-height:100vh;margin:0}
 form{width:min(28rem,90vw);background:#171a21;border:1px solid #262b36;border-radius:14px;padding:1.6rem}
 h1{font-size:1.1rem;margin:0 0 .4rem} p{color:#98a2b3;margin:.2rem 0 1.2rem;font-size:.9rem}
 input{width:100%;box-sizing:border-box;background:#0f1115;border:1px solid #2c3240;color:inherit;
       border-radius:9px;padding:.7rem .8rem;font:inherit}
 button{margin-top:.9rem;width:100%;background:#3b82f6;color:#fff;border:0;border-radius:9px;
        padding:.7rem;font:inherit;font-weight:600;cursor:pointer}
 code{background:#0f1115;padding:.15rem .4rem;border-radius:6px;color:#c8cedb}
</style>
<form onsubmit="location='/?token='+encodeURIComponent(this.t.value.trim());return false">
  <h1>ticket-runner</h1>
  <p>This console needs its token. <code>ticket-runner serve</code> prints it,
     and it is kept in <code>~/.local/state/ticket-runner/web/token</code>.</p>
  <input name="t" autofocus placeholder="token" autocomplete="off" spellcheck="false">
  <button type="submit">Open the console</button>
</form>
"""


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

    if host not in LOOPBACK and not config.web.token:
        print(
            f"refusing to listen on {host}: behind this port sits a runner that starts\n"
            "Claude Code sessions with bypassPermissions, and a generated token is not a\n"
            "decision you took. Either keep the default 127.0.0.1 and reach it over ssh\n"
            "  ssh -L 8787:127.0.0.1:8787 <this machine>\n"
            "or set web.token in your configuration on purpose."
        )
        return 2

    api = Api(config)
    try:
        server = Console((host, port), Handler, api, secret)
    except OSError as error:
        print(f"cannot listen on {host}:{port} — {error}")
        return 1

    address = server.server_address
    shown = f"http://{address[0]}:{address[1]}"
    if announce:
        print(f"ticket-runner console on {shown}")
        print(f"  open  {shown}/?token={secret}")
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
