# ticket-runner

**Your Notion tickets, played by Claude Code.** You write a ticket, you move it to
*Not started*, and a few minutes later the work is waiting for you.

Not only the tickets about code. *"Remove that header"* comes back as a pull request on
its own branch; *"draft me a post about the new release"* comes back written into the
ticket page itself. Both live on the same board, and it is the ticket that decides which
one you get — not a setting.

The runner lives on your machine, in the background, across **all of your projects at
once**. It never touches your working copy: every ticket gets a disposable git worktree of
its own.

```
Notion                    ticket-runner                       what you get
──────                    ─────────────                       ────────────

Not started   ──────▶     claims it, writes the session link
                          │
In progress   ◀───────────┤
                          │
                          ├─ has a repository ──▶  worktree, branch, commits
                          │                        push + gh pr create      ──▶  a pull request
                          │
                          └─ has none ──────────▶  scratch dir, ANSWER.md
                                                   published as Notion blocks ──▶  the page itself
Need Review   ◀───────────
```

Which of the two you get is decided by the project, not by a setting: a project that names
a repository produces code, a project that names none — or a ticket with no project at all
— produces a document.

---

## Installation

```sh
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/install.sh | sh
```

The script checks the dependencies, installs the `ticket-runner` command into
`~/.local/bin`, asks for your Notion token, and arms a systemd timer that picks up ready
tickets **every 30 minutes** — `interval_seconds` in the configuration changes that, down
to a few seconds if you want a ticket picked up as soon as you move it. Then:

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
| `TR_INTERVAL=10` | seconds between two runs (default: 1800, i.e. 30 min) |
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

### 2. Give the token and the workspace to the runner

Two lines to fill in, and only two:

```toml
[notion]
token = "ntn_your_real_token_here"

# The URL of your workspace database is enough — the ID is extracted from it.
workspace = "https://www.notion.so/workspace/3a8451680af480918afcf0eb9cf70e7b"
```

A **workspace** here is one database whose rows are your master pages, each holding its
own inline database:

```
Master workspace          ← the one URL you configure
├── Master Tickets        ← the tickets database lives inside this page
├── Master project        ← the projects database lives inside this one
└── Soul                  ← a plain page: who you are
```

You name the directory once; the runner finds the rest by the **title of a row**. Rename
a row and tell the runner what it is now called, under `[notion.pages]`:

```toml
[notion.pages]
tickets = "Master Tickets"   # required
projects = "Master project"  # optional — only `doctor` uses it
context = "Soul"             # optional — see below
```

If you would rather point at one database than share a whole workspace, `tickets_database`
still works exactly as before, and wins over the workspace when both are set. The URL of
the database is enough, and if it is inline inside a page, the page URL works too: the
runner looks inside and finds the database on its own.

Three ways to get them in, whichever you prefer:

```sh
ticket-runner config      # opens the TOML in your editor — the cleanest

# or let the installer ask you (it does, on a fresh install):
curl -LsSf https://raw.githubusercontent.com/SalvadorCardona/ticket-runner/main/install.sh | sh

# or in one line:
sed -i 's|^token = .*|token = "ntn_…"|' ~/.config/ticket-runner/config.toml
```

### 3. Share the databases with the integration — the step everyone forgets

A valid token on a page that was never shared answers `object not found`, and nothing
about it hints at why. Share **the page holding your workspace database**: the `···` menu,
top right → **Connections** → your integration. Everything underneath becomes readable in
one gesture — which is the main reason to point the runner at a workspace rather than at
each database in turn.

