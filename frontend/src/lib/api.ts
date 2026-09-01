import type {
  Board,
  ChatState,
  Message,
  Project,
  RunnerState,
  Saved,
  Settings,
  SettingValue,
  Talk,
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

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
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
  projects: () => request<{ projects: Project[] }>("/api/projects"),
  chat: () => request<{ messages: Message[] } & ChatState & { busy?: boolean }>("/api/chat"),
  settings: () => request<Settings>("/api/settings"),
  talk: (id: string) => request<Talk>(`/api/tickets/${id}/talk`),

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
    projects?: { name: string; path: string }[]
  }) => request<Saved>("/api/settings", payload),
  refresh: () => request<unknown>("/api/refresh", {}),
}

/** The message of whatever went wrong, however it went wrong. */
export function why(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
