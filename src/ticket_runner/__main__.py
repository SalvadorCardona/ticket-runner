"""The command line interface.

`run` is what the systemd timer calls; everything else exists so you can find
out what it did without reading a systemd journal.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from datetime import datetime

from . import __version__, config as config_module, git, notion, session, state
from . import update as update_module
from . import workspace as workspace_module
from .projects import Resolver
from .runner import Runner

BOLD, DIM, GREEN, RED, YELLOW, RESET = "", "", "", "", "", ""
if sys.stdout.isatty():
    BOLD, DIM = "\033[1m", "\033[2m"
    GREEN, RED, YELLOW, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


def ok(message: str) -> None:
    print(f"  {GREEN}✓{RESET} {message}")


def bad(message: str) -> None:
    print(f"  {RED}✗{RESET} {message}")


def warn(message: str) -> None:
    print(f"  {YELLOW}!{RESET} {message}")


def title(message: str) -> None:
    print(f"{BOLD}{message}{RESET}")


def _names(reference: str, filename: str) -> bool:
    """Does this log belong to that ticket, however the ID was pasted?

    A full ID, a dashed one, a URL, or just the short form all have to work —
    log files are named by the ticket's *last* eight characters, which is not
    what someone copying an ID from Notion has in hand.
    """
    probe = reference.strip().rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[-1].replace("-", "")
    forms = {probe, probe[-8:]} if len(probe) >= 8 else {probe}
    return any(form and form in filename for form in forms)


def _colour(status: str) -> str:
    """Blocked is not a failure: it is a ticket waiting for you."""
    return {"done": GREEN, "failed": RED, "blocked": YELLOW}.get(status, DIM)


def load_config() -> config_module.Config:
    try:
        configuration = config_module.load()
        configuration.require_usable()
        return configuration
    except config_module.ConfigError as error:
        print(f"{RED}error:{RESET} {error}", file=sys.stderr)
        raise SystemExit(2) from error


# -- commands ----------------------------------------------------------------


def command_run(args: argparse.Namespace) -> int:
    configuration = load_config()
    runner = Runner(
        configuration, dry_run=args.dry_run, announce_idle=sys.stdout.isatty()
    )
    try:
        with state.lock():
            results = runner.tick(limit=args.limit, reference=args.ticket or "")
    except state.Busy as error:
        print(f"{DIM}{error}{RESET}")
        return 0
    except notion.NotionError as error:
        print(f"{RED}Notion:{RESET} {error}", file=sys.stderr)
        return 1
    failures = sum(1 for result in results if result.get("status") == "failed")
    # The timer should only see a failure if the whole run failed: one ticket
    # out of three going wrong is not a service outage.
    return 1 if results and failures == len(results) else 0


def command_list(args: argparse.Namespace) -> int:
    configuration = load_config()
    runner = Runner(configuration, quiet=True)
    tickets, waiting = runner.queue()
    if not tickets and not waiting:
        print("No ticket ready.")
        return 0
    if tickets:
        title(
            f"{len(tickets)} ticket(s) in “{configuration.notion.state('ready')}”, "
            "in the order they will run"
        )
    for position, ticket in enumerate(tickets, 1):
        relation = notion.read(ticket.page, configuration.notion.prop("project")) or []
        project, kind = "?", ""
        if relation:
            try:
                resolved = runner.resolver.resolve(runner.client, relation[0])
                project = resolved.name
                kind = "code" if resolved.is_code else "document"
            except (LookupError, notion.NotionError):
                project = f"{YELLOW}project not found{RESET}"
        badges = [
            str(notion.read(ticket.page, configuration.notion.prop(key)) or "")
            for key in ("priority", "model")
        ]
        tail = " · ".join([part for part in [project, kind, *badges] if part])
        print(f"  {position}. {ticket.title}\n     {DIM}{tail}{RESET}\n     {DIM}{ticket.url}{RESET}")

    if waiting:
        title(f"\n{len(waiting)} ticket(s) waiting for their date")
        now = datetime.now().astimezone()
        for ticket, moment in waiting:
            delay = moment - now
            hours = delay.total_seconds() / 3600
            when = f"in {hours:.0f} h" if hours < 48 else f"in {delay.days} days"
            stamp = moment.strftime("%Y-%m-%d %H:%M")
            print(f"  {ticket.title}\n     {DIM}{stamp} — {when}{RESET}")
    return 0


def command_projects(args: argparse.Namespace) -> int:
    configuration = load_config()
    runner = Runner(configuration, quiet=True)
    seen: dict[str, None] = {}
    for ticket in runner.client.query(runner.database):
        for page_id in notion.read(ticket, configuration.notion.prop("project")) or []:
            seen.setdefault(page_id, None)
    if not seen:
        print("No project referenced by any ticket.")
        return 0
    title(f"Referenced projects ({len(seen)})")
    failed = 0
    for page_id in seen:
        try:
            project = runner.resolver.resolve(runner.client, page_id)
            where = project.path if project.is_code else f"{DIM}document — no repository{RESET}"
            ok(f"{project.name} → {where}")
        except (LookupError, notion.NotionError) as error:
            failed += 1
            bad(str(error).replace("\n", "\n    "))
    return 1 if failed else 0


def command_history(args: argparse.Namespace) -> int:
    entries = state.history(args.number)
    if not entries:
        print("No ticket handled yet.")
        return 0
    for entry in entries:
        status = entry.get("status", "?")
        colour = _colour(status)
        seconds = entry.get("seconds")
        timing = f" {DIM}({seconds / 60:.0f} min){RESET}" if isinstance(seconds, (int, float)) else ""
        cost = entry.get("cost_usd")
        price = f" {DIM}(${float(cost):.2f}){RESET}" if isinstance(cost, (int, float)) else ""
        line = f"  {colour}{status:<7}{RESET} {entry.get('at', '')}  {entry.get('ticket', '')}{timing}{price}"
        print(line)
        detail = entry.get("pull_request") or entry.get("reason") or ""
        if detail:
            print(f"          {DIM}{detail}{RESET}")
    return 0


def command_status(args: argparse.Namespace) -> int:
    try:
        configuration = config_module.load()
    except config_module.ConfigError as error:
        bad(str(error))
        return 2

    title("Timer")
    if shutil.which("systemctl"):
        active = subprocess.run(
            ["systemctl", "--user", "is-enabled", "ticket-runner.timer"],
            capture_output=True, text=True,
        ).stdout.strip()
        timers = subprocess.run(
            ["systemctl", "--user", "list-timers", "ticket-runner.timer", "--no-pager"],
            capture_output=True, text=True,
        ).stdout.strip().splitlines()
        (ok if active == "enabled" else warn)(f"ticket-runner.timer: {active or 'not installed'}")
        for line in timers[1:2]:
            print(f"    {DIM}{line.strip()}{RESET}")
    else:
        warn("no systemd — the runner only runs on demand")

    lock_file = config_module.state_dir() / "run.lock"
    if lock_file.exists():
        warn(f"a run is in progress ({lock_file.read_text().strip()})")
    else:
        ok("no run in progress")

    title("Board")
    try:
        configuration.require_usable()
        runner = Runner(configuration, quiet=True)
        counts: dict[str, int] = {}
        for page in runner.client.query(runner.database):
            name = str(notion.read(page, configuration.notion.prop("status")) or "—")
            counts[name] = counts.get(name, 0) + 1
        if not counts:
            print(f"  {DIM}no ticket{RESET}")
        ready_state = configuration.notion.state("ready")
        for name, number in sorted(counts.items(), key=lambda item: -item[1]):
            highlight = GREEN if name == ready_state else DIM
            print(f"  {highlight}{number:>3}{RESET}  {name}")
    except (config_module.ConfigError, notion.NotionError) as error:
        bad(f"Notion unreachable: {str(error).splitlines()[0]}")

    title("Recent tickets")
    entries = state.history(5)
    if not entries:
        print(f"  {DIM}none{RESET}")
    for entry in entries:
        status = entry.get("status", "?")
        seconds = entry.get("seconds")
        timing = f" {DIM}({seconds / 60:.0f} min){RESET}" if isinstance(seconds, (int, float)) else ""
        print(f"  {_colour(status)}{status:<7}{RESET} {entry.get('ticket', '')}{timing}")
        detail = entry.get("pull_request") or entry.get("reason") or ""
        if detail:
            print(f"          {DIM}{str(detail)[:90]}{RESET}")

    spend = sum(float(entry.get("cost_usd") or 0) for entry in state.history(10_000))
    if spend:
        print(f"\n  {DIM}reported spend so far: ${spend:.2f}{RESET}")
    return 0


def command_logs(args: argparse.Namespace) -> int:
    logs = sorted(state.logs_dir().glob("*.jsonl"))
    if not logs:
        print("No log yet.")
        return 0
    target = logs[-1]
    if args.ticket:
        matches = [path for path in logs if _names(args.ticket, path.name)]
        if not matches:
            print(f"No log for {args.ticket}", file=sys.stderr)
            return 1
        target = matches[-1]
    print(f"{DIM}{target}{RESET}", file=sys.stderr)
    if args.raw:
        print(target.read_text(encoding="utf-8", errors="replace"))
        return 0
    handle = target.open(encoding="utf-8", errors="replace")
    try:
        while True:
            line = handle.readline()
            if not line:
                if not args.follow:
                    return 0
                time.sleep(0.5)
                continue
            rendered = _render(line)
            if rendered:
                print(rendered, flush=True)
    except KeyboardInterrupt:
        return 0
    finally:
        handle.close()


def _render(line: str) -> str:
    """One line of the stream-json feed, reduced to what reads."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return ""
    kind = event.get("type")
    if kind == "assistant":
        pieces = []
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "text" and block.get("text", "").strip():
                pieces.append(block["text"].strip())
            elif block.get("type") == "tool_use":
                name = block.get("name", "?")
                target = block.get("input", {})
                hint = target.get("file_path") or target.get("command") or target.get("pattern") or ""
                pieces.append(f"{DIM}· {name} {str(hint)[:100]}{RESET}")
        return "\n".join(pieces)
    if kind == "result":
        cost = event.get("total_cost_usd") or 0
        return f"{BOLD}— end —{RESET} {event.get('num_turns', 0)} turns · ${cost:.3f}"
    return ""


