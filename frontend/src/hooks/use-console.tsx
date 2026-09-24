import * as React from "react"
import { toast } from "sonner"

import { api, why } from "@/lib/api"
import { currentBoard, moveTicket, publishBoard } from "@/lib/board-store"
import { t } from "@/lib/i18n"
import type {
  Board,
  ChatEvent,
  ColumnKey,
  CommandEvent,
  Message,
  NoticeEvent,
  Project,
  Role,
  Running,
  RunnerState,
  SessionsEvent,
  Step,
  StepEvent,
  TalkEvent,
  Ticket,
} from "@/lib/types"
import { useStream, type Connection } from "./use-stream"

/* Everything the console knows, in three places.
 *
 * The hand-written console kept a `state` object at the top of its single file
 * and mutated it. This is the same object, held by React so that the parts of
 * the page that care about a field redraw when it changes and the rest do not.
 *
 * Three contexts rather than one, because the fields do not move at the same
 * speed. A running session writes ten steps a second; the board moves every
 * few seconds at most; whether the stream is up and which sessions are running
 * changes a few times an hour. With one context, every step redrew the menu,
 * the board, the settings and the drawer — so the steps have a context of
 * their own, the connection and the list of sessions another, and the rest a
 * third, each value built once per change rather than once per render.
 *
 * The rule underneath is unchanged and is the reason this is a stream and not a
 * store: a click posts and says nothing. What lands here is what came back on
 * `/api/events`, so two open tabs agree, and an answer typed on a phone shows up
 * on the laptop without either of them asking.
 */

/** How many steps a session's panel keeps before it starts forgetting. */
const KEPT = 200

export type Entry =
  | { id: number; kind: "turn"; role: Role; text: string }
  | { id: number; kind: "steps"; steps: Step[]; done: boolean }
  | { id: number; kind: "command"; argv: string[]; lines: string[]; code: number | null }
  | { id: number; kind: "note"; text: string }

export interface Session {
  source: string
  steps: Step[]
}

let counter = 0
const nextId = () => ++counter

/* One literal rather than two joined: it is also the key it is looked up by,
 * and a key nobody can search for is a key nobody translates. */
const WELCOME =
  "Ask me anything about your workspace — I can read your repositories, look at the board and create tickets. Type > followed by a command (>status, >list, >doctor) to use the CLI directly."

interface ConsoleValue {
  board: Board
  runner: RunnerState | null
  projects: Project[]
  transcript: Entry[]
  busy: boolean
  ticket: Ticket | null
  talk: Message[]
  mention: string
  talkLoading: boolean
  openTicket: (ticket: Ticket) => void
  closeTicket: () => void
  rereadTalk: () => void
  tell: (text: string) => Promise<void>
  submit: (text: string) => Promise<boolean>
  resetChat: () => Promise<void>
  move: (ticket: Ticket, column: ColumnKey) => Promise<void>
  createTicket: (ticket: {
    title: string
    body: string
    project: string
    ready: boolean
  }) => Promise<void>
  refresh: () => void
  runCommand: (line: string) => Promise<void>
  reloadState: () => Promise<void>
  say: (role: Role, text: string) => void
}

/** Whether the stream is up, and which sessions are running. Slow to change. */
interface StatusValue {
  connection: Connection
  running: Running[]
}

/** What the running sessions are doing. Changes with every step. */
interface StepsValue {
  sessions: Session[]
  /** The steps of the open ticket's session, if it has one this console saw. */
  ticketSteps: Step[]
}

const Context = React.createContext<ConsoleValue | null>(null)
const StatusContext = React.createContext<StatusValue | null>(null)
const StepsContext = React.createContext<StepsValue | null>(null)

export function useConsole(): ConsoleValue {
  const value = React.useContext(Context)
  if (!value) throw new Error("useConsole outside its provider")
  return value
}

export function useStatus(): StatusValue {
  const value = React.useContext(StatusContext)
  if (!value) throw new Error("useStatus outside its provider")
  return value
}

export function useSteps(): StepsValue {
  const value = React.useContext(StepsContext)
  if (!value) throw new Error("useSteps outside its provider")
  return value
}

