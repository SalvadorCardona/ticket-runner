"""L'interface en ligne de commande.

`run` est ce que le minuteur systemd appelle ; tout le reste existe pour qu'on
puisse comprendre ce qu'il a fait sans lire un journal systemd.
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

from . import __version__, config as config_module, git, notion, session, state
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


def load_config() -> config_module.Config:
    try:
        configuration = config_module.load()
        configuration.require_usable()
        return configuration
    except config_module.ConfigError as error:
        print(f"{RED}erreur :{RESET} {error}", file=sys.stderr)
        raise SystemExit(2) from error


# -- commandes ---------------------------------------------------------------


def command_run(args: argparse.Namespace) -> int:
    configuration = load_config()
    runner = Runner(configuration, dry_run=args.dry_run)
    try:
        with state.lock():
            results = runner.tick(limit=args.limit, reference=args.ticket or "")
    except state.Busy as error:
        print(f"{DIM}{error}{RESET}")
        return 0
    except notion.NotionError as error:
        print(f"{RED}Notion :{RESET} {error}", file=sys.stderr)
        return 1
    failures = sum(1 for result in results if result.get("status") == "failed")
    # Le minuteur ne doit voir un échec que si le tour entier a échoué : un
    # ticket raté sur trois n'est pas une panne du service.
    return 1 if results and failures == len(results) else 0


def command_list(args: argparse.Namespace) -> int:
    configuration = load_config()
    runner = Runner(configuration, quiet=True)
    tickets = runner.ready()
    if not tickets:
        print("Aucun ticket prêt.")
        return 0
    title(f"{len(tickets)} ticket(s) en « {configuration.notion.state('ready')} »")
    for ticket in tickets:
        relation = notion.read(ticket.page, configuration.notion.prop("project")) or []
        project = "?"
        if relation:
            try:
                project = runner.resolver.resolve(runner.client, relation[0]).name
            except (LookupError, notion.NotionError):
                project = f"{YELLOW}projet non situé{RESET}"
        print(f"  {ticket.title}\n    {DIM}{project} · {ticket.url}{RESET}")
    return 0


def command_projects(args: argparse.Namespace) -> int:
    configuration = load_config()
    runner = Runner(configuration, quiet=True)
    seen: dict[str, None] = {}
    for ticket in runner.client.query(runner.database):
        for page_id in notion.read(ticket, configuration.notion.prop("project")) or []:
            seen.setdefault(page_id, None)
    if not seen:
        print("Aucun projet référencé par un ticket.")
        return 0
    title(f"Projets référencés ({len(seen)})")
    failed = 0
    for page_id in seen:
        try:
            project = runner.resolver.resolve(runner.client, page_id)
            ok(f"{project.name} → {project.path}")
        except (LookupError, notion.NotionError) as error:
            failed += 1
            bad(str(error).replace("\n", "\n    "))
    return 1 if failed else 0


def command_history(args: argparse.Namespace) -> int:
    entries = state.history(args.number)
    if not entries:
        print("Aucun ticket traité pour l'instant.")
        return 0
    for entry in entries:
        status = entry.get("status", "?")
        colour = GREEN if status == "done" else RED if status == "failed" else DIM
        line = f"  {colour}{status:<7}{RESET} {entry.get('at', '')}  {entry.get('ticket', '')}"
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

    title("Minuteur")
    if shutil.which("systemctl"):
        active = subprocess.run(
            ["systemctl", "--user", "is-enabled", "ticket-runner.timer"],
            capture_output=True, text=True,
        ).stdout.strip()
        timers = subprocess.run(
            ["systemctl", "--user", "list-timers", "ticket-runner.timer", "--no-pager"],
            capture_output=True, text=True,
        ).stdout.strip().splitlines()
        (ok if active == "enabled" else warn)(f"ticket-runner.timer : {active or 'absent'}")
        for line in timers[1:2]:
            print(f"    {DIM}{line.strip()}{RESET}")
    else:
        warn("systemd absent — le runner ne tourne qu'à la demande")

    lock_file = config_module.state_dir() / "run.lock"
    if lock_file.exists():
        warn(f"un tour est en cours ({lock_file.read_text().strip()})")
    else:
        ok("aucun tour en cours")

    title("Tickets")
    try:
        configuration.require_usable()
        runner = Runner(configuration, quiet=True)
        ready = runner.ready()
        ok(f"{len(ready)} prêt(s) en « {configuration.notion.state('ready')} »")
    except (config_module.ConfigError, notion.NotionError) as error:
        bad(f"Notion injoignable : {str(error).splitlines()[0]}")

    title("Derniers tickets")
    entries = state.history(5)
    if not entries:
        print(f"  {DIM}aucun{RESET}")
    for entry in entries:
        status = entry.get("status", "?")
        colour = GREEN if status == "done" else RED if status == "failed" else DIM
        print(f"  {colour}{status:<7}{RESET} {entry.get('ticket', '')}")
    return 0


def command_logs(args: argparse.Namespace) -> int:
    logs = sorted(state.logs_dir().glob("*.jsonl"))
    if not logs:
        print("Aucun journal.")
        return 0
    target = logs[-1]
    if args.ticket:
        matches = [path for path in logs if args.ticket[:8] in path.name]
        if not matches:
            print(f"Aucun journal pour {args.ticket}", file=sys.stderr)
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
    """Une ligne du flux stream-json, ramenée à ce qui se lit."""
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
        return f"{BOLD}— fin —{RESET} {event.get('num_turns', 0)} tours · {cost:.3f} $"
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
        ok("jeton Notion et base de tickets renseignés")
    except config_module.ConfigError as error:
        bad(str(error).splitlines()[0])
        problems += 1

    title("Outils")
    for binary, why in (("git", "obligatoire"), ("claude", "obligatoire"), ("gh", "pour les pull requests")):
        path = shutil.which(binary)
        if path:
            version = git.run([binary, "--version"]).out.splitlines()[0] if binary != "gh" else "présent"
            ok(f"{binary} — {version}")
        else:
            (bad if why == "obligatoire" else warn)(f"{binary} absent ({why})")
            problems += 1 if why == "obligatoire" else 0
    if shutil.which("gh"):
        authed = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        (ok if authed.returncode == 0 else warn)(
            "gh authentifié" if authed.returncode == 0 else "gh non authentifié : gh auth login"
        )

    title("Espace de travail")
    root = configuration.runner.workspace_root
    if root.is_dir():
        resolver = Resolver(root, configuration.projects)
        count = len(resolver._index())  # noqa: SLF001 — diagnostic
        ok(f"{root} — {count} dépôt(s) repérés")
    else:
        bad(f"{root} n'existe pas (runner.workspace_root)")
        problems += 1

    if problems:
        print(f"\n{RED}{problems} problème(s) à corriger.{RESET}")
        return 1

    title("Notion")
    client = notion.Client(configuration.notion.token)
    try:
        me = client._request("GET", "/users/me")  # noqa: SLF001 — diagnostic
        ok(f"connecté en tant que « {me.get('name', 'intégration')} »")
    except notion.NotionError as error:
        bad(f"jeton refusé : {error}")
        return 1

    try:
        database = client.resolve_database(configuration.notion.tickets_database)
        schema = client.schema(database)
    except notion.NotionError as error:
        bad(f"base de tickets inaccessible : {str(error).splitlines()[0]}")
        warn("la base doit être partagée avec l'intégration (menu ··· → Connexions)")
        return 1
    ok(f"base de tickets lisible — {len(schema)} propriété(s)")
    if database != configuration.notion.tickets_database:
        warn(f"l'ID configuré est celui de la page ; base utilisée : {database}")

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
                f"propriété « {name} » absente"
                + (" — le runner s'en passera" if key in ("agent", "pull_request") else "")
            )
            problems += 0 if key in ("agent", "pull_request") else 1
        elif kind not in expected:
            warn(f"« {name} » est de type {kind}, attendu {' ou '.join(expected)}")
        else:
            ok(f"« {name} » ({kind})")
    session_property = configuration.notion.prop("session")
    if session_property not in schema:
        warn(f"propriété « {session_property} » absente — l'ID de session ira en commentaire")

    title("Modèle")
    ok(f"claude : {session.available() or 'absent'}")
    print(f"  {DIM}permission_mode = {configuration.runner.permission_mode}{RESET}")

    if problems:
        print(f"\n{RED}{problems} problème(s) à corriger.{RESET}")
        return 1
    print(f"\n{GREEN}Tout est en place.{RESET}")
    return 0


def command_config(args: argparse.Namespace) -> int:
    path = config_module.config_path()
    if not path.exists():
        print(f"{path} n'existe pas — relancez install.sh", file=sys.stderr)
        return 1
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    return subprocess.call([editor, str(path)])


def command_clean(args: argparse.Namespace) -> int:
    root = config_module.state_dir() / "worktrees"
    directories = sorted(root.iterdir()) if root.exists() else []
    if not directories:
        print("Aucun worktree résiduel.")
        return 0
    title(f"{len(directories)} worktree(s) conservé(s)")
    for directory in directories:
        branch = git.git(["rev-parse", "--abbrev-ref", "HEAD"], directory).out or "?"
        print(f"  {directory}  {DIM}{branch}{RESET}")
    if not args.force:
        print(f"\n{DIM}ticket-runner clean --force pour les supprimer{RESET}")
        return 0
    for directory in directories:
        origin = git.git(["rev-parse", "--path-format=absolute", "--git-common-dir"], directory).out
        repo = Path(origin).parent if origin else None
        if repo and repo.exists():
            git.remove_worktree(repo, directory)
        else:
            shutil.rmtree(directory, ignore_errors=True)
        print(f"  supprimé {directory}")
    return 0


def command_timer(args: argparse.Namespace) -> int:
    if not shutil.which("systemctl"):
        print("systemd absent", file=sys.stderr)
        return 1
    action = ["enable", "--now"] if args.command == "enable" else ["disable", "--now"]
    return subprocess.call(["systemctl", "--user", *action, "ticket-runner.timer"])


# -- entrée ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ticket-runner",
        description="Transforme les tickets Notion « prêts » en sessions Claude Code.",
    )
    parser.add_argument("--version", action="version", version=f"ticket-runner {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="traiter les tickets prêts (un tour)")
    run.add_argument("--ticket", help="URL ou ID d'un ticket précis, quel que soit son statut")
    run.add_argument("--limit", type=int, help="nombre maximal de tickets pour ce tour")
    run.add_argument("--dry-run", action="store_true", help="montrer sans rien modifier")
    run.set_defaults(function=command_run)

    listing = subparsers.add_parser("list", help="lister les tickets prêts")
    listing.set_defaults(function=command_list)

    projects = subparsers.add_parser("projects", help="vérifier la correspondance projet → dépôt")
    projects.set_defaults(function=command_projects)

    status = subparsers.add_parser("status", help="minuteur, tour en cours, derniers tickets")
    status.set_defaults(function=command_status)

    history = subparsers.add_parser("history", help="tickets traités")
    history.add_argument("-n", "--number", type=int, default=20)
    history.set_defaults(function=command_history)

    logs = subparsers.add_parser("logs", help="suivre une session")
    logs.add_argument("ticket", nargs="?", help="début de l'ID du ticket")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.add_argument("--raw", action="store_true", help="le flux JSON brut")
    logs.set_defaults(function=command_logs)

    doctor = subparsers.add_parser("doctor", help="diagnostic complet")
    doctor.set_defaults(function=command_doctor)

    configure = subparsers.add_parser("config", help="ouvrir la configuration")
    configure.set_defaults(function=command_config)

    clean = subparsers.add_parser("clean", help="supprimer les worktrees d'échecs")
    clean.add_argument("--force", action="store_true")
    clean.set_defaults(function=command_clean)

    for name, help_text in (("enable", "activer le minuteur"), ("disable", "arrêter le minuteur")):
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
