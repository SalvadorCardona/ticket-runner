# ticket-runner

**Your Notion tickets, played by Claude Code.** You write a ticket, you move it to
*Ready*, and a few minutes later the work is waiting for you.

Not only the tickets about code. *"Remove that header"* comes back as a pull request on
its own branch; *"draft me a post about the new release"* comes back written into the
ticket page itself. Both live on the same board, and it is the ticket that decides which
one you get — not a setting.

The runner lives on your machine, in the background, across **all of your projects at
once**. It never touches your working copy: every ticket gets a disposable git worktree of
its own.

And when you would rather have your hands on it than wait for a board to refresh,
`ticket-runner serve` opens a console on `127.0.0.1`: the same board live, this CLI in a
browser, and a chat with your whole workspace. See [The web console](#the-web-console).

```
Notion                    ticket-runner                       what you get
──────                    ─────────────                       ────────────

Ready         ──────▶     claims it, writes the session link
                          │
In progress   ◀───────────┤
                          │
                          ├─ has a repository ──▶  worktree, branch, commits
                          │                        push + gh pr create      ──▶  a pull request
                          │
                          └─ has none ──────────▶  scratch dir, ANSWER.md
                                                   published as Notion blocks ──▶  the page itself
In review     ◀───────────  a pull request is waiting for you
Done          ◀───────────  once you merge it — or straight away, for a document
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

You will rarely need to. The installer clones the repository into
`~/.local/share/ticket-runner/app`, which is what lets the runner answer *"am I still on
the latest version"* with one `git fetch`. A run looks at the clock before it looks at the
tickets: **once an hour** it asks, and if the answer is no it updates itself — the
launcher and the systemd units included — before claiming a single ticket. The change
therefore lands between two sessions, never inside one, and the new code takes over on the
next pass.

```sh
ticket-runner update --check   # what is available, changing nothing
ticket-runner update           # apply it now
```

`runner.auto_update = false` turns the automatic half off; `runner.update_interval_seconds`
changes the hour. An installation made from a local copy (`TR_SRC=.`) has no remote to
compare itself against: it says so once per check and carries on.

> **Requirements** — Linux with systemd in the user session, `python3` >= 3.11 (no
> dependencies to install, everything is in the standard library), `git`,
> [Claude Code](https://claude.com/claude-code), and `gh` authenticated for pull requests.

| Variable | Effect |
| --- | --- |
| `TR_INTERVAL=10` | seconds between two runs (default: 1800, i.e. 30 min) |
| `TR_NO_SERVICE=1` | no timer: you run `ticket-runner run` yourself |
| `TR_SRC=.` | install from a local clone, without the network — and without self-updating |
| `TR_REF=v1.2` | install a tag instead of `main`, and stay on it |

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

### 2. Share one page with it

Open any Notion page — an empty one will do — and share it: the `···` menu, top right →
**Connections** → your integration. That click is the floor: an integration cannot grant
itself access, so it is the one step no command can take for you.

### 3. Let the runner build the rest

```sh
ticket-runner init https://www.notion.so/your-page --token ntn_…
```

It creates everything under that page and writes the result into your configuration:

```
your page                 ← the one you shared
└── ticket-runner         ← the workspace: its rows are the master pages
    ├── Tickets           ← the tickets database, 12 columns, 2 relations
    ├── Projects          ← Name, Repository, Path
    ├── Agents            ← the roles a ticket can be handled by
    └── Context           ← a plain page: who you are
```

Plus a demonstration ticket, left unstarted, so the first thing you do is move something
to *Ready* and watch it work.

**Running it again is safe** — and is how you upgrade. Nothing is duplicated: what exists
is kept, what a previous version did not know how to create is added, and a column you
retyped on purpose is never overruled.

> One Notion quirk shows through: the API cannot create a `status` property, so `Status`
> is made a **select** with the same five options. The runner reads either — it looks at
> the declared type and writes accordingly — so this changes nothing but the icon.

You name the directory once; the runner finds the rest by the **title of a row**. Rename
a row and tell the runner what it is now called, under `[notion.pages]`:

```toml
[notion.pages]
tickets = "Tickets"     # required
projects = "Projects"   # optional — only `doctor` uses it
agents = "Agents"       # optional — see below
context = "Context"     # optional — see below
```

Rows created under the names this shipped with before — `Master Tickets`, `Soul` — are
still found as long as this table does not name them otherwise. There is nothing to
rename on an existing board.

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

### The step everyone forgets

A valid token on a page that was never shared answers `object not found`, and nothing
about it hints at why — which is why step 2 is the sharing. Everything created underneath
inherits that access in one gesture, and that is also what makes the relations legal: a
relation can only point at a database the same integration can reach.

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
| `runner.auto_update` | `true` | a run keeps the installation on the latest version |
| `runner.update_interval_seconds` | `3600` | how often a run asks; one minute is the floor |
| `runner.log_retention_days` | `14` | drop older session logs; `0` keeps everything |
| `runner.attach_sessions` | `true` | file each session under its project, so `claude --resume` there lists it |
| `runner.prompt_file` | `""` | your own prompt template, for repository tickets |
| `runner.document_prompt_file` | `""` | the same, for tickets with no repository |
| `notion.workspace` | `""` | the database whose rows are your master pages |
| `notion.tickets_database` | `""` | one database instead of a workspace; wins when both are set |
| `[notion.pages]` | | which row of the workspace is the tickets database, the projects database, the agents database, the context page |
| `[notion.properties]` | | if your columns have other names |
| `[notion.status]` | | if your statuses have other names |
| `[projects]` | | `"Notion name" = "/path"` for repositories that cannot be guessed |
| `[web]` | | the console's host, port and token — see *The web console* |

---

## The Notion side

### The tickets database

| Property | Type | Role |
| --- | --- | --- |
| `Name` | title | what the agent must do, in one line |
| `Status` | status *or* select | **what drives the whole system** — see below |
| `Project` | relation | *optional* — to the projects database: decides the repository |
| `Agent` | relation | *optional* — to the agents database: decides who handles it |
| `Runner` | text | filled by the runner: which machine took the ticket |
| `Pull Request` | URL | filled by the runner at the end |
| `Session` | **URL** or text | written as soon as the ticket is claimed. Make it a URL and it becomes a link that opens the session; leave it text and it holds the bare ID |
| `Priority` | select | *optional* — `Urgent`, `High`, `Normal`, `Low`. Decides which ready ticket runs first |
| `Model` | select | *optional* — `opus`, `sonnet`, `haiku`. This ticket's model, over its agent's and over `runner.model` |
| `Cost` | number | *optional* — written back, in dollars |
| `Duration` | number | *optional* — written back, in minutes |
| `Progress` | text | *optional* — **what the session is doing right now**, rewritten every ten seconds |
| `Scheduled` | date | *optional* — **hold the ticket until that moment**, then run it |

`Scheduled` is what turns the board into a calendar. A ticket without one starts within
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

The last six are optional in the strict sense: a database without them behaves exactly as
before, because the runner only ever writes properties the schema declares. Add them and
you get a queue you can steer — a cheap model for a documentation ticket, an expensive one
for a refactor — and a board that shows what each ticket cost.

The **body** of the ticket page is sent to the agent as the description. Write there what
you would tell a developer who does not know the subject: what must change, where, and
how you will know it is done.

### Following the work

#### Live, on the ticket itself

A run used to say nothing between *In progress* and the pull request. Now it narrates:
while the session works, its steps are written **into the ticket**, on a ten-second
cadence.

Two places, and they answer two different questions.

- **The page** gets one toggle per run — `⏳ Live — 12 step(s) · 3 min` — and a line under
  it per file read, per command run, per sentence the agent says. Open it to watch the
  work; leave it collapsed and its title alone tells you the session is moving. When the
  run ends the toggle settles into `✓ 27 step(s) · 6 min · removed the header`, and stays
  as the story of what happened.
- **The `Progress` column** carries the last line, so a glance at the board — from a
  phone, without opening anything — shows which ticket is on `Bash · npm test` and which
  is still reading. It is cleared when the run ends: the comment, the status and the pull
  request speak from then on.

```
⏳ Live — 12 step(s) · 3 min
   Read    src/app/header.component.html
   I will remove the banner and its stylesheet rules.
   Edit    src/app/header.component.html
   Bash    npm test -- --watch=false
```

A **cadence, not a stream**: a session emits several events a second, and writing each one
would rewrite the page continuously, spend the integration's rate limit and produce
something nobody can read. Ten seconds is the default, five the floor:

```toml
[runner]
progress = true
progress_interval_seconds = 10
```

What reaches the ticket is a line per step — `Bash · npm test`, never the eight hundred
lines it printed. Long sessions stop at three hundred steps, with a line saying so: a
ticket page is not a log file. And a board with no `Progress` column, or an integration
that refuses the write, costs the report and nothing else — the ticket runs to its end
either way.

`ticket-runner init` adds the column to an existing board; the toggles need nothing.

#### From the terminal

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
2. a **`Path` property on the project page**, which keeps the mapping on the board rather
   than in a file on one machine;
3. a **`Repository` property** — a GitHub URL or `owner/name` — matched against the
   `origin` remotes of every repository found under `workspace_root`.

Both columns are read by name, whatever their capitalisation, and the `github` column
earlier versions asked for still works.

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

One row of the workspace, named `Context` by default, is a plain page with no database in it.
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

### The agents database — who handles the ticket

A project says *where* the work happens. It says nothing about **who** does it, and
“fix this regression” and “write this announcement” are not the same craft on the same
repository.

Add an `Agent` relation column on your tickets, pointing at a database of agents. One row
per role, and **the body of its page is the role**, exactly as a project page is its brief:

> **Dev front**
> Tu touches au CSS avant le JS. Aucune dépendance nouvelle sans raison écrite.
> Un test qui reproduit le bug avant le correctif.

An agent row may also carry a `Model`, which is how a rewriting ticket runs on a cheaper
model than a refactor. The narrowest choice wins:

```
the ticket's Model  →  its agent's Model  →  runner.model
```

The role is read after your context page and after the project's brief, and **it can never
loosen the frame**: committing without pushing, and answering `RESULT: blocked` rather than
guessing, live in the template, above anything a page can say.

All of it is optional twice over: a tickets database with no `Agent` column behaves exactly
as it always has, and a ticket that names no agent runs on the runner's own prompt.

### The discussion on a ticket

The comments of a ticket go into the prompt, oldest first, which closes the loop the
`blocked` status opens: a run asks a question, you answer it in a comment — and the next
run reads your answer instead of asking again.

**Answering is the whole gesture.** The reply itself puts the ticket back in the queue:
nothing to move on the board, the runner claims it and it goes to *in progress* for as
long as the new run lasts. Which is narrow on purpose, because not every comment is an
instruction:

- only tickets **the runner has already reported on** wake up. A comment on a ticket no
  run of ours ever touched is a conversation of yours, and one handled by another machine
  is that machine's to pick up — a report is signed `ticket-runner@<host>`;
- only when **someone else has had the last word** since that report. The report the next
  run posts is also what closes the ticket again;
- and never a ticket that came back with its pull request. *In review* and *Done* are
  both answers already: comment on one and nothing happens — the discussion belongs to
  the pull request. A ticket already ready, or one in flight, is left where it is too.

So it is `blocked` and `failed` that come back to life, which is where a run leaves a
ticket it could not finish, and precisely where an answer is expected.

The runner's own reports are included too, trimmed to their verdict and reason; the branch
names, session IDs and log paths they carry are of no use to a session. At most the last
ten comments and 2000 characters, newest kept, so a ticket that has been round three times
does not spend more of its prompt on its own history than on the work.

This needs one capability the integration does not have by default:
[notion.so/my-integrations](https://www.notion.so/my-integrations) → your integration →
**Capabilities** → *Read comments*. Without it the runner says so once and carries on —
and no ticket ever wakes up, since it cannot see the answer.

### The statuses

This is where your control over the system lives. The names are yours — map them under
`[notion.status]`, and `ticket-runner doctor` checks each one actually exists on the
board, because a status the database does not offer would only fail at the very end of a
ticket.

`ticket-runner init` creates these six:

| Key | Default | What it means |
| --- | --- | --- |
| `ready` | **Ready** | the description is precise enough for an agent to handle it alone. **The gesture that triggers work** — the other being a comment answering a ticket already handled once. |
| `running` | **In progress** | claimed by the runner. Stops the next run from taking it again. |
| `review` | **In review** | branch pushed, pull request opened. Yours to review. |
| `done` | **Done** | that pull request has been merged — or the ticket produced a document, which has nothing to wait for. |
| `failed` | **Failed** | something broke: the session, the push, the worktree. |
| `blocked` | **Blocked** | the agent would not guess and asked a question instead — or its project could not be located. Answer in a comment and the ticket runs again. |

Three of those names are deliberate. *In review* rather than *Done*, because nothing is
done when the runner lets go of a ticket: a pull request is waiting for a human, and a
board that calls that *Done* stops being believed by the second week. *Done* is then kept
for what it says — merged. And *Blocked* is its own column rather than a shade of
*Failed*, because the runner works hard to tell them apart — a ticket waiting for **you**
and a session that crashed are different days, and pouring both into one column throws
that away.

One column for two states is still a fine board, if yours is small. Name `failed` and
leave `blocked` out, and questions land wherever failures do; name `done` and leave
`review` out, and a ticket stops at its open pull request:

```toml
[notion.status]
done = "Shipped"
failed = "Needs you"
```

### Merging is the only gesture

A ticket that came back as a pull request waits in *In review*. Every run then asks
GitHub — through `gh` — what became of those pull requests, and a ticket whose own has
been **merged** moves to *Done*, with a comment saying so. So you merge, and the board
catches up on its own; nothing else to close by hand.

The cadence is the runner's own: `interval_seconds`, not a second timer to install and
forget. A ticket whose pull request is still open, closed without merging, or unreachable
because `gh` is not authenticated simply stays in review — the next run asks again. A
board whose `review` and `done` are one column has nowhere for a ticket to wait, so
nothing is watched.

Nothing is ever merged automatically. The merge is yours; only its consequence is not.

---

## The web console

Notion is where tickets are written and read; it is a poor place to *steer* from. So there
is a second window on the same workspace, served from your own machine:

```sh
ticket-runner serve
```

It prints a URL with a token in it. Open it and you get one page, three things:

```
┌──────────────────────────────┬─────────────────────────────┐
│  Ready                    2  │  you                        │
│  ┌────────────────────────┐  │  Where is the SQLite ticket │
│  │ Retirer le bandeau     │  │                             │
│  │ Site vitrine · High    │  │  workspace                  │
│  └────────────────────────┘  │  Six minutes in, on Trader  │
│                              │  IA. It has rewritten       │
│  In progress              1  │  src/storage.py and is on    │
│  ┌────────────────────────┐  │  pytest. Nothing committed. │
│  │ Migrer vers SQLite     │  │                             │
│  │ Bash · pytest -q       │  │  > status                   │
│  └────────────────────────┘  │  timer on · 30 min          │
└──────────────────────────────┴─────────────────────────────┘
       the board, live                the console
```

**The board** is the Notion board, read from Notion and written back to it. Nothing here
is a second database: moving a card moves the ticket, and the new ticket you type at the
top is a page in the same database, with its brief as real Notion blocks. What the console
adds is the part Notion cannot do — the running session's steps, live, read straight from
the session log on disk rather than from the `Progress` column.

**The console** is one field and two gestures, and they are not made to look alike.

- A line starting with `>` is a **`ticket-runner` subcommand** — `>status`, `>list`,
  `>run`, `>doctor`, `>logs 1a2b3c4d`. The CLI is already the considered surface of this
  tool, so the console does not invent a second one; the command runs as a subprocess with
  no shell, and its output streams into the page. There is no shell in the browser, on
  purpose: it would add every risk and no capability the chat does not already have.
- Anything else is a **message to your workspace**. One long Claude Code session, started
  in `workspace_root`, carried on from turn to turn — with your repositories under its
  feet and `ticket-runner` on its PATH. *"Create a ticket for the SQLite migration on
  Trader IA and make it ready"* is a thing it does, not a thing it explains how to do.

That conversation is a real session, like every ticket's: `claude --resume <id>` in a
terminal opens the very same one, and it survives the browser, the server and the machine.
*New conversation* starts a fresh one; the old one stays resumable by its identifier.

### Keeping it running

```sh
systemctl --user enable --now ticket-runner-web    # the unit install.sh laid down
ticket-runner serve --print-token                  # the token, if you lost the URL
```

The unit is installed and left disabled: it opens a port, and that is a decision rather
than a default.

### What is behind that port

**The console is arbitrary code execution on the machine that runs it.** The chat starts
Claude Code sessions with the same `bypassPermissions` the runner uses — that is what
makes it useful, and it is the whole of the risk. So:

- it binds **`127.0.0.1`** and `serve` **refuses any other host** unless `web.token` is
  set in the configuration on purpose: a token drawn automatically is not a decision you
  took;
- every request carries that token — the `?token=` in the URL is moved into a cookie on
  the first load, so it stops sitting in your history;
- writes demand a header a cross-origin form cannot set, and the `Host` header must name
  the address the console was reached on. Between them, a hostile page you have open in
  another tab can neither post to the console nor read from it.

To reach it from your phone or another machine, **tunnel rather than widen**:

```sh
ssh -L 8787:127.0.0.1:8787 <the machine running it>
```

Then `http://127.0.0.1:8787` on the near side, over a channel that already authenticates
you. A console bound to `0.0.0.0` with a token is possible — set `web.token` and say so —
but the tunnel is the answer that does not depend on the token never leaking.

| Key | Default | Effect |
| --- | --- | --- |
| `web.host` | `127.0.0.1` | what to bind. Anything else needs `web.token` set |
| `web.port` | `8787` | |
| `web.token` | `""` | empty: drawn once into `~/.local/state/ticket-runner/web/token` |
| `web.poll_seconds` | `15` | how often the board is reread — only while a browser is connected |
| `web.chat_timeout_minutes` | `20` | past this, a chat turn is killed |

---

## Usage

```sh
ticket-runner init <url>   # build (or complete) the Notion board under a page
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
ticket-runner update       # move the installation to the newest version
ticket-runner update --check         # what is available, changing nothing
ticket-runner enable       # apply interval_seconds and start the timer
ticket-runner disable      # stop the timer
ticket-runner serve        # the web console: board, command line and chat
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
| “no page named … in the workspace” | the row is called something else. `doctor` lists what it did find — rename the row, set `[notion.pages]`, or run `ticket-runner init` to create it |
| the agent knows nothing about you | no `Context` row in the workspace, or the page is empty. `doctor` says which, and the run says so once |
| “comments not readable” | the integration lacks *Read comments* (my-integrations → Capabilities). The ticket runs, without its discussion, and answering it in a comment no longer wakes it |
| a comment on a ticket changes nothing | the ticket is *done*, or no run of this host ever reported on it — those two never wake |
| a ticket keeps running again and again | its report never gets posted, so your answer stays the last word: the integration lost *Insert comments* |
| a ticket ignores its agent | the `Agent` column is missing or is not a relation — `doctor` names it |
| “project not found on disk” | the project names a repository that is not there: fix its `Path` or `Repository` property, or add `"Notion name" = "/path"` under `[projects]` |
| a ticket became a document when you wanted code | its project names no repository. Give the project page a `Path` or a `Repository` |
| “nothing to work from” | the ticket has neither a title nor a description — a page left on the bare template counts as empty |
| a ticket sat in *In progress* forever | it no longer can: the next run puts back any ticket this host claimed while no run was alive |
| no desktop notification | `notify-send` is missing, or the service has no session bus. `runner.notify = false` silences the attempt |
| the timer does not fire with no session open | `sudo loginctl enable-linger $USER` |
| the version never moves | the install directory is a copy, not a clone: an installation older than self-updating, or one made with `TR_SRC`. `doctor` says which — run `install.sh` again |
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

**Paths differ from your laptop.** A project's `Path` property in Notion names one
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
  command on that machine — which is the honest way to read that permission. Since the
  comments of a ticket reach the prompt too, and since answering a ticket the runner has
  already handled starts a run of its own, that includes **comment-only** collaborators:
  on a shared board, they are the same permission.

Setting `permission_mode = "acceptEdits"` narrows it further, at the cost of sessions that
stall the first time one needs to run the test suite. It is the right setting for a shared
board and the wrong one for a private machine.

The same sentence covers the web console, more directly: whoever can reach that port can
run commands on that machine. On a server, leave it on loopback and reach it through the
ssh tunnel above — never on `0.0.0.0` because it happened to be easier that evening.

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