> **What you share is what the runner can read.** Anything under that page reaches the
> prompts it writes, and prompts are kept on disk in `~/.local/state/ticket-runner/`. Keep
> credentials out of the workspace — a page of environment variables is exactly the kind
> of thing that should live in a password manager instead.

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
| `runner.interval_seconds` | `1800` | seconds between two passes — `ticket-runner enable` applies a change |
| `runner.max_concurrent` | `2` | tickets handled side by side in one run |
| `runner.timeout_minutes` | `30` | past this, the session is killed and the ticket fails |
| `runner.model` | `""` | `"opus"`, `"sonnet"`… empty = the CLI's default |
| `runner.permission_mode` | `"bypassPermissions"` | see *What protects your code* below |
| `runner.branch_prefix` | `"ticket/"` | prefix of the created branches |
| `runner.base_branch` | `""` | empty = each repository's default branch |
| `runner.push` | `true` | `false`: commits stay local |
| `runner.open_pull_request` | `true` | `false`: the branch is pushed, without a PR |
| `runner.keep_worktree_on_failure` | `true` | keep enough around to understand a failure |
| `runner.notify` | `true` | one desktop notification per finished ticket |
| `runner.log_retention_days` | `14` | drop older session logs; `0` keeps everything |
| `runner.attach_sessions` | `true` | file each session under its project, so `claude --resume` there lists it |
| `runner.prompt_file` | `""` | your own prompt template, for repository tickets |
| `runner.document_prompt_file` | `""` | the same, for tickets with no repository |
| `notion.workspace` | `""` | the database whose rows are your master pages |
| `notion.tickets_database` | `""` | one database instead of a workspace; wins when both are set |
| `[notion.pages]` | | which row of the workspace is the tickets database, the projects database, the context page |
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
| `Project` | relation | *optional* — to the projects database: decides the repository |
| `Agent` | text | filled by the runner: who took the ticket |
| `Pull Request` | URL | filled by the runner at the end |
| `Session` | **URL** or text | written as soon as the ticket is claimed. Make it a URL and it becomes a link that opens the session; leave it text and it holds the bare ID |
| `Priority` | select | *optional* — `Urgent`, `High`, `Normal`, `Low`. Decides which ready ticket runs first |
| `Model` | select | *optional* — `opus`, `sonnet`, `haiku`. This ticket's model, over `runner.model` |
| `Cost` | number | *optional* — written back, in dollars |
| `Duration` | number | *optional* — written back, in minutes |
| `Due Date` | date | *optional* — **hold the ticket until that moment**, then run it |

`Due Date` is what turns the board into a calendar. A ticket without one starts within
seconds of reaching the ready column, so a date on it can only mean *not yet*: the runner
leaves it alone until the moment comes, then treats it like any other. Write the release
post on Monday, run the monthly report on the first — the ticket sits ready and waits.

A bare date means the start of that day in the runner's own timezone, so a ticket dated
30 August begins on the 30th rather than at some hour dictated by UTC. A date with a time
is taken as written, offset included. A range starts at its end — the moment the thing is
due. And a value the runner cannot read never holds a ticket back: a ticket is not frozen
by a date that failed to parse.

Precision is to the minute, and that limit is Notion's rather than the runner's: it stores
`14:48:27` as `14:48`. With a ten-second cadence a ticket therefore starts within a few
seconds of the minute you named, which is as close as the board can express.

The last five are optional in the strict sense: a database without them behaves exactly as
before, because the runner only ever writes properties the schema declares. Add them and
you get a queue you can steer — a cheap model for a documentation ticket, an expensive one
for a refactor — and a board that shows what each ticket cost.

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

**Make `Session` a URL property and its cell becomes a button.** Clicking it opens a
terminal already inside that conversation — no identifier to copy, no directory to find.
`install.sh` registers a `ticket-runner://` scheme with your desktop for exactly this, and
`ticket-runner open <link>` is what runs behind the click. Which of the two you get is
decided by the column's type in Notion, nothing to configure: a URL column gets the link,
a text column gets the identifier.

The terminal is picked from the usual suspects — GNOME Terminal, Konsole, xfce4-terminal,
kitty, Alacritty, foot — or set `TICKET_RUNNER_TERMINAL` to yours.

Every ticket is a **real Claude Code session** — not a private log format, the same
transcript your own sessions produce. `claude --resume` works from any directory, and
keeps working after the worktree is gone: the transcript lives in `~/.claude/projects/`,
not in the checkout.

By default they also **show up in the project's session picker**. A session started
inside a disposable worktree would otherwise be filed under that worktree, so opening
`claude` in the repository would never list it; when a ticket finishes, the runner moves
its transcript under the repository's own directory instead. Open `claude` in the repo,
pick the session, and you are inside the conversation that produced the pull request.
Tickets with no repository are filed under `workspace_root`. Set
`attach_sessions = false` to leave them where they ran.

This one reaches into Claude Code's own storage layout, so it is written to fail quietly:
if the layout ever changes, the move is skipped and the session stays resumable by its
identifier, exactly as before.

