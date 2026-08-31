---
name: release
description: Cut a ticket-runner release — pick the version, promote the changelog, tag it, and publish the GitHub release. Use when asked to release, ship, publish, cut a version, tag a version, bump the version, or prepare a changelog entry for a release.
---

# Releasing ticket-runner

A release is one number, one changelog entry, one tag and one GitHub release,
and they all have to say the same thing. `scripts/release.py` is what keeps them
saying it; this skill is the order to do things in and the judgement calls the
script cannot make for you.

## Where the truth lives

| What | Where | Who writes it |
|---|---|---|
| the version | `__version__` in `src/ticket_runner/__init__.py` | `release.py bump`, never by hand |
| the notes | the `## [Unreleased]` section of `CHANGELOG.md` | whoever merges a change |
| the tag | `v<version>` on `main` | you, at step 5 |
| the release | GitHub, body taken from the changelog | the `release` workflow, on the tag |

Everything downstream is derived. `ticket-runner --version`, the version in the
web console header, the release title and the release body all read from those
two files, so the two files are the only ones to edit.

## Picking the number

Semantic versioning, read from the *installation's* point of view — a runner
already installed on somebody's machine, which updates itself:

- **major** — that installation needs a hand to keep working. A configuration
  key renamed, a Notion property that now has to exist, a command removed.
- **minor** — the runner gained something. A new command, a new channel, a new
  thing a ticket can do.
- **patch** — the runner stopped getting something wrong, and nobody has to
  change anything.

If a change is in `[Unreleased]` under `### Removed` or `### Changed` and an
existing configuration would break on it, it is a major, whatever else is in the
list. Say which of the three you chose and why, before you run anything.

While the version is below `1.0.0`, a breaking change is a **minor**, not a
major — that is what `0.x` means. Do not push the project to `1.0.0` on your own
judgement; that is the maintainer's call, so ask.

## The five steps

Run them from `main`, up to date, with a clean tree.

1. **Read what is being released.** `git log --oneline "$(git describe --tags
   --abbrev=0 2>/dev/null || echo HEAD~20)"..HEAD` and the `[Unreleased]`
   section side by side. If a merged change is missing from the changelog, add
   it now, in the file's voice — what a user can do today that they could not do
   yesterday, not the commit subject. This is the step that takes the thinking;
   the rest is mechanical.

2. **Bump.** `python3 scripts/release.py bump minor` (or `patch`, `major`, or an
   explicit `X.Y.Z`). It promotes `[Unreleased]` to `## [X.Y.Z] - <today>`,
   opens a fresh empty `[Unreleased]`, and rewrites `__version__` — both files,
   or neither. It refuses an empty `[Unreleased]`, a version that already has a
   section, and a version that does not move forward.

3. **Check.** `python3 tests/run.py` and then `python3 scripts/release.py
   check`. `check` prints *every* problem it finds, not the first: the version
   and the changelog disagreeing, a tag that already exists, a dirty tree, the
   wrong branch. Do not go on with any of them printed.

4. **Commit.** `git commit -am "release: X.Y.Z"` and push it to `main`. The
   version commit lands before the tag, always — a tag pointing at a commit that
   does not carry its own version is what step 5's guard exists to catch.

5. **Tag and publish.** This is the outward-facing, hard-to-undo step: a
   published tag and a release are visible to everyone who installs the runner.
   **Ask the maintainer before running it**, showing them the version, the
   notes, and what step 3 said.

   ```sh
   git tag -a "v$(python3 scripts/release.py current)" \
           -m "ticket-runner $(python3 scripts/release.py current)"
   git push origin "v$(python3 scripts/release.py current)"
   ```

   The tag push is the whole request: `.github/workflows/release.yml` re-runs the
   suite at that commit and creates the GitHub release from the changelog
   section. Watch it — `gh run watch` — and confirm with `gh release view
   "v$(...)"`. If Actions did not run it, do the same thing by hand from a
   checkout of the tag: `python3 scripts/release.py publish`. It is idempotent,
   so trying it after the workflow already succeeded is safe and says so.

## What can go wrong, and what to do

- **`check` says the tag already exists.** Published tags do not move. Cut the
  next patch instead.
- **The release is wrong but the tag is right.** Edit `CHANGELOG.md` on `main`
  and `gh release edit vX.Y.Z --notes-file -`. Never re-tag.
- **The tag is on the wrong commit.** If nobody has installed it yet, delete the
  tag and the release (`git push origin :vX.Y.Z`, `gh release delete`) and start
  again from step 4 — and say plainly that you are doing it. Otherwise, cut the
  next patch.
- **`publish` says the tag and `__version__` disagree.** The tag went on a
  commit from before the bump. Move the tag, not the version.

## What a release does *not* change

The runner's self-update follows the branch it was installed from, commit by
commit, not tags — see `src/ticket_runner/update.py`. An installation on `main`
therefore picks up work as it is merged and does not wait for a release. Tags
are for people: the changelog somebody reads, and `TR_REF=v0.2.0` for an
installation that wants to sit still. Do not change the updater to follow tags
as part of a release; that is a separate decision, and a large one.
