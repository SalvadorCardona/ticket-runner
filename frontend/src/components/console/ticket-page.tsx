import * as React from "react"
import { ArrowLeft } from "lucide-react"
import { ActionList } from "react-data-form"
import { Link, generateLinkByResource, useCurrentViewResourceContext } from "react-resource-view"

import { Skeleton } from "@/components/ui/skeleton"
import { useConsole } from "@/hooks/use-console"
import type { TicketDetail } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Markdown } from "./markdown"
import { LABEL, TONE, TicketActions, TicketBadges, TicketLinks } from "./ticket-bits"
import { TicketTalk } from "./ticket-talk"

/* One ticket, as a page.
 *
 * The `read` view of the tickets resource: react-resource-view has fetched
 * `/api/tickets/<id>` by the time this draws, and what it holds is the card
 * plus the page under it — the brief, the report a run appended, the notes
 * between. Beside it (or under it, on a phone) is the ticket's discussion,
 * which is how you talk to it.
 */

export function TicketPage() {
  const context = useCurrentViewResourceContext()
  const page = context.data as TicketDetail | undefined
  const { ticket: open, openTicket, board } = useConsole()

  // The page is the ticket's terminal too: opening it loads the discussion.
  React.useEffect(() => {
    if (page) openTicket(page)
  }, [page, openTicket])

  // The stream keeps the open ticket fresher than the page read once: the
  // column and the progress line are read from it where it is the same ticket.
  const ticket = page ? (open && open.id === page.id ? { ...page, ...open } : page) : null
  const back = generateLinkByResource({ resource: context.resource, resourceAction: ActionList.list })
  const column = ticket
    ? board.columns.find((item) => item.key === ticket.column)?.name ||
      LABEL[ticket.column] ||
      ticket.column
    : ""

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1.5 border-b px-3.5 py-2.5">
        <Link
          to={back}
          className="text-muted-foreground hover:text-foreground mt-0.5 inline-flex items-center gap-1 text-xs"
        >
          <ArrowLeft className="size-3.5" />
          board
        </Link>
        <div className="min-w-0 flex-1 basis-full sm:basis-auto">
          {ticket ? (
            <>
              <h2 className="text-base leading-snug font-semibold">{ticket.title}</h2>
              <p className="mt-0.5 text-xs">
                <span className={cn("font-medium", TONE[ticket.column] ?? "text-muted-foreground")}>
                  {column}
                </span>
                {ticket.progress ? (
                  <span className="text-muted-foreground"> · {ticket.progress}</span>
                ) : null}
              </p>
            </>
          ) : context.error ? (
            <p className="text-destructive text-sm">This ticket could not be read.</p>
          ) : (
            <>
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="mt-1.5 h-3 w-1/3" />
            </>
          )}
        </div>
        {ticket ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <TicketLinks ticket={ticket} />
            <span className="text-muted-foreground font-mono text-xs">#{ticket.short}</span>
          </div>
        ) : null}
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        <div className="p-3.5">
          {ticket ? (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <TicketBadges ticket={ticket} />
                <TicketActions ticket={ticket} />
              </div>
              {ticket.content ? (
                <Markdown text={ticket.content} />
              ) : (
                <p className="text-muted-foreground text-sm">
                  The page is empty: the title is the whole brief.
                </p>
              )}
            </>
          ) : !context.error ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-5/6" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          ) : null}
        </div>

        {/* On one column there is no pane beside this one: the discussion sits
            under the page, where a phone expects it. */}
        <TicketTalk className="border-t min-[861px]:hidden" bounded />
      </div>
    </div>
  )
}
