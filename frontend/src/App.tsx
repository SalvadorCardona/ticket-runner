import * as React from "react"
import { ActionList } from "react-data-form"

import { AppSidebar } from "@/components/console/app-sidebar"
import { ContextPane } from "@/components/console/context-pane"
import { Header } from "@/components/console/header"
import { LivePane } from "@/components/console/live-pane"
import { ResourcePane } from "@/components/console/resource-pane"
import { TalkDrawer } from "@/components/console/talk-drawer"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ConsoleProvider, useConsole } from "@/hooks/use-console"
import { useBoard } from "@/lib/board-store"
import { useT } from "@/lib/i18n"
import { useRoute, type Page } from "@/lib/router"
import { cn } from "@/lib/utils"
import { PROJECTS } from "@/resources/projects"
import { SCHEDULES } from "@/resources/schedules"
import { SETTINGS } from "@/resources/settings"
import { TICKETS } from "@/resources/tickets"

/* The shape of the page.
 *
 * A menu down the left, and one column beside it: what the address names — the
 * board, a ticket, the live sessions, the settings. There used to be a second
 * one, holding whatever you talk to while looking at the first, with an entry
 * in the menu to reach it on a phone and a switch in the bar to fold it away.
 * It is a drawer now, opened by the bubble in the bottom corner, at every
 * width: the page keeps its width until you ask for the conversation, and
 * there is one way in rather than three. Below 768px the menu is a drawer too.
 */

/** What each pane is called in the bar's path. Lower case: it is a segment, not a title. */
const CRUMB: Record<Page, string> = {
  live: "live",
  context: "context",
}

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
          : resourceId === SCHEDULES
            ? [t("workspace"), t("schedules")]
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

  return (
    <>
      <AppSidebar route={route} />
      <SidebarInset className="min-h-0 overflow-hidden">
        <div className="flex h-full min-h-0 flex-col">
          <Header crumbs={crumbs} />

          <div className="grid min-h-0 flex-1 grid-cols-1">
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
          </div>
        </div>
      </SidebarInset>

      {/* Over everything, at every width: the conversation is never a page you
          navigate to and lose your place for. */}
      <TalkDrawer />
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
