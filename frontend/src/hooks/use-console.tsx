import * as React from "react"
import { toast } from "sonner"

import { api, why } from "@/lib/api"
import type {
  Board,
  ChatEvent,
  CommandEvent,
  Message,
  NoticeEvent,
  Project,
  Role,
  RunnerState,
  Step,
  StepEvent,
  TalkEvent,
  Ticket,
} from "@/lib/types"
import { useStream, type Connection } from "./use-stream"

/* Everything the console knows, in one place.
 *
 * The hand-written console kept a `state` object at the top of its single file
 * and mutated it. This is the same object, held by React so that the parts of
 * the page that care about a field redraw when it changes and the rest do not.
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

const WELCOME =
  "Ask me anything about your workspace — I can read your repositories, look at the board " +
  "and create tickets. Type > followed by a command (>status, >list, >run) to use the CLI directly."

interface ConsoleValue {
  connection: Connection
  board: Board
  runner: RunnerState | null
  projects: Project[]
  transcript: Entry[]
  busy: boolean
  sessions: Session[]
  ticket: Ticket | null
  talk: Message[]
  mention: string
  ticketSteps: Step[]
  talkLoading: boolean
  openTicket: (ticket: Ticket) => void
  rereadTalk: () => void
  tell: (text: string) => Promise<void>
  submit: (text: string) => Promise<void>
  resetChat: () => Promise<void>
  move: (ticket: Ticket, column: string) => Promise<void>
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

const Context = React.createContext<ConsoleValue | null>(null)

export function useConsole(): ConsoleValue {
  const value = React.useContext(Context)
  if (!value) throw new Error("useConsole outside its provider")
  return value
}

export function ConsoleProvider({ children }: { children: React.ReactNode }) {
  const [board, setBoard] = React.useState<Board>({ tickets: [], columns: [] })
  const [runner, setRunner] = React.useState<RunnerState | null>(null)
  const [projects, setProjects] = React.useState<Project[]>([])
  const [transcript, setTranscript] = React.useState<Entry[]>([])
  const [busy, setBusy] = React.useState(false)
  const [sessions, setSessions] = React.useState<Session[]>([])
  const [ticket, setTicket] = React.useState<Ticket | null>(null)
  const [talk, setTalk] = React.useState<Message[]>([])
  const [mention, setMention] = React.useState("")
  const [ticketSteps, setTicketSteps] = React.useState<Step[]>([])
  const [talkLoading, setTalkLoading] = React.useState(false)

  // What the stream handlers need to read without being rebuilt for it.
  const openId = React.useRef<string | null>(null)
  const openShort = React.useRef<string>("")
  const openColumn = React.useRef<string>("")

  const say = React.useCallback((role: Role, text: string) => {
    setTranscript((entries) => [...entries, { id: nextId(), kind: "turn", role, text }])
  }, [])

  const reloadState = React.useCallback(async () => {
    try {
      setRunner(await api.state())
    } catch {
      // The header going stale is not worth a message: the stream is still up,
      // and the next event asks again.
    }
  }, [])

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
      setTalk([{ role: "error", text: `could not read the discussion: ${why(error)}` }])
    } finally {
      setTalkLoading(false)
    }
  }, [])

  const openTicket = React.useCallback(
    (open: Ticket) => {
      const another = openId.current !== open.id
      openId.current = open.id
      openShort.current = open.short
      openColumn.current = open.column
      setTicket(open)
      if (another) {
        setTicketSteps([])
        setTalk([])
      }
      void loadTalk(open)
    },
    [loadTalk]
  )

  const rereadTalk = React.useCallback(() => {
    if (ticket) void loadTalk(ticket)
  }, [ticket, loadTalk])

  /* -- the stream ----------------------------------------------------------- */

  const connection = useStream({
    board: (fresh: Board) => {
      setBoard(fresh)
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
      openShort.current = moved.short
      setTicket(moved)
      if (changed) void loadTalk(moved)
    },

    step: (event: StepEvent) => {
      const line: Step = { label: event.label, detail: event.detail }
      setSessions((current) => {
        const found = current.findIndex((item) => item.source === event.source)
        if (found < 0) return [{ source: event.source, steps: [line] }, ...current]
        const kept = [...current]
        kept[found] = {
          ...kept[found],
          steps: [...kept[found].steps, line].slice(-KEPT),
        }
        return kept
      })
      // The same step, in the terminal of the ticket it belongs to — so that
      // reading a ticket and watching it work are one place rather than two.
      if (event.source === openShort.current)
        setTicketSteps((steps) => [...steps, line].slice(-KEPT))
    },

    chat: (event: ChatEvent) => {
      if (event.stage === "reset") {
        setTranscript([{ id: nextId(), kind: "turn", role: "workspace", text: WELCOME }])
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

  const submit = React.useCallback(
    async (text: string) => {
      const line = text.trim()
      if (!line) return
      try {
        if (line.trimStart().startsWith(">"))
          await api.command(line.replace(/^\s*>/, ""))
        else await api.send(line)
      } catch (error) {
        say("error", why(error))
        setBusy(false)
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

  const move = React.useCallback(
    async (target: Ticket, column: string) => {
      try {
        await api.setStatus(target.id, column)
      } catch (error) {
        toast.error(`could not move “${target.title}”`, { description: why(error) })
      }
    },
    []
  )

  const createTicket = React.useCallback(
    async (fresh: { title: string; body: string; project: string; ready: boolean }) => {
      await api.createTicket(fresh)
      toast.success("Ticket created", { description: fresh.title })
    },
    []
  )

  const refresh = React.useCallback(() => {
    void api.refresh().catch(() => {})
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
            : [{ id: nextId(), kind: "turn", role: "workspace", text: WELCOME }]
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

  const value: ConsoleValue = {
    connection,
    board,
    runner,
    projects,
    transcript,
    busy,
    sessions,
    ticket,
    talk,
    mention,
    ticketSteps,
    talkLoading,
    openTicket,
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
  }

  return <Context.Provider value={value}>{children}</Context.Provider>
}
