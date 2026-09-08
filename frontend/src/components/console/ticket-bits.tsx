import * as React from "react"
import { ExternalLink } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useConsole } from "@/hooks/use-console"
import type { Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"

/* What a ticket wears wherever it is drawn — on its card, at the top of its
 * page: the column it is in, the tags, the links out, and the gestures it
 * offers where it stands. */

export const LABEL: Record<string, string> = {
  ready: "Ready",
  running: "In progress",
  review: "In review",
  validated: "Validated",
  blocked: "Blocked",
  failed: "Failed",
  done: "Done",
  other: "Elsewhere",
}

/** The colour of a column, on the left edge of a card. */
export const EDGE: Record<string, string> = {
  ready: "border-l-tr-green",
  running: "border-l-tr-blue",
  review: "border-l-tr-violet",
  validated: "border-l-tr-pink",
  blocked: "border-l-tr-amber",
  failed: "border-l-tr-red",
}

/** The same colour, as text. */
export const TONE: Record<string, string> = {
  ready: "text-tr-green",
  running: "text-tr-blue",
  review: "text-tr-violet",
  validated: "text-tr-pink",
  blocked: "text-tr-amber",
  failed: "text-tr-red",
}

/** The same colour again, as a dot — over a column, beside a status. */
export const SEED: Record<string, string> = {
  ready: "bg-tr-green",
  running: "bg-tr-blue",
  review: "bg-tr-violet",
  validated: "bg-tr-pink",
  blocked: "bg-tr-amber",
  failed: "bg-tr-red",
}

/* How long ago, in the two words a card has room for. Cards are read in a
 * glance and a glance does not parse a timestamp: "12 min ago" says the one
 * thing you wanted from it, and the exact instant is on the ticket's page. */
export function ago(at: string): string {
  const then = new Date(at).getTime()
  if (Number.isNaN(then)) return ""
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 90) return "just now"
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  return days < 30 ? `${days}d ago` : `${Math.round(days / 30)}mo ago`
}

/** A tag: one word about a ticket, drawn small enough that five of them still read as one row. */
export function Chip({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        "text-muted-foreground inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[0.7rem] whitespace-nowrap",
        className
      )}
    >
      {children}
    </span>
  )
}

export function Away({ label, href }: { label: string; href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline"
    >
      {label}
      <ExternalLink className="size-3" />
    </a>
  )
}

/** Notion, the pull request, the session — whichever the ticket has. */
export function TicketLinks({ ticket }: { ticket: Ticket }) {
  return (
    <>
      <Away label="Notion" href={ticket.url} />
      {ticket.pull_request ? <Away label="pull request" href={ticket.pull_request} /> : null}
      {ticket.session_link ? <Away label="session" href={ticket.session_link} /> : null}
    </>
  )
}

/** What is said *about* a ticket rather than in it: how urgent, on which model, when. */
export function TicketTags({ ticket }: { ticket: Ticket }) {
  if (!ticket.priority && !ticket.model && !ticket.scheduled) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {ticket.priority ? <Chip>{ticket.priority}</Chip> : null}
      {ticket.model ? <Chip>{ticket.model}</Chip> : null}
      {ticket.scheduled ? <Chip>⏱ {ticket.scheduled.replace("T", " ")}</Chip> : null}
    </div>
  )
}

/* The line along the bottom of a card: where the work goes, what it has cost,
 * and the way out to Notion. All three are facts rather than prose, so all
 * three are set in the mono face and read as a single ruled row. */
export function TicketFoot({ ticket }: { ticket: Ticket }) {
  return (
    <div className="flex items-center gap-2 border-t pt-2.5 font-mono text-[0.7rem]">
      <span className="text-muted-foreground min-w-0 flex-1 truncate">
        {ticket.project || "no project"}
      </span>
      {typeof ticket.cost === "number" && ticket.cost ? (
        <span className="tabular-nums">${ticket.cost.toFixed(2)}</span>
      ) : null}
      {ticket.url ? (
        <a
          href={ticket.url}
          target="_blank"
          rel="noreferrer noopener"
          className="text-muted-foreground hover:text-foreground shrink-0"
          aria-label="open in Notion"
          onClick={(event) => event.stopPropagation()}
        >
          <ExternalLink className="size-3.5" />
        </a>
      ) : null}
    </div>
  )
}

/** The gestures a ticket offers where it stands, or nothing at all where it offers none. */
export function TicketActions({ ticket, className }: { ticket: Ticket; className?: string }) {
  const { move, board } = useConsole()
  const quiet = "text-muted-foreground hover:text-foreground"
  // A ticket the runner has in hand is not one you move: drawing an empty row
  // for it would leave a gap on the card where the gestures would have been.
  if (ticket.column === "running") return null
  return (
    <div className={cn("flex flex-wrap items-center gap-x-1 gap-y-1", className)}>
      {ticket.column !== "ready" ? (
        <Button variant="ghost" size="xs" className={quiet} onClick={() => move(ticket, "ready")}>
          {ticket.column === "review" ? "run again" : "make ready"}
        </Button>
      ) : null}
      {/* Validating is the gesture the runner acts on — it merges the pull
          request, or publishes what the ticket holds — where "done" only files
          the ticket away yourself. Offered only on a board that has the column. */}
      {ticket.column === "review" && board.validate ? (
        <Button
          variant="ghost"
          size="xs"
          className="text-tr-pink hover:text-tr-pink"
          onClick={() => move(ticket, "validated")}
        >
          validate
        </Button>
      ) : null}
      {ticket.column === "review" ? (
        <Button variant="ghost" size="xs" className={quiet} onClick={() => move(ticket, "done")}>
          done
        </Button>
      ) : null}
      {ticket.column === "ready" ? (
        <Button variant="ghost" size="xs" className={quiet} onClick={() => move(ticket, "blocked")}>
          hold
        </Button>
      ) : null}
    </div>
  )
}
