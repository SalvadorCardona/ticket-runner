import * as React from "react"

import { AppSidebar } from "@/components/console/app-sidebar"
import { BoardPane } from "@/components/console/board-pane"
import { ConsolePane } from "@/components/console/console-pane"
import { Header } from "@/components/console/header"
import { LivePane } from "@/components/console/live-pane"
import { SettingsPane } from "@/components/console/settings-pane"
import { TicketPane } from "@/components/console/ticket-pane"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ConsoleProvider, useConsole } from "@/hooks/use-console"
import type { Pane } from "@/lib/menu"
import { cn } from "@/lib/utils"

/* The shape of the page.
 *
 * A menu down the left, and to the right of it two columns: the pane the menu
 * chose, and the console — which stays put whichever of the other four is
 * chosen, because it is the thing you talk to while looking at them. Below
 * 861px there is only room for one column and the console becomes an entry in
 * the menu like the rest; below 768px the menu itself becomes a drawer.
 */

const TITLE: Record<Pane, string> = {
  board: "Board",
  ticket: "Ticket",
  console: "Console",
  live: "Sessions",
  settings: "Settings",
}

function Console() {
  const [pane, setPane] = React.useState<Pane>("board")
  const { ticket, runCommand } = useConsole()

  // Clicking a card is what opens a ticket; this is what makes the pane it
  // opened into the one you are looking at.
  const opened = React.useRef<string | null>(null)
  React.useEffect(() => {
    if (ticket && ticket.id !== opened.current) {
      opened.current = ticket.id
      setPane("ticket")
    }
  }, [ticket])

  const check = (verb: string) => {
    setPane("console")
    void runCommand(verb)
  }

  const cell = (name: Exclude<Pane, "console">) => (
    <div
      key={name}
      className={cn(
        "scroll-thin col-start-1 row-start-1 min-h-0 overflow-y-auto",
        pane === name ? "block" : "hidden",
        // The two panes that hold a composer at the bottom manage their own
        // scrolling, and must not be scrolled a second time by this cell.
        (name === "ticket" || name === "settings") && "overflow-hidden",
        pane === name && (name === "ticket" || name === "settings") && "flex flex-col"
      )}
    >
      {name === "board" ? <BoardPane /> : null}
      {name === "ticket" ? <TicketPane /> : null}
      {name === "live" ? <LivePane /> : null}
      {name === "settings" ? <SettingsPane onCheck={check} /> : null}
    </div>
  )

  return (
    <>
      <AppSidebar pane={pane} setPane={setPane} />
      <SidebarInset className="min-h-0 overflow-hidden">
        <div className="flex h-full min-h-0 flex-col">
          <Header title={TITLE[pane]} />

          <div className="grid min-h-0 flex-1 grid-cols-1 min-[861px]:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            {(["board", "ticket", "live", "settings"] as const).map(cell)}

            <div
              className={cn(
                "col-start-1 row-start-1 min-h-0 flex-col",
                "min-[861px]:col-start-2 min-[861px]:flex min-[861px]:border-l",
                pane === "console" ? "flex" : "hidden"
              )}
            >
              <ConsolePane />
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
