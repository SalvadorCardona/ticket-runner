import * as React from "react"
import { ArrowLeft } from "lucide-react"
import { ActionList } from "react-data-form"
import { Link, generateLinkByResource, useCurrentViewResourceContext } from "react-resource-view"

import { Skeleton } from "@/components/ui/skeleton"
import { useConsole } from "@/hooks/use-console"
import { useT } from "@/lib/i18n"
import type { TicketDetail } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Eyebrow, Fact, Facts } from "./frame"
import { Markdown } from "./markdown"
import { LABEL, SEED, TONE, TicketActions, TicketLinks, TicketTags, ago } from "./ticket-bits"
import { TicketTalk } from "./ticket-talk"

/* One ticket, as a page.
 *
 * The `read` view of the tickets resource: react-resource-view has fetched
 * `/api/tickets/<id>` by the time this draws, and what it holds is the card
 * plus the page under it — the brief, the report a run appended, the notes
 * between. Beside it (or under it, on a phone) is the ticket's discussion,
 * which is how you talk to it.
 *
 * It opens the way the board's cards do and then says more: the column as a
 * banner, the title big enough to be the page's title, and the metadata as a
 * ruled grid — because six facts in a row of pills is six pills, where six
 * facts in a grid is a thing you can read down.
 */

export function TicketPage() {
  const context = useCurrentViewResourceContext()
  const page = context.data as TicketDetail | undefined
  const { ticket: open, openTicket, board } = useConsole()
  const t = useT()

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
      t(LABEL[ticket.column]) ||
      ticket.column
    : ""

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3.5 py-2.5">
        <Link
          to={back}
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
        >
          <ArrowLeft className="size-3.5" />
          {t("board")}
        </Link>
        <span className="flex-1" />
        {ticket ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <TicketLinks ticket={ticket} />
            <span className="text-muted-foreground font-mono text-xs">#{ticket.short}</span>
          </div>
        ) : null}
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        <div className="p-3.5 sm:p-5">
          {ticket ? (
            <>
              {/* The column, across the top: the one fact that decides what the
                  runner will do with this ticket next. */}
              <div className="bg-card mb-4 flex items-center gap-2 rounded-lg border px-3 py-2">
                <span
                  className={cn(
                    "size-1.5 shrink-0 rounded-full",
                    SEED[ticket.column] ?? "bg-muted-foreground"
                  )}
                />
                <span
                  className={cn(
                    "text-sm font-medium",
                    TONE[ticket.column] ?? "text-muted-foreground"
                  )}
                >
                  {column}
                </span>
                {ticket.progress ? (
                  <span className="text-muted-foreground min-w-0 truncate text-xs">
                    · {ticket.progress}
                  </span>
                ) : null}
              </div>

              <h2 className="text-xl leading-tight font-bold tracking-[-0.02em] text-balance sm:text-2xl">
                {ticket.title}
              </h2>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <TicketTags ticket={ticket} />
                <TicketActions ticket={ticket} className="-mx-1" />
              </div>

              <Facts className="mt-4">
                <Fact label={t("project")}>
                  {ticket.project || t("no project — a document")}
                </Fact>
                <Fact label={t("priority")}>{ticket.priority || "—"}</Fact>
                <Fact label={t("model")}>{ticket.model || "—"}</Fact>
                <Fact label={t("spent")}>
                  {typeof ticket.cost === "number" && ticket.cost
                    ? `$${ticket.cost.toFixed(2)}`
                    : "—"}
                </Fact>
                <Fact label={t("created")}>{ago(ticket.created) || "—"}</Fact>
                <Fact label={t("scheduled")}>
                  {ticket.scheduled ? ticket.scheduled.replace("T", " ") : "—"}
                </Fact>
              </Facts>

              <div className="mt-6">
                <Eyebrow>{t("the brief")}</Eyebrow>
                <div className="mt-2">
                  {ticket.content ? (
                    <Markdown text={ticket.content} />
                  ) : (
                    <p className="text-muted-foreground text-sm">
                      {t("The page is empty: the title is the whole brief.")}
                    </p>
                  )}
                </div>
              </div>
            </>
          ) : context.error ? (
            <p className="text-destructive text-sm">{t("This ticket could not be read.")}</p>
          ) : (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-8 w-2/3" />
              <Skeleton className="mt-2 h-20 w-full" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-5/6" />
            </div>
          )}
        </div>

        {/* On one column there is no pane beside this one: the discussion sits
            under the page, where a phone expects it. */}
        <TicketTalk className="border-t min-[861px]:hidden" bounded />
      </div>
    </div>
  )
}