def command_doctor(args: argparse.Namespace) -> int:
    problems = 0

    title("Configuration")
    try:
        configuration = config_module.load()
        ok(f"{configuration.path}")
    except config_module.ConfigError as error:
        bad(str(error))
        return 2
    try:
        configuration.require_usable()
        ok("Notion token and tickets database are set")
    except config_module.ConfigError as error:
        bad(str(error).splitlines()[0])
        problems += 1

    title("Tools")
    for binary, why in (("git", "required"), ("claude", "required"), ("gh", "for pull requests")):
        path = shutil.which(binary)
        if path:
            version = git.run([binary, "--version"]).out.splitlines()[0] if binary != "gh" else "present"
            ok(f"{binary} — {version}")
        else:
            (bad if why == "required" else warn)(f"{binary} missing ({why})")
            problems += 1 if why == "required" else 0
    if shutil.which("gh"):
        authed = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        (ok if authed.returncode == 0 else warn)(
            "gh authenticated" if authed.returncode == 0 else "gh not authenticated: gh auth login"
        )

    title("Version")
    status = update_module.check()
    if status.reason:
        warn(status.reason)
    elif status.stale:
        warn(f"{status.current[:8]} installed, {status.latest[:8]} available")
    else:
        ok(f"newest version installed ({status.current[:8]})")
    if configuration.runner.auto_update:
        every = configuration.runner.update_interval_seconds
        print(f"  {DIM}checked by a run every {every}s (runner.auto_update){RESET}")
    else:
        print(f"  {DIM}runner.auto_update = false — ticket-runner update to do it by hand{RESET}")

    title("Repositories")
    root = configuration.runner.workspace_root
    if root.is_dir():
        resolver = Resolver(root, configuration.projects)
        count = len(resolver._index())  # noqa: SLF001 — diagnostics
        ok(f"{root} — {count} repository(ies) found")
    else:
        bad(f"{root} does not exist (runner.workspace_root)")
        problems += 1

    if problems:
        print(f"\n{RED}{problems} problem(s) to fix.{RESET}")
        return 1

    title("Notion")
    client = notion.Client(configuration.notion.token)
    try:
        me = client._request("GET", "/users/me")  # noqa: SLF001 — diagnostics
        ok(f"connected as “{me.get('name', 'integration')}”")
    except notion.NotionError as error:
        bad(f"token refused: {error}")
        return 1

    if configuration.notion.workspace:
        title("Notion workspace")
    try:
        space = workspace_module.resolve(client, configuration.notion)
    except notion.NotionError as error:
        for line in str(error).splitlines():
            bad(line.strip())
        warn("every page must be shared with the integration (··· menu → Connections)")
        return 1
    database = space.tickets

    if configuration.notion.workspace:
        listed = ", ".join(f"“{name}”" for name in sorted(space.rows)) or "nothing"
        ok(f"{len(space.rows)} page(s): {listed}")
        for message in space.warnings:
            warn(message)
        if space.context:
            first = space.context.strip().splitlines()[0]
            ok(
                f"“{configuration.notion.page('context')}” — {len(space.context)} characters "
                f"in every prompt: {DIM}{first[:60]}{RESET}"
            )
        for key in ("projects", "agents"):
            if resolved := getattr(space, key):
                ok(f"“{configuration.notion.page(key)}” → database {resolved}")

    title("Tickets database")
    try:
        schema = client.schema(database)
    except notion.NotionError as error:
        bad(f"unreachable: {str(error).splitlines()[0]}")
        warn("the database must be shared with the integration (··· menu → Connections)")
        return 1
    ok(f"readable — {len(schema)} property(ies)")
    reference = configuration.notion.tickets_database or configuration.notion.page("tickets")
    if database != reference:
        warn(f"resolved from “{reference}” to database {database}")

    for key, expected in (
        ("status", ("status", "select")),
        ("project", ("relation",)),
        ("agent", ("rich_text",)),
        ("pull_request", ("url",)),
    ):
        name = configuration.notion.prop(key)
        kind = schema.get(name)
        if kind is None:
            (warn if key in ("agent", "pull_request") else bad)(
                f"property “{name}” missing"
                + (" — the runner will do without it" if key in ("agent", "pull_request") else "")
            )
            problems += 0 if key in ("agent", "pull_request") else 1
        elif kind not in expected:
            warn(f"“{name}” is a {kind}, expected {' or '.join(expected)}")
        else:
            ok(f"“{name}” ({kind})")
    optional = (
        ("session", "url", "a clickable link to the session; as text, the bare ID"),
        ("model", "select", "pick the model per ticket, overriding runner.model"),
        ("priority", "select", "which ready ticket runs first"),
        ("cost", "number", "what the run cost, written back"),
        ("duration", "number", "how long it took, in minutes"),
        ("due", "date", "hold the ticket until that date, then run it"),
        ("role", "relation", "which agent handles the ticket; its page is the role"),
    )
    for key, preferred, why in optional:
        name = configuration.notion.prop(key)
        kind = schema.get(name)
        if kind is None:
            warn(f"“{name}” missing — {why}")
        elif kind != preferred:
            ok(f"“{name}” ({kind}) — {preferred} would be better: {why}")
        else:
            ok(f"“{name}” ({kind})")

    title("Statuses")
    options = client.options(database, configuration.notion.prop("status"))
    if not options:
        warn("the status property offers no options — nothing to check against")
    else:
        for key in ("ready", "running", "done", "failed", "blocked"):
            wanted = configuration.notion.state(key)
            if wanted in options:
                ok(f"{key:<8} → “{wanted}”")
            else:
                bad(f"{key:<8} → “{wanted}” is not offered by the database")
                problems += 1
        print(f"  {DIM}available: {', '.join(options)}{RESET}")

    title("Model")
    ok(f"claude: {session.available() or 'missing'}")
    interval = configuration.runner.interval_seconds
    print(f"  {DIM}one run every {interval}s (ticket-runner enable to apply a change){RESET}")
    print(f"  {DIM}permission_mode = {configuration.runner.permission_mode}{RESET}")

    if problems:
        print(f"\n{RED}{problems} problem(s) to fix.{RESET}")
        return 1
    print(f"\n{GREEN}Everything is in place.{RESET}")
    return 0


