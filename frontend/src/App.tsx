import * as React from "react"
import { ActionList } from "react-data-form"

import { AppSidebar } from "@/components/console/app-sidebar"
import { ConsolePane } from "@/components/console/console-pane"
import { ContextPane } from "@/components/console/context-pane"
import { Header } from "@/components/console/header"
import { LivePane } from "@/components/console/live-pane"
import { ResourcePane } from "@/components/console/resource-pane"
import { SchedulesPane } from "@/components/console/schedules-pane"
import { TicketTalk } from "@/components/console/ticket-talk"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ConsoleProvider, useConsole } from "@/hooks/use-console"
import { useBoard } from "@/lib/board-store"
import { useT } from "@/lib/i18n"
import { useRoute, type Page } from "@/lib/router"
import { cn } from "@/lib/utils"
import { PROJECTS } from "@/resources/projects"
import { SETTINGS } from "@/resources/settings"
import { TICKETS } from "@/resources/tickets"

/* The shape of the page.
 *
 * A menu down the left, and to the right of it two columns. The first is what
 * the address names: the board, a ticket, the live sessions, the settings. The
 * second is the thing you talk to while looking at the first — the workspace
 * console, or, on a ticket's page, that ticket. Below 861px there is only room
 * for one column: the console becomes an entry in the menu like the rest, and
 * a ticket's discussion sits under its page. Below 768px the menu is a drawer.
 */

/** What each pane is called in the bar's path. Lower case: it is a segment, not a title. */
const CRUMB: Record<Page, string> = {
  console: "console",
  live: "live",
  context: "context",
  schedules: "schedules",
}

const ASIDE = "ticket-runner-aside"

function Console() {
  const route = useRoute()
  const board = useBoard()
  const t = useT()
  const { ticket, openTicket, closeTicket } = useConsole()

  // Which resource the address names. An address that names none is the board.
  const resourceId = route.kind === "resource" ? (route.params.resourceId ?? TICKETS) : null

  // The address says which ticket is open; the board says what it is, so the
  // discussion loads while the page is still being read.
  const ticketId =
    route.kind === "resource" &&
    resourceId === TICKETS &&
    route.params.resourceAction === ActionList.read &&
    route.params.id
      ? String(route.params.id)
      : null
  React.useEffect(() => {
    if (!ticketId) {
      closeTicket()
      return
    }
    const known = board.tickets.find((item) => item.id === ticketId)
    if (known) openTicket(known)
  }, [ticketId, board, openTicket, closeTicket])

  const [aside, setAside] = React.useState(() => {
    try {
      return localStorage.getItem(ASIDE) !== "hidden"
    } catch {
      return true
    }
  })
  const toggleAside = () => {
    setAside((shown) => {
      try {
        localStorage.setItem(ASIDE, shown ? "hidden" : "shown")
      } catch {
        // Remembered for as long as the tab is open, then.
      }
      return !shown
    })
  }

  // The bar says the path, not the title: `workspace / board / #3f2a1c`. The
  // page under it opens with the heading, so a ticket is named here by its id
  // — the short thing that fits a breadcrumb — rather than by its sentence.
  const crumbs =
    route.kind === "page"
      ? [t("workspace"), t(CRUMB[route.page])]
      : resourceId === SETTINGS
        ? [t("workspace"), t("settings")]
        : resourceId === PROJECTS
          ? [t("workspace"), t("projects")]
          : ticketId
            ? [t("workspace"), t("board"), `#${ticket?.short ?? String(ticketId).slice(-8)}`]
            : [t("workspace"), t("board")]

  // Each pane keeps its place while another is shown, so a transcript
  // half-read and a text half-typed survive a trip through the menu.
  const cell = (name: "live" | "context", child: React.ReactNode) => {
    const shown = route.kind === "page" && route.page === name
    return (
      <div
        key={name}
        className={cn(
          "col-start-1 row-start-1 min-h-0 overflow-hidden",
          shown ? "flex flex-col" : "hidden",
          name === "live" && "scroll-thin overflow-y-auto"
        )}
      >
        {child}
      </div>
    )
  }

  const twoColumns = aside ? "min-[861px]:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]" : ""

  return (
    <>
      <AppSidebar route={route} />
      <SidebarInset className="min-h-0 overflow-hidden">
        <div className="flex h-full min-h-0 flex-col">
          <Header
            crumbs={crumbs}
            aside={aside}
            asideLabel={ticketId ? t("the discussion") : t("the console")}
            onToggleAside={toggleAside}
          />

          <div className={cn("grid min-h-0 flex-1 grid-cols-1", twoColumns)}>
            {route.kind === "resource" ? (
              <div
                className={cn(
                  "scroll-thin col-start-1 row-start-1 min-h-0",
                  ticketId ? "flex flex-col overflow-hidden" : "overflow-y-auto"
                )}
              >
                <ResourcePane params={route.params} />
              </div>
            ) : null}
            {cell("live", <LivePane />)}
            {/* A `cell` for the same reason the live pane is one: it holds a
                text somebody is half-way through rewriting, and a trip through
                the menu must not cost it. */}
            {cell("context", <ContextPane />)}

            {/* Not `cell`s: these two have nothing half-typed to keep, and the
                only way to draw either is to ask the board — which a tab left
                open on the tickets has no business making it do. */}
            {route.kind === "page" && route.page === "schedules" ? (
              <div className="scroll-thin col-start-1 row-start-1 min-h-0 overflow-y-auto">
                <SchedulesPane />
              </div>
            ) : null}

            {/* The second column, or the whole page below 861px when the
                address is the console's. */}
            <div
              className={cn(
                "col-start-1 row-start-1 min-h-0 flex-col",
                aside && "min-[861px]:col-start-2 min-[861px]:flex min-[861px]:border-l",
                route.kind === "page" && route.page === "console" ? "flex" : "hidden"
              )}
            >
              {ticketId ? <TicketTalk className="max-[860px]:hidden" /> : null}
              <div
                className={cn(
                  "min-h-0 flex-1 flex-col",
                  ticketId ? "flex min-[861px]:hidden" : "flex"
                )}
              >
                <ConsolePane />
              </div>
            </div>
          </div>
        </div>
      </SidebarInset>
    </>
  )
}

export default function App() {
  return (
    <TooltipProvider>
      <ConsoleProvider>
        <SidebarProvider className="h-svh min-h-0">
          <Console />
          <Toaster />
        </SidebarProvider>
      </ConsoleProvider>
    </TooltipProvider>
  )
}
