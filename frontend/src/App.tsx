import * as React from "react"

import { BoardPane } from "@/components/console/board-pane"
import { ConsolePane } from "@/components/console/console-pane"
import { Header } from "@/components/console/header"
import { LivePane } from "@/components/console/live-pane"
import { SettingsPane } from "@/components/console/settings-pane"
import { TicketPane } from "@/components/console/ticket-pane"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { ConsoleProvider, useConsole } from "@/hooks/use-console"
import { cn } from "@/lib/utils"

/* Two columns on a screen, one at a time on a phone.
 *
 * The console is always the right-hand one, whichever of the other four is
 * chosen — so choosing one must not take it away. Below 861px there is only
 * room for one, and the console becomes a tab like the rest.
 */

type Pane = "board" | "ticket" | "console" | "live" | "settings"

const PANES: { key: Pane; label: string }[] = [
  { key: "board", label: "Board" },
  { key: "ticket", label: "Ticket" },
  { key: "console", label: "Console" },
  { key: "live", label: "Live" },
  { key: "settings", label: "Settings" },
]

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

  const chosen = (name: Pane) => (
    <div
      key={name}
      className={cn(
        "col-start-1 row-start-1 min-h-0 overflow-y-auto",
        "scroll-thin",
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
    <div className="flex h-full flex-col">
      <Header />

      <nav className="flex gap-1 border-b px-3 py-1.5">
        {PANES.map((item) => (
          <button
            key={item.key}
            onClick={() => setPane(item.key)}
            aria-current={pane === item.key}
            className={cn(
              "focus-visible:ring-ring/50 cursor-pointer rounded-md px-3 py-1 text-sm font-medium transition-colors focus-visible:ring-[3px] focus-visible:outline-none",
              pane === item.key
                ? "bg-secondary text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <main className="grid min-h-0 flex-1 grid-cols-1 min-[861px]:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        {PANES.filter((item) => item.key !== "console").map((item) => chosen(item.key))}

        <div
          className={cn(
            "col-start-1 row-start-1 min-h-0 flex-col border-l",
            "min-[861px]:col-start-2 min-[861px]:flex",
            pane === "console" ? "flex max-[860px]:border-l-0" : "hidden"
          )}
        >
          <ConsolePane />
        </div>
      </main>

      <Toaster />
    </div>
  )
}

export default function App() {
  return (
    <TooltipProvider>
      <ConsoleProvider>
        <Console />
      </ConsoleProvider>
    </TooltipProvider>
  )
}