def command_config(args: argparse.Namespace) -> int:
    path = config_module.config_path()
    if not path.exists():
        print(f"{path} does not exist — run install.sh again", file=sys.stderr)
        return 1
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    return subprocess.call([editor, str(path)])


def command_clean(args: argparse.Namespace) -> int:
    """Remove what failures left behind: worktrees and scratch directories."""
    state_root = config_module.state_dir()
    directories = [
        directory
        for parent in ("worktrees", "scratch")
        if (state_root / parent).exists()
        for directory in sorted((state_root / parent).iterdir())
    ]
    if not directories:
        print("Nothing left behind.")
        return 0
    title(f"{len(directories)} directory(ies) kept")
    for directory in directories:
        branch = git.git(["rev-parse", "--abbrev-ref", "HEAD"], directory).out
        print(f"  {directory}  {DIM}{branch or 'no repository'}{RESET}")
    if not args.force:
        print(f"\n{DIM}ticket-runner clean --force to remove them{RESET}")
        return 0
    for directory in directories:
        origin = git.git(["rev-parse", "--path-format=absolute", "--git-common-dir"], directory).out
        repo = Path(origin).parent if origin else None
        if repo and repo.exists():
            git.remove_worktree(repo, directory)
        else:
            shutil.rmtree(directory, ignore_errors=True)
        print(f"  removed {directory}")
    removed = state.prune_logs(args.days)
    if removed:
        print(f"  removed {removed} log file(s) older than {args.days} days")
    return 0


