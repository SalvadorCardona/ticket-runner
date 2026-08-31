#!/usr/bin/env python3
"""Cutting a release, in the four gestures that make one.

    python3 scripts/release.py current           what version this tree is
    python3 scripts/release.py notes [VERSION]   the changelog entry, on stdout
    python3 scripts/release.py bump  KIND        promote Unreleased, write the version
    python3 scripts/release.py check [VERSION]   everything that must be true before a tag
    python3 scripts/release.py publish [VERSION] the GitHub release, from the tag

The version lives in exactly one place — `__version__` in
`src/ticket_runner/__init__.py` — and the notes live in exactly one other,
`CHANGELOG.md`. Everything else is derived: the tag is `v` and the version, the
release title is the name and the version, the release body is the changelog
section. Nothing here invents a number or writes prose; it moves what a human
already wrote into the shapes git and GitHub want.

`bump` is the only verb that changes a file, and it changes both of them at
once: a version written without its changelog entry, or an entry promoted
without its version, is the failure mode this script exists to make impossible.

`publish` is idempotent. It is run twice on purpose — once by the release
workflow when the tag lands, and once by hand when Actions is not the one
doing it — and the second run finds the release already there and says so.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "src" / "ticket_runner" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
NAME = "ticket-runner"

# X.Y.Z, with room for the -rc.1 nobody has needed yet but everybody eventually does.
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")

# "## [0.2.0] - 2026-08-31", "## [0.2.0] — 2026-08-31", "## [Unreleased]".
# The dash is whichever one the hand that wrote the line reached for.
HEADING = re.compile(r"^##\s+\[(?P<version>[^\]]+)\]\s*(?:[-–—]\s*(?P<date>.+?))?\s*$")

UNRELEASED = "Unreleased"


class Problem(Exception):
    """Something a human has to decide about. Printed, never raised at them."""


# -- the version -------------------------------------------------------------


def parse(version: str) -> tuple[int, int, int, str]:
    match = VERSION.match(version.strip())
    if not match:
        raise Problem(f"{version!r} is not a version: expected X.Y.Z, optionally X.Y.Z-rc.1")
    major, minor, patch, pre = match.groups()
    return int(major), int(minor), int(patch), pre or ""


def next_version(current: str, kind: str, first: bool = False) -> str:
    """`patch`, `minor`, `major` — or an explicit version, which wins over all three.

    An explicit version has to move *forward*: releasing 0.1.0 again, or going
    back to it, is a mistake that only shows up once the tag is published.

    `first` is the one exception, and it happens once in a repository's life.
    Before anything has been released, `__version__` is not the last release —
    there isn't one — it is the number the tree is being prepared under. Asking
    for exactly that number is then the right request, and the only way to cut a
    first release under the version the code already claims.
    """
    major, minor, patch, _ = parse(current)
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    if kind == "patch":
        return f"{major}.{minor}.{patch + 1}"
    parse(kind)
    if order(kind) < order(current) or (order(kind) == order(current) and not first):
        raise Problem(f"{kind} does not come after {current} — a release only moves forward")
    return kind


def order(version: str) -> tuple[int, int, int, int, str]:
    """Sortable. A prerelease comes *before* the release it leads to."""
    major, minor, patch, pre = parse(version)
    return (major, minor, patch, 0 if pre else 1, pre)


def read_version(init: Path | None = None) -> str:
    text = (init or INIT).read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise Problem(f"no __version__ in {init or INIT}")
    return match.group(1)


def write_version(version: str, init: Path | None = None) -> None:
    path = init or INIT
    text = path.read_text(encoding="utf-8")
    text, count = re.subn(
        r'^__version__\s*=\s*"[^"]+"',
        f'__version__ = "{version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise Problem(f"no __version__ to rewrite in {path}")
    path.write_text(text, encoding="utf-8")


# -- the changelog -----------------------------------------------------------


def sections(text: str) -> list[tuple[str, str, str]]:
    """Every `## [...]` section, in the order the file has them: (version, date, body)."""
    found: list[tuple[str, str, str]] = []
    lines = text.splitlines()
    starts = [(i, m) for i, line in enumerate(lines) if (m := HEADING.match(line))]
    for position, (index, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body = "\n".join(lines[index + 1 : end]).strip("\n")
        found.append((match.group("version"), (match.group("date") or "").strip(), body))
    return found


def released(text: str) -> list[tuple[str, str, str]]:
    return [entry for entry in sections(text) if entry[0] != UNRELEASED]


def notes_for(text: str, version: str) -> str:
    for name, _date, body in sections(text):
        if name == version:
            if not body.strip():
                raise Problem(f"the {version} section of CHANGELOG.md is empty")
            return body.strip()
    raise Problem(f"CHANGELOG.md has no [{version}] section")


def promote(text: str, version: str, date: str) -> str:
    """Turn `## [Unreleased]` into `## [version] - date`, and open a fresh Unreleased.

    Refuses an empty Unreleased: a release with no notes is a tag, and a tag is
    not what anybody came here for.
    """
    for name, _date, body in sections(text):
        if name == version:
            raise Problem(f"CHANGELOG.md already has a [{version}] section")
    for name, _date, body in sections(text):
        if name == UNRELEASED:
            if not body.strip():
                raise Problem("nothing under [Unreleased] — there is no release to cut")
            break
    else:
        raise Problem("CHANGELOG.md has no [Unreleased] section to promote")

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = HEADING.match(line.rstrip("\n"))
        if match and match.group("version") == UNRELEASED:
            lines[index] = f"## [{UNRELEASED}]\n\n## [{version}] - {date}\n"
            return "".join(lines)
    raise Problem("CHANGELOG.md has no [Unreleased] section to promote")  # unreachable


# -- git and gh --------------------------------------------------------------


def git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=False, timeout=120
    )


def out(*arguments: str) -> str:
    return git(*arguments).stdout.strip()


def tag_exists(tag: str) -> bool:
    """Locally *and* on the remote: a tag somebody else pushed is just as published.

    A remote that cannot be reached is not an answer, and answering "no" to it
    would let `check` bless a tag that already exists. It says so instead.
    """
    if out("tag", "--list", tag):
        return True
    try:
        looked = git("ls-remote", "--exit-code", "--tags", "origin", tag)
    except subprocess.SubprocessError as error:
        raise Problem(f"origin could not be asked whether {tag} exists: {error}") from error
    if looked.returncode not in (0, 2):
        raise Problem(f"origin could not be asked whether {tag} exists: {looked.stderr.strip()}")
    return looked.returncode == 0


# -- the verbs ---------------------------------------------------------------


def command_current(arguments: argparse.Namespace) -> int:
    print(read_version())
    return 0


def command_notes(arguments: argparse.Namespace) -> int:
    version = arguments.version or read_version()
    print(notes_for(CHANGELOG.read_text(encoding="utf-8"), version))
    return 0


def command_bump(arguments: argparse.Namespace) -> int:
    current = read_version()
    text = CHANGELOG.read_text(encoding="utf-8")
    version = next_version(current, arguments.kind, first=not released(text))
    date = dt.date.today().isoformat()
    text = promote(text, version, date)
    CHANGELOG.write_text(text, encoding="utf-8")
    write_version(version)
    print(f"{current} → {version}  ({date})")
    print(f"  {INIT.relative_to(ROOT)}")
    print(f"  {CHANGELOG.relative_to(ROOT)}")
    print(f"\nreview the diff, commit it, then: {sys.argv[0]} check")
    return 0


def command_check(arguments: argparse.Namespace) -> int:
    """Everything that must be true before a tag exists. Says all of it, not the first."""
    version = arguments.version or read_version()
    problems: list[str] = []

    try:
        parse(version)
    except Problem as error:
        problems.append(str(error))

    if version != read_version():
        problems.append(f"__version__ is {read_version()}, not {version}")

    text = CHANGELOG.read_text(encoding="utf-8")
    try:
        notes_for(text, version)
    except Problem as error:
        problems.append(str(error))

    newest = released(text)
    if newest and newest[0][0] != version:
        problems.append(
            f"the newest released section of CHANGELOG.md is [{newest[0][0]}], not [{version}]"
        )

    tag = f"v{version}"
    try:
        if tag_exists(tag):
            problems.append(
                f"{tag} already exists — releasing it again would move a published tag"
            )
    except Problem as error:
        problems.append(str(error))

    if out("status", "--porcelain"):
        problems.append("the working tree has uncommitted changes")

    branch = out("rev-parse", "--abbrev-ref", "HEAD")
    if branch != arguments.branch:
        problems.append(f"on {branch}, not {arguments.branch} (--branch says otherwise)")

    for problem in problems:
        print(f"  ✗ {problem}")
    if problems:
        return 1
    print(f"  ✓ {NAME} {version} is ready to tag as {tag}")
    return 0


def command_publish(arguments: argparse.Namespace) -> int:
    """Create the GitHub release for a tag that already exists. Twice is fine."""
    version = arguments.version or read_version()
    tag = f"v{version}"

    reference = os.environ.get("GITHUB_REF_NAME", "")
    if reference and reference != tag:
        print(f"  ✗ the tag being built is {reference}, but __version__ says {tag}")
        print("    the tag was placed on a commit that does not carry its own version")
        return 1

    body = notes_for(CHANGELOG.read_text(encoding="utf-8"), version)

    if subprocess.run(
        ["gh", "release", "view", tag], cwd=ROOT, capture_output=True, text=True, check=False
    ).returncode == 0:
        print(f"  · {tag} is already released — nothing to do")
        return 0

    created = subprocess.run(
        ["gh", "release", "create", tag, "--title", f"{NAME} {version}", "--notes-file", "-"],
        cwd=ROOT,
        input=body,
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        print(f"  ✗ gh release create: {created.stderr.strip() or created.stdout.strip()}")
        return 1
    print(f"  ✓ {created.stdout.strip() or tag}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/release.py", description=f"Cut a {NAME} release."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    current = subparsers.add_parser("current", help="the version this tree carries")
    current.set_defaults(function=command_current)

    notes = subparsers.add_parser("notes", help="the changelog entry for a version")
    notes.add_argument("version", nargs="?")
    notes.set_defaults(function=command_notes)

    bump = subparsers.add_parser("bump", help="promote Unreleased and write the new version")
    bump.add_argument("kind", help="patch | minor | major | X.Y.Z")
    bump.set_defaults(function=command_bump)

    check = subparsers.add_parser("check", help="what must be true before the tag")
    check.add_argument("version", nargs="?")
    check.add_argument("--branch", default="main", help="the branch a release is cut from")
    check.set_defaults(function=command_check)

    publish = subparsers.add_parser("publish", help="the GitHub release, from an existing tag")
    publish.add_argument("version", nargs="?")
    publish.set_defaults(function=command_publish)

    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return int(arguments.function(arguments))
    except Problem as error:
        print(f"  ✗ {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
