import type {
  Board,
  LogEntry,
  ChatState,
  Context,
  Message,
  Pair,
  ProjectDetail,
  Projects,
  RunnerState,
  Saved,
  ScheduleDetail,
  Schedules,
  Settings,
  SettingValue,
  Step,
  Talk,
  TicketDetail,
} from "./types"

/* Talking to the server.
 *
 * Two things every request here carries, and neither is decoration:
 *
 * - `X-Ticket-Runner: 1`. The server refuses a write without it, because a page
 *   you have open in another tab can post a form to this port with your cookie
 *   attached but cannot set a header of its own without a preflight this server
 *   never answers. The header is the difference between "the console asked" and
 *   "some page you had open asked".
 * - `credentials: "same-origin"`, which is what sends that cookie at all.
 */

const GUARD = { "X-Ticket-Runner": "1" }

export class ApiError extends Error {
  readonly status: number
  /* The payload as it arrived, under the name react-resource-view looks for.
   *
   * A form drawn by that package hands whatever a write threw to its own
   * `normalizeApiError`, which reads an error's `data` and passes it to the
   * dialect. Without it the sentence the server refused with reaches the
   * browser's console and nowhere else — and a save that fails quietly is a
   * save you think worked. */
  readonly data: { error: string }

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.data = { error: message }
  }
}

let leaving = false

/* The sign-in page is what the server answers `/` with to a browser it does
 * not know, so going back to it is reloading the page. Once: two requests
 * refused in the same second must not reload twice. */
function backToTheDoor() {
  if (leaving) return
  leaving = true
  window.location.reload()
}

/** Whether the server still knows this browser — asked when the stream closes. */
export async function signedOut(): Promise<boolean> {
  try {
    const response = await fetch("/api/state", {
      headers: { ...GUARD },
      credentials: "same-origin",
    })
    if (response.status !== 401) return false
  } catch {
    // The server is down, not the session: the stream is tried again.
    return false
  }
  backToTheDoor()
  return true
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const options: RequestInit = body
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json", ...GUARD },
        body: JSON.stringify(body),
      }
    : { headers: { ...GUARD } }
  const response = await fetch(path, { ...options, credentials: "same-origin" })
  // Signed out underneath the page — a password changed, a cookie expired, the
  // console restarted with another token. Every call after this one would fail
  // the same way, each with its own toast: the page goes back to the door.
  if (response.status === 401) backToTheDoor()
  const payload = await response.json().catch(() => ({}) as Record<string, unknown>)
  if (!response.ok) {
    const said = (payload as { error?: string }).error
    throw new ApiError(said || String(response.status), response.status)
  }
  return payload as T
}

export const api = {
  state: () => request<RunnerState>("/api/state"),
  board: () => request<Board>("/api/board"),
  projects: () => request<Projects>("/api/projects"),
  context: () => request<Context>("/api/context"),
  schedules: () => request<Schedules>("/api/schedules"),
  schedule: (id: string) => request<ScheduleDetail>(`/api/schedules/${id}`),
  chat: () => request<{ messages: Message[] } & ChatState & { busy?: boolean }>("/api/chat"),
  settings: () => request<Settings>("/api/settings"),
  project: (id: string) => request<ProjectDetail>(`/api/projects/${id}`),
  ticket: (id: string) => request<TicketDetail>(`/api/tickets/${id}`),
  talk: (id: string) => request<Talk>(`/api/tickets/${id}/talk`),
  logs: () => request<{ logs: LogEntry[] }>("/api/logs"),
  log: (name: string) => request<{ name: string; steps: Step[] }>(`/api/logs/${encodeURIComponent(name)}`),

  createTicket: (ticket: {
    title: string
    body: string
    project: string
    ready: boolean
  }) => request<{ id: string; title: string }>("/api/tickets", ticket),
  setStatus: (id: string, column: string) =>
    request<{ id: string; status: string }>(`/api/tickets/${id}/status`, { column }),
  tell: (id: string, text: string) =>
    request<unknown>(`/api/tickets/${id}/talk`, { text }),
  command: (line: string) => request<unknown>("/api/command", { line }),
  send: (text: string) => request<unknown>("/api/chat", { text }),
  resetChat: () => request<unknown>("/api/chat/reset", {}),
  saveSettings: (payload: {
    settings: Record<string, SettingValue>
    projects?: Pair[]
    github?: Pair[]
  }) => request<Saved>("/api/settings", payload),
  saveContext: (text: string) => request<{ text: string }>("/api/context", { text }),
  saveProject: (id: string, values: Record<string, unknown>) =>
    request<ProjectDetail>(`/api/projects/${id}`, values),
  saveSchedule: (id: string, values: Record<string, unknown>) =>
    request<{ id: string }>(`/api/schedules/${id}`, values),
  createSchedule: (values: Record<string, unknown>) =>
    request<{ id: string; name: string }>("/api/schedules", values),
  refresh: () => request<unknown>("/api/refresh", {}),
}

/** The message of whatever went wrong, however it went wrong. */
export function why(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