def command_update(args: argparse.Namespace) -> int:
    """What a run does once an hour, on demand and out loud."""
    status = update_module.check()
    if status.reason:
        bad(status.reason)
        return 1
    if not status.stale:
        ok(f"already on the newest version ({status.current[:8]})")
        return 0
    print(f"  {status.current[:8]} → {status.latest[:8]}")
    if args.check:
        print(f"  {DIM}ticket-runner update to apply it{RESET}")
        return 0
    try:
        interval = config_module.load().runner.interval_seconds
    except config_module.ConfigError:
        interval = config_module.Runner().interval_seconds
    error = update_module.apply(status, interval)
    if error:
        bad(error)
        return 1
    ok(f"updated to {status.latest[:8]}")
    return 0


def command_open(args: argparse.Namespace) -> int:
    """Handle a ticket-runner:// link. The desktop calls this on a click."""
    try:
        return session.open_link(args.uri)
    except (ValueError, FileNotFoundError) as error:
        print(f"{RED}error:{RESET} {error}", file=sys.stderr)
        return 1


def command_timer(args: argparse.Namespace) -> int:
    if not shutil.which("systemctl"):
        print("systemd not available", file=sys.stderr)
        return 1
    if args.command == "disable":
        return subprocess.call(
            ["systemctl", "--user", "disable", "--now", "ticket-runner.timer"]
        )

    try:
        interval = config_module.load().runner.interval_seconds
    except config_module.ConfigError as error:
        print(f"{RED}error:{RESET} {error}", file=sys.stderr)
        return 2
    update_module.write_units(interval)
    subprocess.call(["systemctl", "--user", "daemon-reload"])
    code = subprocess.call(
        ["systemctl", "--user", "enable", "--now", "ticket-runner.timer"]
    )
    if code == 0:
        every = f"{interval}s" if interval < 120 else f"{interval // 60} min"
        ok(f"timer enabled — one run every {every}")
    return code


