# ticket-runner

**Your Notion tickets, played by Claude Code.** You write a ticket, you move it to
*Not started*, and a few minutes later a pull request is waiting for you — its own branch,
its commits, a description, and the session link in the ticket's comments.

The runner lives on your machine, in the background, across **all of your projects at
once**: it is the ticket's `Project` relation that decides which repository it goes to
work in.

```
Notion                    ticket-runner                     git
──────                    ─────────────                     ───
Not started    ──────▶    claims the ticket
                          git worktree + branch       ──▶   ticket/remove-the-header-3ca45168
In progress    ◀──────    claude --print
                          commits verified
Done + PR      ◀──────    push + gh pr create         ──▶   pull request to review
```

---

## Installation

```sh
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/install.sh | sh
```

The script checks the dependencies, installs the `ticket-runner` command into
`~/.local/bin`, asks for your Notion token, and arms a systemd timer that picks up ready
tickets **every 30 minutes**. Then:

```sh
ticket-runner doctor
```

which tells you, line by line, what is still missing.

Running the same command again **updates** the installation: the code is replaced, your
configuration is kept.

> **Requirements** — Linux with systemd in the user session, `python3` >= 3.11 (no
> dependencies to install, everything is in the standard library), `git`,
> [Claude Code](https://claude.com/claude-code), and `gh` authenticated for pull requests.

| Variable | Effect |
| --- | --- |
| `TR_INTERVAL=15` | minutes between two runs (default: 30) |
| `TR_NO_SERVICE=1` | no timer: you run `ticket-runner run` yourself |
| `TR_SRC=.` | install from a local clone, without the network |

---

## Configuration

Everything lives in **`~/.config/ticket-runner/config.toml`**, created by the installer
with mode `600` — it holds your Notion token. `ticket-runner config` opens it in
`$EDITOR`.

### 1. Create a Notion integration

The runner works alone, on your machine, at three in the morning. It needs an identity of
its own: an **internal integration**, which is a robot account with its own token.

On [notion.so/my-integrations](https://www.notion.so/my-integrations) → **New
integration** → give it a name (`ticket-runner`), pick your workspace, type **Internal**.
Copy the token it shows you; it starts with `ntn_`.

### 2. Give the token to the runner

Two lines to fill in, and only two:

```toml
[notion]
token = "ntn_your_real_token_here"

# The URL of the database is enough — the ID is extracted from it. If your tickets
# database is inline inside a page, the page URL works too: the runner looks inside
# and finds the database on its own.
tickets_database = "https://www.notion.so/workspace/Tickets-3c3451680af480f5b1aad0785c0322b4"
```

Three ways to get them in, whichever you prefer:

```sh
ticket-runner config      # opens the TOML in your editor — the cleanest

# or let the installer ask you (it does, on a fresh install):
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/install.sh | sh

# or in one line:
sed -i 's|^token = .*|token = "ntn_…"|' ~/.config/ticket-runner/config.toml
```

### 3. Share the databases with the integration — the step everyone forgets

A valid token on a database that was never shared answers `object not found`, and nothing
about it hints at why. On **the tickets database and the projects database alike**: the
`···` menu, top right → **Connections** → your integration. The first one to read the
tickets, the second to know which repository to work in.

Then:

```sh
ticket-runner doctor
```

which checks the token, the access to the database, the type of every column and the
presence of each status — and names whichever of those was missed.

### 4. The rest of the file

| Key | Default | Effect |
| --- | --- | --- |
| `runner.workspace_root` | `~/workspace` | where to look for repositories |
| `runner.max_concurrent` | `2` | tickets handled side by side in one run |
| `runner.timeout_minutes` | `30` | past this, the session is killed and the ticket fails |
| `runner.model` | `""` | `"opus"`, `"sonnet"`… empty = the CLI's default |
| `runner.permission_mode` | `"bypassPermissions"` | see *What protects your code* below |
| `runner.branch_prefix` | `"ticket/"` | prefix of the created branches |
| `runner.base_branch` | `""` | empty = each repository's default branch |
| `runner.push` | `true` | `false`: commits stay local |
| `runner.open_pull_request` | `true` | `false`: the branch is pushed, without a PR |
| `runner.keep_worktree_on_failure` | `true` | keep enough around to understand a failure |
| `runner.prompt_file` | `""` | your own prompt template |
| `[notion.properties]` | | if your columns have other names |
| `[notion.status]` | | if your statuses have other names |
| `[projects]` | | `"Notion name" = "/path"` for repositories that cannot be guessed |

---

## The Notion side

### The tickets database

| Property | Type | Role |
| --- | --- | --- |
| `Name` | title | what the agent must do, in one line |
| `Status` | status | **what drives the whole system** — see below |
| `Project` | relation | to the projects database: decides the repository |
| `Agent` | text | filled by the runner: who took the ticket |
| `Pull Request` | URL | filled by the runner at the end |
| `Session` | text | the session ID, written as soon as the ticket is claimed |

The **body** of the ticket page is sent to the agent as the description. Write there what
you would tell a developer who does not know the subject: what must change, where, and
how you will know it is done.

### Following the work

`Session` is filled **when the ticket is claimed**, not when it finishes — so a ticket
sitting in *In progress* is exactly the one you can look into:

```sh
claude --resume <session id>          # reopen the conversation, read it, carry on
ticket-runner logs -f                 # the live feed of the running session
ticket-runner logs <ticket id>        # a past session, rendered
ticket-runner logs <ticket id> --raw  # the raw JSON stream
```

`claude --resume` works from any directory, and keeps working after the worktree is gone:
the transcript lives in `~/.claude/projects/`, not in the checkout. While a session runs,
its worktree is also a normal repository — `git -C ~/.local/state/ticket-runner/worktrees/<name> diff`
shows you what it has changed so far.

The runner also posts a comment on the ticket when it finishes, carrying the summary, the
branch, the pull request and the resume command. That one needs a capability the
integration does not get by default: **notion.so/my-integrations → your integration →
Capabilities → Insert comments**. Without it the run still succeeds, and the log says the
comment was refused with a 403.

### The projects database

One row per project. The runner needs to locate the repository on disk, and tries in this
order:

1. a `[projects]` entry in your configuration — `"Trader Ia" = "~/workspace/labo/trader-ia"`;
2. the project's **`github`** property, matched against the `origin` remotes of every
   repository found under `workspace_root`;
3. failing that, a directory named after the repository.

`ticket-runner projects` shows you the outcome for every referenced project — worth
running once after installation; it is what saves you from surprises.

### The statuses

This is where your control over the system lives. The names are yours — map them under
`[notion.status]`, and `ticket-runner doctor` checks each one actually exists on the
board, because a status the database does not offer would only fail at the very end of a
ticket.

Out of the box the runner uses the four a plain Notion status property gives you:

| Key | Default | What it means |
| --- | --- | --- |
| `ready` | **Not started** | the description is precise enough for an agent to handle it alone. **The only gesture that triggers work.** |
| `running` | **In progress** | claimed by the runner. Stops the next run from taking it again. |
| `done` | **Done** | branch pushed, pull request opened. Yours to review. |
| `failed` | **Draft** | something broke: the session, the push, the worktree. |
| `blocked` | *follows `failed`* | the agent would not guess and asked a question instead — or its project could not be located. |

Add two statuses to your board and the picture gets a lot clearer:

```toml
[notion.status]
done = "Need Review"     # a pull request is waiting for you
failed = "Blocked"       # something went wrong, the comment says what
blocked = "Blocked"      # the agent asked a question
```

*Done* then means what you decide it means — merged, accepted — and *Draft* goes back to
its real job: a ticket not yet ready to be handed over.

Nothing is ever merged automatically.

---

## Usage

```sh
ticket-runner list         # the ready tickets, and their project
ticket-runner run          # one run, right now
ticket-runner run --dry-run          # what it would do, touching nothing
ticket-runner run --ticket <url>     # that one ticket, whatever its status
ticket-runner logs -f      # follow the running session
ticket-runner status       # timer, current run, recent tickets
ticket-runner history      # what has been handled, with the pull requests
ticket-runner projects     # Notion project → local repository mapping
ticket-runner doctor       # full diagnostics
ticket-runner clean --force          # remove worktrees left behind by failures
ticket-runner disable      # stop the timer (enable to start it again)
```

The first attempt is best made by hand, on a ticket you choose:

```sh
ticket-runner run --ticket https://www.notion.so/... --dry-run   # look first
ticket-runner run --ticket https://www.notion.so/...             # then go
```

---

## What protects your code

An agent working with nobody there to stop it needs a frame. Five guardrails, all of them
on the program's normal path:

- **The main repository is never touched.** Every ticket gets a disposable `git worktree`
  on its own branch. Your working copy, your uncommitted files and your current branch
  stay exactly as you left them — and two tickets on the same project can move at once.
- **The agent commits, the runner publishes.** Pushing a branch and opening a PR are
  outward-facing gestures: they happen afterwards, once it is established that there are
  commits at all. A session that declares itself done without committing anything is
  treated as a failure.
- **An ambiguous ticket is not guessed.** The prompt explicitly asks the agent to answer
  `RESULT: blocked` and stop rather than decide in your place. The ticket goes to the
  `blocked` status with the question in a comment.
- **A failing ticket takes only itself down.** The others in the same run carry on. Its
  worktree is kept for the post-mortem, and the session ID reopens the conversation
  exactly where it stopped: `claude --resume <id>`.
- **Two runs never overlap.** A file lock means a run that outlasts the timer's interval
  is not lapped by the next one.

One thing to know: by default the runner starts the session with
`permission_mode = "bypassPermissions"`, because a session with nobody to ask cannot ask,
and would stall on the first test it needs to run. The isolation comes from the worktree,
not from the permission model. If you would rather have it the other way round,
`"acceptEdits"` forbids unapproved shell commands — at the cost of sessions that stop
often.

---

## When it does not work

| Symptom | Most likely cause |
| --- | --- |
| `object not found` on the database | the database is not shared with the integration (`···` → Connections) |
| “project not found on disk” | add `"Notion name" = "/path"` under `[projects]` |
| the timer does not fire with no session open | `sudo loginctl enable-linger $USER` |
| branch pushed, no pull request | `gh` cannot reach its credentials from a systemd service — locked keyring. Use `gh auth login` with a token, or set `GH_TOKEN` in the unit |
| `claude: command not found` in the journal | the PATH baked into the unit predates a node version change: run `install.sh` again |

Session logs are in `~/.local/state/ticket-runner/logs/` (one `.jsonl` per ticket, the raw
session stream), the history in `history.jsonl`, and the timer's own journal in
`journalctl --user -u ticket-runner -f`.

---

## Uninstall

```sh
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/uninstall.sh | sh
```

`TR_PURGE=1` also removes the configuration, the logs and the history. Branches already
pushed are never touched.

---

## Licence

MIT.
