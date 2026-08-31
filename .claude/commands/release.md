---
description: Cut a release — pick the version, promote the changelog, tag, publish
argument-hint: patch | minor | major | X.Y.Z (or nothing, and I will propose one)
---

Cut a ticket-runner release. Follow `.claude/skills/release/SKILL.md` step by
step — it is the procedure, and it is what the checks in `scripts/release.py`
are written against.

Requested version: **$ARGUMENTS**

If that is empty, read `## [Unreleased]` in `CHANGELOG.md` and the commits since
the last tag, propose `patch`, `minor` or `major` with the one-line reason, and
wait for an answer before touching a file.

Before anything: `git switch main && git pull` — a release is cut from `main`,
never from a feature branch.

Stop at step 5 and ask. Tagging and publishing are visible to everyone who
installs the runner, so show the version, the notes that will become the release
body, and the output of `scripts/release.py check`, and let the maintainer say
go.
