# Changelog

What changed, release by release, in words a user of the runner would use — not
in commit subjects. Every entry answers "what can I do today that I could not do
yesterday", and the ones that matter most are the ones that change a habit.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the versions follow [semantic versioning](https://semver.org/): the **minor**
number moves when the runner gains something, the **patch** number when it stops
getting something wrong, and the **major** number when an installation needs a
hand to keep working — a configuration key that changed name, a Notion property
that has to exist, a command that went away.

`Unreleased` is where work lands as it is merged. It becomes a version when
somebody cuts a release; see `.claude/skills/release/SKILL.md`.

## [Unreleased]

### Added

- **The runner waits for the credits instead of failing on them.** A Claude
  subscription is metered in windows, and a spent one used to cost a whole
  board: every ticket the runner touched came back as a failure with a log to
  read, and by the time the credits returned there was nobody left to put any of
  them back. Now a session that dies on the quota puts the ticket back where it
  was taken from — *ready* for work, *validated* for a publication, branch and
  worktree untouched — and nothing at all is started until the window rolls
  over. The wait lasts as long as Claude Code said it would, or a quarter of an
  hour when it did not say; `ticket-runner status` and the console's header both
  show how much of it is left. `runner.wait_for_credits = false` brings back the
  old behaviour, which is what an `ANTHROPIC_API_KEY` runner wants.

- `runner.language`, and the runner answers in it. `"fr"` — or `"FR"`, or
  `"fr-FR"`, or `"français"` — and every report under a ticket, every question a
  blocked one asks and every line that reaches Telegram or Slack comes back in
  French. The setting also travels into every prompt, so the summary at the top
  of a report, the document a ticket with no repository produces and the answers
  given in the comments follow it too; commit messages and code keep the
  language the repository already uses. Empty stays English *and* keeps meaning
  "nobody decided": each session goes on answering in the language of the ticket
  it was given, exactly as before.

### Changed

- The web console has been redrawn. Every page opens the same way — where you
  are, said as a path; a heading you can read from across the room; and the one
  line that says what the page is for — and the accent is a lime, so the button
  worth pressing is the only thing on the screen wearing it. A ticket's card
  says its id and its age before it says anything else, and states its project
  and its cost along the bottom; a ticket's page states its metadata as a ruled
  grid instead of a row of pills. Sessions open on the three numbers you came
  for: how many are writing, how often the timer comes round, what has been
  spent.
- Forms read as forms. Every field the console draws — its own on the settings
  tab, and the ones react-data-form builds for a new ticket — sits in a filled
  box with its label against it and its explanation under it. The settings tab
  gains a list of its sections down the left, which says what the file holds,
  which parts are open, and how many of your unsaved changes are hiding in a
  part you folded away; a field you have touched says so.