export function ConsoleProvider({ children }: { children: React.ReactNode }) {
  const [board, setBoard] = React.useState<Board>({ tickets: [], columns: [] })
  const [runner, setRunner] = React.useState<RunnerState | null>(null)
  const [projects, setProjects] = React.useState<Project[]>([])
  const [transcript, setTranscript] = React.useState<Entry[]>([])
  const [busy, setBusy] = React.useState(false)
  const [running, setRunning] = React.useState<Running[]>([])
  const [steps, setSteps] = React.useState<Record<string, Step[]>>({})
  const [ticket, setTicket] = React.useState<Ticket | null>(null)
  const [talk, setTalk] = React.useState<Message[]>([])
  const [mention, setMention] = React.useState("")
  const [talkLoading, setTalkLoading] = React.useState(false)

  // What the stream handlers need to read without being rebuilt for it.
  const openId = React.useRef<string | null>(null)
  const openColumn = React.useRef<string>("")
  // The logs whose steps were already asked for, so a list announced twice
  // does not read the same log twice.
  const asked = React.useRef(new Set<string>())

  const say = React.useCallback((role: Role, text: string) => {
    setTranscript((entries) => [...entries, { id: nextId(), kind: "turn", role, text }])
  }, [])

  /* -- the sessions --------------------------------------------------------- */

  /* A session this page did not see start — the page was reloaded, or opened
   * mid-run — has its steps read back from its log, once, rather than
   * starting blank and filling from wherever it happened to be. */
  const catchUp = React.useCallback((sessions: Running[]) => {
    setRunning(sessions)
    for (const session of sessions) {
      if (asked.current.has(session.log)) continue
      asked.current.add(session.log)
      void api
        .log(session.log)
        .then((payload) => {
          const read = payload.steps.slice(-KEPT)
          // Steps that arrived on the stream while the log was being read are
          // in the log too: whichever says more is the one kept.
          setSteps((current) => {
            const seen = current[session.source] ?? []
            return seen.length >= read.length ? current : { ...current, [session.source]: read }
          })
        })
        .catch(() => {
          // A log that cannot be read leaves the session to fill from the
          // stream, as it did before there was anything to catch up with.
        })
    }
  }, [])

  const reloadState = React.useCallback(async () => {
    try {
      const fresh = await api.state()
      setRunner(fresh)
      if (fresh.sessions) catchUp(fresh.sessions)
    } catch {
      // The header going stale is not worth a message: the stream is still up,
      // and the next event asks again.
    }
  }, [catchUp])

  /* -- the ticket's terminal ------------------------------------------------ */

  const loadTalk = React.useCallback(async (open: Ticket) => {
    setTalkLoading(true)
    try {
      const payload = await api.talk(open.id)
      // Notion took a moment and you opened another card in it: this answer is
      // about a ticket nobody is looking at any more.
      if (openId.current !== open.id) return
      setTalk(payload.messages)
      setMention(payload.mention)
    } catch (error) {
      if (openId.current !== open.id) return
      setTalk([
        { role: "error", text: t("could not read the discussion: {{why}}", { why: why(error) }) },
      ])
    } finally {
      setTalkLoading(false)
    }
  }, [])

  const openTicket = React.useCallback(
    (open: Ticket) => {
      const another = openId.current !== open.id
      openId.current = open.id
      openColumn.current = open.column
      setTicket(open)
      if (another) {
        setTalk([])
        void loadTalk(open)
      }
    },
    [loadTalk]
  )

  const closeTicket = React.useCallback(() => {
    openId.current = null
    openColumn.current = ""
    setTicket(null)
    setTalk([])
  }, [])

  const rereadTalk = React.useCallback(() => {
    if (ticket) void loadTalk(ticket)
  }, [ticket, loadTalk])

  /* -- the stream ----------------------------------------------------------- */

  const connection = useStream({
    board: (fresh: Board) => {
      setBoard(fresh)
      // The same board, where the resource views read it from.
      publishBoard(fresh)
      // The board moved: keep the open ticket's terminal describing the right
      // one. Reread the discussion only when the ticket *changed column* — that
      // is when a run ended and left its report under it. A ticket in flight
      // redraws the board every few seconds, and asking Notion for its comments
      // each time would be polling a conversation that has not moved. The
      // "reread" button is there.
      const id = openId.current
      if (!id) return
      const moved = fresh.tickets.find((item) => item.id === id)
      if (!moved) return
      const changed = moved.column !== openColumn.current
      openColumn.current = moved.column
      setTicket(moved)
      if (changed) void loadTalk(moved)
    },

    // Which sessions are running: the server's word, not a count of the steps
    // this tab happened to see. A session that ended leaves the list here.
    sessions: (event: SessionsEvent) => catchUp(event.sessions ?? []),

    step: (event: StepEvent) => {
      const line: Step = { label: event.label, detail: event.detail }
      setSteps((current) => ({
        ...current,
        [event.source]: [...(current[event.source] ?? []), line].slice(-KEPT),
      }))
    },

    chat: (event: ChatEvent) => {
      if (event.stage === "reset") {
        setTranscript([{ id: nextId(), kind: "turn", role: "workspace", text: t(WELCOME) }])
        setBusy(false)
        return
      }
      if (event.stage === "sent") {
        setTranscript((entries) => [
          ...entries,
          { id: nextId(), kind: "turn", role: "you", text: event.text },
          { id: nextId(), kind: "steps", steps: [], done: false },
        ])
        setBusy(true)
        return
      }
      if (event.stage === "step") {
        const line: Step = { label: event.label, detail: event.detail }
        setTranscript((entries) => {
          const last = entries[entries.length - 1]
          if (last?.kind === "steps" && !last.done)
            return [...entries.slice(0, -1), { ...last, steps: [...last.steps, line] }]
          return [...entries, { id: nextId(), kind: "steps", steps: [line], done: false }]
        })
        return
      }
      // "answer" or "failed".
      const answered = event.stage === "answer" && event.ok !== false
      setTranscript((entries) => {
        const closed = entries.map((entry) =>
          entry.kind === "steps" && !entry.done ? { ...entry, done: true } : entry
        )
        const grown: Entry[] = [
          ...closed,
          { id: nextId(), kind: "turn", role: answered ? "workspace" : "error", text: event.text },
        ]
        if (event.cost_usd)
          grown.push({
            id: nextId(),
            kind: "note",
            text: `${event.seconds}s · $${event.cost_usd}`,
          })
        return grown
      })
      setBusy(false)
      void reloadState()
    },

    command: (event: CommandEvent) => {
      if (event.stage === "started") {
        setTranscript((entries) => [
          ...entries,
          { id: nextId(), kind: "command", argv: event.argv, lines: [], code: null },
        ])
        setBusy(true)
        return
      }
      setTranscript((entries) => {
        const found = entries.findLastIndex(
          (entry) => entry.kind === "command" && entry.code === null
        )
        if (found < 0) return entries
        const entry = entries[found] as Extract<Entry, { kind: "command" }>
        const kept = [...entries]
        kept[found] =
          event.stage === "line"
            ? { ...entry, lines: [...entry.lines, event.text] }
            : { ...entry, code: event.code }
        return kept
      })
      if (event.stage === "ended") {
        setBusy(false)
        void reloadState()
      }
    },

    talk: (event: TalkEvent) => {
      // Somebody wrote to a ticket — here, or in the other tab, or on a phone.
      if (event.ticket !== openId.current) return
      setTalk((messages) => [...messages, { role: event.role, text: event.text, at: event.at }])
    },

    settings: () => {
      // Another tab saved, or `ticket-runner config` did. The settings pane
      // reloads itself when it is not in the middle of an edit; the header is
      // redrawn either way.
      window.dispatchEvent(new CustomEvent("ticket-runner:settings"))
      void reloadState()
    },

    // "notice", not "error": EventSource fires an `error` event of its own for
    // every dropped connection, and a server event under the same name would
    // arrive through the same listener with nothing in it.
    notice: (event: NoticeEvent) => {
      toast.error(event.where, { description: event.message })
      say("error", `${event.where}: ${event.message}`)
    },
  })

  /* -- what a click does ---------------------------------------------------- */

  /** Says whether the line was taken, so the field is emptied only then. */
  const submit = React.useCallback(
    async (text: string) => {
      const line = text.trim()
      if (!line) return false
      try {
        if (line.trimStart().startsWith(">"))
          await api.command(line.replace(/^\s*>/, ""))
        else await api.send(line)
        return true
      } catch (error) {
        say("error", why(error))
        setBusy(false)
        return false
      }
    },
    [say]
  )

  const runCommand = React.useCallback(
    async (line: string) => {
      try {
        await api.command(line)
      } catch (error) {
        say("error", why(error))
      }
    },
    [say]
  )

  const resetChat = React.useCallback(async () => {
    try {
      await api.resetChat()
    } catch (error) {
      say("error", why(error))
    }
  }, [say])

  const tell = React.useCallback(async (text: string) => {
    const id = openId.current
    if (!id || !text.trim()) return
    // Nothing is drawn here: what appears is what came back on the stream, so
    // the phone that sent it and the laptop that did not show the same thing.
    await api.tell(id, text.trim())
  }, [])

  /* A gesture on a card. The card moves now, goes back if the write fails, and
   * says where it went — a ticket put on hold lands in a column that is often
   * off the screen, and a card that simply vanished reads as a card lost. */
  const move = React.useCallback(async (target: Ticket, column: ColumnKey) => {
    const name =
      currentBoard()?.columns.find((item) => item.key === column)?.name || column
    try {
      if (await moveTicket(target.id, column))
        toast.success(t("“{{title}}” moved to {{column}}", { title: target.title, column: name }))
    } catch (error) {
      toast.error(t("could not move “{{title}}”", { title: target.title }), {
        description: why(error),
      })
    }
  }, [])

  const createTicket = React.useCallback(
    async (fresh: { title: string; body: string; project: string; ready: boolean }) => {
      await api.createTicket(fresh)
      toast.success(t("Ticket created"), { description: fresh.title })
    },
    []
  )

  const refresh = React.useCallback(() => {
    api.refresh().catch((error) => {
      toast.error(t("The board could not be read again"), { description: why(error) })
    })
  }, [])

  /* -- opening -------------------------------------------------------------- */

  React.useEffect(() => {
    // The stream is already open by the time this runs, and only then the three
    // reads: two of them ask Notion, and a console that opened its live
    // connection *after* a slow board sat there saying "connecting…" for as long
    // as Notion took to answer.
    void reloadState()

    void api
      .chat()
      .then((payload) => {
        setTranscript(
          payload.messages.length
            ? payload.messages.map((message) => ({
                id: nextId(),
                kind: "turn" as const,
                role: message.role,
                text: message.text,
              }))
            : [{ id: nextId(), kind: "turn", role: "workspace", text: t(WELCOME) }]
        )
        if (payload.busy) setBusy(true)
      })
      .catch((error) => say("error", why(error)))

    void api
      .projects()
      .then((payload) => setProjects(payload.projects))
      // A board with no projects database is a board that runs.
      .catch(() => {})
  }, [reloadState, say])

  const value = React.useMemo<ConsoleValue>(
    () => ({
      board,
      runner,
      projects,
      transcript,
      busy,
      ticket,
      talk,
      mention,
      talkLoading,
      openTicket,
      closeTicket,
      rereadTalk,
      tell,
      submit,
      resetChat,
      move,
      createTicket,
      refresh,
      runCommand,
      reloadState,
      say,
    }),
    [
      board,
      runner,
      projects,
      transcript,
      busy,
      ticket,
      talk,
      mention,
      talkLoading,
      openTicket,
      closeTicket,
      rereadTalk,
      tell,
      submit,
      resetChat,
      move,
      createTicket,
      refresh,
      runCommand,
      reloadState,
      say,
    ]
  )

  const status = React.useMemo<StatusValue>(() => ({ connection, running }), [connection, running])

  const openShort = ticket?.short ?? ""
  const live = React.useMemo<StepsValue>(
    () => ({
      sessions: running.map((session) => ({
        source: session.source,
        steps: steps[session.source] ?? [],
      })),
      // Kept after the session ends: the open ticket's terminal shows how the
      // run it just finished went, until another ticket is opened.
      ticketSteps: openShort ? (steps[openShort] ?? []) : [],
    }),
    [running, steps, openShort]
  )

  return (
    <StatusContext.Provider value={status}>
      <StepsContext.Provider value={live}>
        <Context.Provider value={value}>{children}</Context.Provider>
      </StepsContext.Provider>
    </StatusContext.Provider>
  )
}
