import { ExternalLink } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useConsole } from "@/hooks/use-console"
import type { Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"

/* What a ticket wears wherever it is drawn — on its card, at the top of its
 * page: the column it is in, the badges, the links out, and the gestures it
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

export function TicketBadges({ ticket }: { ticket: Ticket }) {
  return (
    <div className="flex flex-wrap gap-1">
      <Badge variant="secondary" className="font-normal">
        {ticket.project || "no project — document"}
      </Badge>
      {ticket.priority ? (
        <Badge variant="outline" className="font-normal">
          {ticket.priority}
        </Badge>
      ) : null}
      {ticket.model ? (
        <Badge variant="outline" className="font-normal">
          {ticket.model}
        </Badge>
      ) : null}
      {ticket.scheduled ? (
        <Badge variant="outline" className="font-normal">
          ⏱ {ticket.scheduled.replace("T", " ")}
        </Badge>
      ) : null}
      {typeof ticket.cost === "number" && ticket.cost ? (
        <Badge variant="outline" className="font-normal">
          ${ticket.cost.toFixed(2)}
        </Badge>
      ) : null}
    </div>
  )
}

/** The gestures a ticket offers where it stands. */
export function TicketActions({ ticket, className }: { ticket: Ticket; className?: string }) {
  const { move, board } = useConsole()
  const quiet = "text-muted-foreground hover:text-foreground"
  return (
    <div className={cn("flex flex-wrap items-center gap-x-1 gap-y-1", className)}>
      {ticket.column !== "ready" && ticket.column !== "running" ? (
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