# -- entry point -------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ticket-runner",
        description="Turns ready Notion tickets into Claude Code sessions.",
    )
    parser.add_argument("--version", action="version", version=f"ticket-runner {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="handle the ready tickets (one run)")
    run.add_argument("--ticket", help="URL or ID of one ticket, whatever its status")
    run.add_argument("--limit", type=int, help="maximum number of tickets for this run")
    run.add_argument("--dry-run", action="store_true", help="show without changing anything")
    run.set_defaults(function=command_run)

    listing = subparsers.add_parser("list", help="list the ready tickets")
    listing.set_defaults(function=command_list)

    projects = subparsers.add_parser("projects", help="check the project → repository mapping")
    projects.set_defaults(function=command_projects)

    status = subparsers.add_parser("status", help="timer, current run, recent tickets")
    status.set_defaults(function=command_status)

    history = subparsers.add_parser("history", help="tickets already handled")
    history.add_argument("-n", "--number", type=int, default=20)
    history.set_defaults(function=command_history)

    logs = subparsers.add_parser("logs", help="follow a session")
    logs.add_argument("ticket", nargs="?", help="the ticket's ID, in any form")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.add_argument("--raw", action="store_true", help="the raw JSON stream")
    logs.set_defaults(function=command_logs)

    doctor = subparsers.add_parser("doctor", help="full diagnostics")
    doctor.set_defaults(function=command_doctor)

    configure = subparsers.add_parser("config", help="open the configuration")
    configure.set_defaults(function=command_config)

    updating = subparsers.add_parser("update", help="move the installation to the newest version")
    updating.add_argument("--check", action="store_true", help="say what is available, change nothing")
    updating.set_defaults(function=command_update)

    opener = subparsers.add_parser("open", help="open a ticket-runner:// session link")
    opener.add_argument("uri", help="ticket-runner://session/<id>?cwd=<path>")
    opener.set_defaults(function=command_open)

    clean = subparsers.add_parser("clean", help="remove worktrees left by failures")
    clean.add_argument("--force", action="store_true")
    clean.add_argument("--days", type=int, default=14, help="also drop logs older than this")
    clean.set_defaults(function=command_clean)

    for name, help_text in (
        ("enable", "apply runner.interval_seconds and start the timer"),
        ("disable", "stop the timer"),
    ):
        timer = subparsers.add_parser(name, help=help_text)
        timer.set_defaults(function=command_timer)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "function", None):
        parser.print_help()
        return 0
    try:
        return args.function(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
