import * as React from "react"

import { api } from "./api"
import type { Board, ColumnKey, Ticket } from "./types"

/* The board, as the stream last said it.
 *
 * react-resource-view asks a resource for its rows through `getCollection`,
 * and the natural thing to give it would be a request to `/api/board`. That
 * would ask Notion again every time the list redraws — while the stream is
 * already carrying the very same board every few seconds, to every open tab.
 * So the rows come from here: the stream writes, the resource reads, and a
 * redraw costs nothing.
 */

let board: Board | null = null
const listeners = new Set<() => void>()
const waiting: ((board: Board) => void)[] = []

const tell = () => listeners.forEach((listener) => listener())

/** What the stream just said. */
export function publishBoard(fresh: Board) {
  board = fresh
  for (const resolve of waiting.splice(0)) resolve(fresh)
  tell()
}

/** A ticket as the console already knows it will be, before Notion confirms.
 *
 * A card dropped in a column has to land there now; the board event that
 * follows the write says the same thing a few seconds later. */
export function patchTicket(id: string, patch: Partial<Ticket>) {
  if (!board) return
  board = {
    ...board,
    tickets: board.tickets.map((ticket) => (ticket.id === id ? { ...ticket, ...patch } : ticket)),
  }
  tell()
}

/** A ticket just written, drawn before the board is reread. */
export function addTicket(ticket: Ticket) {
  if (!board || board.tickets.some((item) => item.id === ticket.id)) return
  board = { ...board, tickets: [...board.tickets, ticket] }
  tell()
}

export const currentBoard = (): Board | null => board

/* A card moved to another column: drawn there now, written, and put back where
 * it was if the write fails. The one way a ticket changes column from the
 * console — the buttons on a card and a card dropped on the board both come
 * through here, so neither can leave a card standing in a column Notion never
 * heard about. Says whether it moved anything. */
export async function moveTicket(id: string, column: ColumnKey): Promise<boolean> {
  const before = board?.tickets.find((ticket) => ticket.id === id)
  if (before && before.column === column) return false
  if (before) patchTicket(id, { column })
  try {
    await api.setStatus(id, column)
  } catch (error) {
    if (before) patchTicket(id, { column: before.column, status: before.status })
    throw error
  }
  return true
}

/** The board, as soon as there is one. */
export function boardOnce(): Promise<Board> {
  if (board) return Promise.resolve(board)
  return new Promise((resolve) => waiting.push(resolve))
}

export function subscribeBoard(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

const EMPTY: Board = { tickets: [], columns: [] }

export function useBoard(): Board {
  return React.useSyncExternalStore(subscribeBoard, () => board ?? EMPTY)
}