- Reports read like sentences rather than like a row of fields. What used to be
  `Branch \`x\` · 3 commit(s) · <url>` followed by three lines of session
  machinery is now “3 commits on \`x\`, and the pull request is waiting to be
  read: <url>”, a line saying what the run took and cost, and the resume command
  last — where you look on the rare day something went wrong, rather than first.
  Durations are rounded to the minute, prices to the cent.
- The web console's board is now the board: the columns your Notion board has,
  under its own names, and a card dragged into one moves the ticket. The
  *table* tab shows the same tickets as rows. A new ticket is written in a form
  over the board rather than in a strip above it.
- A card opens a page of its own — the brief, the report a run appended, the
  notes in between, read from the Notion page — with the ticket's terminal
  beside it, in place of the workspace console. The *Ticket* entry of the menu
  is gone: the page is where the card takes you, and it has an address
  (`/?view=console/tickets/read/<id>`) a reload or a link comes back to. Every
  page does — `/?page=live`, `/?page=settings`.
- The board, the ticket page and the form are one declaration for
  [react-resource-view](https://github.com/SalvadorCardona/react-resource-view)
  and [react-data-form](https://github.com/SalvadorCardona/react-data-form);
  the two transcripts are shadcn's `message` and `message-scroller`. A switch at
  the right of the header folds the second column away, for a board that wants
  the width.

### Added

- Tickets that come back on their own. A fifth database, *Schedules*, where one
  row describes a ticket and how often it is born — `Cadence` (Hourly, Daily,
  Weekly, Monthly), `At`, `Day`, and the `Active` tick that turns it on — with
  the body of its page as the brief, copied into every ticket it makes. When the
  moment comes, the runner writes the ticket into the ready column and steps
  back: same column, same queue, same session, same pull request. Monday's
  dependency review is written once instead of being retyped every Monday.
  Two rules are the whole point of it: **catching up creates one occurrence, not
  the missed ones** — a machine off for three days wakes up owing one ticket and
  not twelve — and **an occurrence still open blocks the next one**, so a
  schedule stuck on a question does not fill the board with copies of itself.
  `ticket-runner init` builds the database, on a bare page or on a board that
  predates it; `ticket-runner schedules` says what repeats and when it next
  does; `ticket-runner schedules --run "<name>"` makes its ticket on the spot;
  `ticket-runner list` now shows the whole calendar, the tickets waiting for a
  date and the ones not written yet. Optional throughout: a workspace with no
  schedules page has nothing that repeats, `doctor` is green on it, and
  `runner.schedule = false` turns everything off without a row being unticked.
- The web console shows what comes back on its own. A *Schedules* page in the
  menu — `/?page=schedules` — reads the calendar the way `ticket-runner
  schedules` reads it: what repeats, at what rhythm, when the next ticket is due
  and when the last one was made, with a way through to the ticket that
  occurrence produced. A row nobody can read says what is wrong with it rather
  than showing a date it does not have, and `runner.schedule = false` is said at
  the foot of the page — a browser was the one place that switch could not be
  seen, and a calendar of ticked rows that never fire reads as one that works.
  Nothing is written from here: a schedule is a Notion page, and its name is the
  link to it. The page asks Notion when you open it rather than living on the
  event stream, so a tab left open on the board never polls that database.
- `GET /api/tickets/<id>`: one ticket, with the page under it flattened the way
  the runner reads it before a run.
- `GET /api/schedules`: the Schedules database as the console draws it, with
  what makes each row unreadable spelled out rather than raised.
- The official `shadcn` skill, vendored under `.claude/skills/shadcn`, so a
  session working on the console composes from the same kit.

### Fixed

- A project whose `Path` points nowhere is no longer refused when the same page still
  names its repository. Rename a clone on disk and the page keeps the old path, while
  its `Repository` column stays right — the runner used to stop at the first wrong
  declaration and never read the second, blocking every ticket of that project with
  `project not found on disk`. Each way is now tried in turn, and the ticket runs on
  what the first working one finds; its comment says which declaration is out of
  date, and `ticket-runner projects` shows the project with a `!` rather than a tick
  until you correct it. A repository renamed on GitHub is found too: `gh` is asked what
  the old name is called now, and that is what the clones are matched against. What a
  fallback may find is deliberately narrow — only a clone whose `origin` remote is the
  one declared, never one whose folder is merely named like the project, and never one
  of two clones that answer to the same remote. A project none of its declarations lead
  to is still put back, and the comment now lists every way that was tried and why each
  one failed, instead of the first disappointment alone.

- A desktop notification now takes you to the ticket it names: clicking it
  opens that ticket's Notion page, where before a click did nothing and you
  had to go and find the title on the board. `notify-send` cannot do it — it
  never hands back the identifier a desktop answers a click with, and on GNOME
  it refuses `--action` outright — so a notification with a page behind it is
  posted over D-Bus and followed by a detached process, which waits for the
  click and then goes quiet. A machine missing `gdbus`, `dbus-monitor` or
  `xdg-open`, or a desktop that does not do notification actions, gets exactly
  the notification it got before.
- `ticket-runner init` can build the Tickets database on a bare page again. It
  declared the *Project* and *Agent* relations in a shape the Notion API
  rejects, so on 8 September 2026 a fresh page stopped at `POST /databases:
  400 body failed validation. Fix one:` — and said nothing after the colon,
  since only the first line of the error was shown, then claimed nothing was
  half-built when the workspace and the Projects and Agents databases already
  were. The relations are now spelled the way the API accepts; when the API
  refuses something, `init` prints every line of its answer; and the advice
  says what is true: what was built is kept, run the same command again.
- The runner no longer goes quiet after a run that failed. On 7 September 2026
  a Notion timeout failed a run, the timer was restarted, and nothing ran for
  the next two hours: the timer counted from the boot and from the service's
  last activation, had neither to count from, and sat *enabled* with no next
  run — `status` showed a green tick the whole time. The timer now also counts
  from its own start (`OnActiveSec`), so it always has a next run. `status` and
  `doctor` read that next run rather than `is-enabled`, and a timer that has
  none is a red line, not a tick; the console's badge says *stalled*. And
  `status` no longer reports a run in progress on the strength of a `run.lock`
  a dead process left behind: it asks the lock itself, which the kernel drops
  with the process. **An existing installation keeps its old unit, and the fault
  with it, until `ticket-runner enable` is run again** — which now restarts the
  timer rather than leaving an active one as it was, since a reload alone does
  not revive a starved timer.
- A ticket that has run before is picked up instead of being refused. Its branch
  is named after it, so a session that failed, or a pull request nobody merged,
  left a branch that answered `branch ticket/… already exists — ticket already
  handled?` on every pass afterwards — the ticket was stuck until somebody ran
  `ticket-runner clean --force` by hand. That branch is now checked out again,
  replayed on top of the newest base, and the session carries on from what it
  already holds: the agent is told it is continuing somebody's work, the ticket's
  comment says what was reused and what it was rebased onto, and the push that
  follows forces with a lease, since the history under it was replayed. A rebase
  that conflicts is undone rather than left half-applied — the session still runs,
  and the conflict is a line in the comment. Two things still stop the ticket, and
  both should: a branch another worktree has checked out, and a directory holding
  commits or changes that were never anywhere else.

### Added

- A date on a **validated** ticket is honoured too, so the board schedules what is
  finished and not only what is to be done: the post you wrote on Monday and accepted on
  Tuesday goes out on Thursday at 18:00, on its own, rather than on the pass that follows
  your click. The ticket waits in its column until the moment comes, and a pull request
  waits the same way — one column, one rule. `ticket-runner list` shows what *Validated*
  is holding back beside the ready tickets waiting for their date, and a pass counts them
  both.

- A ticket nobody got round to titling is named by the runner when it becomes
  ready: a very short session reads what the page says and writes a title back
  into Notion, so the board shows it too — and the branch reads
  `ticket/retirer-le-shader-…` instead of one more `untitled-ticket`. A ticket
  that already has a title keeps it and costs nothing extra, and one with
  nothing on the page still comes back with the question rather than a name
  invented for it.
- A terminal for one ticket, in the console: click a card and the **Ticket** tab

- The console is a React application. Its page is rebuilt on TypeScript, Vite,
  Tailwind and [shadcn/ui](https://ui.shadcn.com), and it has a light theme now —
  a switch in the header, dark still what it opens on. Nothing about how it is
  installed or served changed: what ships is the built bundle, committed beside
  the Python that serves it, so a machine still needs `python3` and `git` and no
  Node at all. Its source lives in `frontend/`.
- A menu down the left of the console, in place of the row of tabs — and it says
  more than the tabs could: how many tickets are ready and how many are in
  review, which ticket the Ticket pane is holding, how many sessions are writing
  right now. `Ctrl-B` folds it to a rail of icons; on a phone it is a drawer.
- The repository declares the shadcn MCP server in `.mcp.json`, so an agent
  working here can search the registry and add a component without leaving the
  session.
- A terminal for one ticket, in the console: click a card and the **Ticket** pane

  shows everything said on it — the runner's reports, your answers, the ones you
  gave from Telegram — with a field to say the next thing and, while it runs, its
  session's steps scrolling underneath. What you type is a comment on the ticket,
  written into the thread the runner last spoke in: answering its question runs
  the ticket again, and naming it asks it for words instead.
- Addresses in the console are links. An answer, the output of a command, a step
  of a session or a comment on a ticket that carries a URL is one click away,
  rather than something to read out loud into another tab.
- A ticket moved to *Ready* becomes a Claude Code session: a disposable git
  worktree, a branch, commits, and a pull request — or, for a project with no
  repository, a document written back into the Notion page itself.
- A projects database, a context page and an agents database, so a ticket knows
  which repository it belongs to, who the work is for, and who handles it.
- A discussion on a ticket: a comment under one of the runner's reports is
  answered in the thread by something that has read the ticket and the code.
- Telegram and Slack: a ticket the agent will not guess at asks its question
  where you already are, and one word answers it.
- `ticket-runner serve` — the web console: the board live, the CLI in a browser,
  and a chat with the whole workspace.
- Progress written as the session runs, at a ten-second cadence: a bullet per
  command run and per file touched, and what the agent says as a paragraph of
  its own — whole, in its own markdown, and never cut to the length of a bullet.
- Self-update: a run asks once an hour whether the installed code is still the
  newest, and updates itself between two runs.
- `ticket-runner history` shows what each ticket cost and how long it took.
- A dated ticket waits for its date.
- An architecture diagram, generated by [archify](https://github.com/tt-a1i/archify)
  from `diagrams/ticket-runner.architecture.json`: a still in the README and an
  interactive `diagrams/architecture.html` whose nodes link to the code they are
  drawn from.
- A *Validated* column: the answer to the question *In review* asks. Move a
  ticket there and the runner does the last thing it needs — it merges its pull
  request (`runner.merge_method`, `squash` by default), or, when there is none,
  runs a session that publishes what the ticket already holds: the post, the
  mail, the announcement. Then *Done*, which now means out in the world rather
  than merely finished. A run that dies mid-publication comes back as a question
  rather than redoing the work, publications of one pass run side by side, and
  `--dry-run` says what it would merge or publish without touching anything.
  Optional: a board without the column behaves exactly as before, and
  `ticket-runner init` adds it.
- A **Settings** tab in the web console: `config.toml` drawn as a page, every
  key of it, written back into that very file one line at a time — the comments
  around it survive, and the console picks the change up without a restart. A
  blank field says nothing and shows the default it falls back on; tokens are
  never sent to the browser, only *set, ending in …f3a2*; and a save is all of
  it or none of it, on a copy that has to load before it takes the file's place.
- A release and versioning system: this changelog, `scripts/release.py`, the
  `release` workflow, and the `/release` command Claude uses to cut one.
- `ticket-runner`, typed alone, presents itself: the product, the version it is
  running, an update waiting if there is one, and the commands — rather than an
  argparse usage block. The web console prints the same version beside its name
  in the header, so a browser tab left open says which runner it is talking to.

### Changed

- **The web console starts on its own.** Its unit was installed and left
  stopped, so the board only existed for as long as you remembered to type
  `ticket-runner serve` in a terminal you then had to leave open. It is now
  armed with the timer — by `install.sh` on a new machine, by `ticket-runner
  enable` on one that already has the runner — so `http://127.0.0.1:8787` is up
  after a boot with nothing to type, and the installer prints the address with
  the token in it rather than leaving it in a state file. What it opens is
  loopback and nothing else, which is what makes it a reasonable default;
  widening `web.host` is still the decision it always was. `TR_NO_WEB=1 sh
  install.sh` installs the unit and leaves it stopped, `ticket-runner disable`
  stops both — from a terminal, the console's own command line refusing the one
  command that would cut it off mid-answer — and `ticket-runner serve` on a
  machine where the console is already listening says where it is instead of
  failing on the port.
- The console's scroll bars are the console's own: thin, rounded, the colour of
  its panels, and only really visible under the pointer. The browser's — pale,
  wide, and drawn for a white page — turned up in every part of the console
  that scrolls, which is nearly all of it: the board, the transcript, a
  session's steps, the settings. The dropdowns and the caret follow the same
  dark now.

### Fixed

- `ticket-runner clean --force` removes the branch of every worktree it
  removes. A branch is named after its ticket, so a failed session left one
  behind that made every later attempt answer `branch ticket/… already exists`:
  the ticket was stuck for good, and `clean` — which only ever removed the
  directory — did not help. It does now, and it stops where something would be
  lost: a branch with commits of its own, one whose pull request is still open,
  or a worktree with uncommitted changes is kept, named in the output with the
  reason and with the command that drops it once you have looked.