While a session runs, its worktree is also a normal repository —
`git -C ~/.local/state/ticket-runner/worktrees/<name> diff` shows you what it has changed
so far.

The runner also posts a comment on the ticket when it finishes, carrying the summary, the
branch, the pull request and the resume command. That one needs a capability the
integration does not get by default: **notion.so/my-integrations → your integration →
Capabilities → Insert comments**. Without it the run still succeeds, and the log says the
comment was refused with a 403.

### The projects database

One row per project, and **the project decides what kind of work its tickets are.**

A project that names a repository is a **code project**. Its tickets get a git worktree, a
branch, commits and a pull request. Three ways to name it, most explicit first:

1. a `[projects]` entry in your configuration — `"Trader Ia" = "~/workspace/labo/trader-ia"`;
2. a **`path` property on the project page**, which keeps the mapping on the board rather
   than in a file on one machine;
3. a **`github` property**, matched against the `origin` remotes of every repository found
   under `workspace_root`.

A project that names none — and **a ticket with no project at all** — is **document work**.
It gets a disposable scratch directory instead of a worktree, and the agent's answer is
written back into the Notion ticket as real blocks: headings, lists, checkboxes, links.
No branch, no pull request. That is what you want for *"draft me the steps to become a
certified trainer"* or *"summarise this for me"*: there is nothing to commit, and the
deliverable is the page itself.

**Whatever you write on the project page becomes standing instructions** for every
ticket of that project. Not the ticket's page — the *project's*. It is prepended to the
brief the agent receives, so it is written once instead of retyped into every ticket:

> **Communication**
> Tone: first person, short sentences, no superlatives. No emoji, no hashtags. Show a
> verifiable number, not a promise. If the tool has a limit, say it.
> X: 280 characters for a single post. Always offer two or three angles.

That is what turns *"write me a post about the new tool"* into your voice rather than a
generic one — and, on a code project, what carries conventions that do not belong in any
single ticket. An empty project page costs nothing and changes nothing.

The runner never guesses from a project's name. A name that happens to match a folder is
a coincidence, and turning a writing task into commits on a like-named repository is a
worse outcome than asking you to be explicit. But a repository that *is* named and does
not exist is an error, and blocks the ticket rather than silently falling back.

`ticket-runner projects` shows you which is which for every referenced project — worth
running once after installation; it is what saves you from surprises.

### The context page — who the work is for

One row of the workspace, named `Soul` by default, is a plain page with no database in it.
Whatever you write there goes into **every prompt, on every project**, ahead of the
project's brief:

```
the context page   who you are, what you work with, how you like things written
      ↓
the project page   the conventions of THIS project
      ↓
the ticket         the task
```

From the widest frame to the narrowest, so the specific is read last and wins when the two
disagree. What belongs there:

> Je suis Salvador Cardona, développeur web depuis 13 ans. Je travaille sur Animalink.
> Stack: PHP/Symfony, React, Docker. `pnpm`, jamais `npm`.
> Réponses courtes, pas d'emoji, la commande plutôt que l'explication.

It pays for itself mostly on **document tickets**: there the agent starts in an empty
directory and knows nothing about you at all, whereas on a code ticket the repository and
its `CLAUDE.md` already answer most of it.

Two things to keep in mind. **Keep it to one screen** — it is the one text billed on 100 %
of your tickets, and a long preamble dilutes the ticket itself. And what belongs to a
single project belongs on that project's page, not here: the test is whether it would
change the answer on a ticket of *any* project.

