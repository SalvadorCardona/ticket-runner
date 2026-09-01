/* The shapes the Python side sends, written down once.
 *
 * Every one of these mirrors a dict built in `src/ticket_runner/web/` — `api.py`
 * for the reads and writes, `console.py` and `live.py` for what comes down the
 * event stream. When a field is added there, it is added here, and TypeScript
 * says which components have to care.
 */

export type ColumnKey =
  | "ready"
  | "running"
  | "review"
  | "validated"
  | "blocked"
  | "failed"
  | "done"
  | "other"

export interface Ticket {
  id: string
  short: string
  title: string
  url: string
  status: string
  column: ColumnKey
  project: string
  kind: string
  priority: string
  model: string
  progress: string
  runner: string
  pull_request: string
  session: string
  session_link: string
  cost: number | null
  duration: number | null
  scheduled: string
  created: string
}

export interface Board {
  tickets: Ticket[]
  /** Whether this board has a `validated` column the runner would honour. */
  validate?: boolean
  columns: { key: ColumnKey; name: string }[]
}

export interface Project {
  id: string
  name: string
  kind: string
  url: string
}

export interface ChatState {
  session_id: string
  turns: number
  resume_command: string
}

export interface RunnerState {
  timer: string
  running: boolean
  lock: string
  workspace_root: string
  interval_seconds: number
  model: string
  permission_mode: string
  claude: boolean
  version: string
  update: string
  spend: number
  handled: number
  chat: ChatState
  commands: string[]
  busy: boolean
}

/** A line of a session: the tool it used, and what it used it on. */
export interface Step {
  label: string
  detail: string
}

export type Role = "you" | "workspace" | "error" | "command"

export interface Message {
  role: Role
  text: string
  at?: string
}

export interface Talk {
  id: string
  mention: string
  messages: Message[]
}

/* -- what the stream carries ------------------------------------------------ */

export interface StepEvent extends Step {
  source: string
  log: string
}

export type ChatEvent =
  | { stage: "reset" }
  | { stage: "sent"; text: string; session_id: string }
  | ({ stage: "step" } & Step)
  | {
      stage: "answer" | "failed"
      text: string
      ok?: boolean
      cost_usd?: number
      seconds?: number
      session_id?: string
    }

export type CommandEvent =
  | { stage: "started"; argv: string[] }
  | { stage: "line"; text: string }
  | { stage: "ended"; code: number }

export interface TalkEvent extends Message {
  ticket: string
}

export interface NoticeEvent {
  where: string
  message: string
}

/* -- settings --------------------------------------------------------------- */

export type FieldKind = "text" | "int" | "bool" | "choice" | "events" | "secret"

export interface SettingField {
  name: string
  kind: FieldKind
  label: string
  help: string
  choices: string[]
  fallback: unknown
  after: string
  stated: boolean
  value: string | number | boolean | string[] | null
  preview?: string
}

export interface SettingSection {
  key: string
  title: string
  blurb: string
  pairs: string
  fields: SettingField[]
}

export interface ProjectPath {
  name: string
  path: string
}

export interface Settings {
  path: string
  usable: boolean
  problem: string
  sections: SettingSection[]
  projects: ProjectPath[]
}

export interface Saved {
  saved: string[]
  after: string[]
}

/** What a settings field may become on the way back to the file. */
export type SettingValue = string | number | boolean | string[] | null