The page is optional. Without it the runner behaves exactly as before, and says so once
per run rather than leaving you to wonder.

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
ticket-runner clean --force          # remove worktrees and scratch dirs left by failures
ticket-runner enable       # apply interval_seconds and start the timer
ticket-runner disable      # stop the timer
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
- **A ticket is never stuck for good.** Because a run holds that lock, any ticket still
  marked *in progress* at the start of a run was abandoned — by a reboot, a
  `systemctl stop`, a crash. It goes back in the queue with a comment saying so, instead
  of sitting claimed forever. Tickets claimed by another machine are left alone.

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
| `object not found` on the database | the page is not shared with the integration (`···` → Connections). Sharing the page that holds the workspace covers everything under it |
| “no page named … in the workspace” | the row is called something else. `doctor` lists what it did find — rename the row, or set `[notion.pages]` |
| the agent knows nothing about you | no `Soul` row in the workspace, or the page is empty. `doctor` says which, and the run says so once |
| “project not found on disk” | the project names a repository that is not there: fix its `path` or `github` property, or add `"Notion name" = "/path"` under `[projects]` |
| a ticket became a document when you wanted code | its project names no repository. Give the project page a `path` or a `github` |
| “nothing to work from” | the ticket has neither a title nor a description — a page left on the bare template counts as empty |
| a ticket sat in *In progress* forever | it no longer can: the next run puts back any ticket this host claimed while no run was alive |
| no desktop notification | `notify-send` is missing, or the service has no session bus. `runner.notify = false` silences the attempt |
| the timer does not fire with no session open | `sudo loginctl enable-linger $USER` |
| branch pushed, no pull request | `gh` cannot reach its credentials from a systemd service — locked keyring. Use `gh auth login` with a token, or set `GH_TOKEN` in the unit |
| `claude: command not found` in the journal | the PATH baked into the unit predates a node version change: run `install.sh` again |

Session logs are in `~/.local/state/ticket-runner/logs/` (one `.jsonl` per ticket, the raw
session stream), the history in `history.jsonl`, and the timer's own journal in
`journalctl --user -u ticket-runner -f`.

---

## On a server

The runner is at its best where it never sleeps. Nothing about it assumes a desktop, but
five things change when it moves off your laptop.

**Claude Code needs its own credentials there.** This is the real prerequisite, and it is
worth settling before anything else: a headless machine has no browser to log in with.
Authenticate once, or provide `ANTHROPIC_API_KEY` — which bills per token rather than
against a subscription, and changes the economics of a ten-second cadence considerably.

**`gh` has no keyring.** Password-store lookups fail silently in a systemd service and you
get pushed branches with no pull request. Put a token in the unit instead:

```ini
# ~/.config/systemd/user/ticket-runner.service
Environment=GH_TOKEN=ghp_…
```

Scope it to the repositories the runner may touch, and nothing else.

**Paths differ from your laptop.** A project's `path` property in Notion names one
machine's layout, and the server's is not the same. That is why a `[projects]` entry in
the local configuration wins over it: each machine overrides what it needs, and the board
keeps the mapping that suits the machine you use most.

**The session link must cross the network.** A session that ran on the server left its
transcript there, so a link opening a local terminal would find nothing. Set
`session_host` to the ssh destination and the Session cell keeps working from your laptop
— the click opens the conversation over ssh:

```toml
[runner]
session_host = "salva@vps.example.com"
```

**Desktop notifications are pointless there.** They fail quietly, so nothing breaks, but
set `notify = false` to stop trying. The Notion comment on each finished ticket is the
notification that matters on a server.

And the thing to make sure of: **run one runner, not two.** Claiming a ticket is a read
then a write, not an atomic operation, so two runners watching the same board will
occasionally start the same ticket twice. If you keep a copy on your laptop, keep it
stopped (`ticket-runner disable`) and use it for `--ticket` runs on demand.

### Who can write a ticket can run commands on that machine

This deserves saying plainly rather than burying it. The runner starts sessions in
`bypassPermissions`: the worktree protects your *repository*, not the machine. Anyone who
can move a ticket to the ready column can therefore have arbitrary commands run under the
account the runner uses.

On a personal laptop where you are the only author, that is the same trust you already
give Claude Code. On a server whose board is shared — a Notion workspace with partners, a
database someone else can edit — it is a different proposition. What makes it sound:

- a **dedicated account** on the server, holding the repositories and nothing else: no
  other project's secrets, no keys that reach beyond what the runner needs;
- a **narrowly scoped `GH_TOKEN`**, so the worst case stays inside the repositories the
  runner already writes to;
- **editing rights on the tickets database limited** to the people you would let run a
  command on that machine — which is the honest way to read that permission.

Setting `permission_mode = "acceptEdits"` narrows it further, at the cost of sessions that
stall the first time one needs to run the test suite. It is the right setting for a shared
board and the wrong one for a private machine.

---

## Tests

```sh
python3 tests/run.py
```

No framework and no dependency, for the same reason the runner has none: a suite that
needs an install is a suite that stops being run. It covers the pure part — identifier
collisions, status mapping, the markdown-to-Notion conversion, deep links, property
encoding — which is to say what has already gone wrong once, or would go wrong silently.

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
