import { Moon, RefreshCw, Sun } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useConsole } from "@/hooks/use-console"
import { useTheme } from "@/hooks/use-theme"
import { cn } from "@/lib/utils"

/** An interval, as somebody would say it out loud. */
function every(seconds: number): string {
  if (!seconds) return ""
  return seconds < 120 ? `${seconds}s` : `${Math.round(seconds / 60)} min`
}

/* What the runner is doing, above everything else.
 *
 * Every pill here answers a question somebody would otherwise open a terminal
 * for: is the timer on, is something running now, is `claude` even installed,
 * what has this cost, is there a version waiting.
 */
export function Header() {
  const { runner, connection, refresh } = useConsole()
  const { theme, toggle } = useTheme()

  return (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-2">
      <span className="text-[0.95rem] font-semibold tracking-tight">
        ticket<span className="text-muted-foreground">-runner</span>
      </span>

      {runner?.version ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="text-muted-foreground font-mono text-xs">v{runner.version}</span>
          </TooltipTrigger>
          <TooltipContent>
            {runner.update
              ? `v${runner.version} — ${runner.update} is waiting, run: ticket-runner update`
              : `v${runner.version} — the version this console is running`}
          </TooltipContent>
        </Tooltip>
      ) : null}

      <div className="flex flex-wrap items-center gap-1.5">
        {runner ? (
          <>
            <Badge variant={runner.timer === "enabled" ? "secondary" : "outline"}>
              <span
                className={cn(
                  "size-1.5 rounded-full",
                  runner.timer === "enabled" ? "bg-tr-green" : "bg-tr-amber"
                )}
              />
              {runner.timer === "enabled"
                ? `timer on · ${every(runner.interval_seconds)}`
                : `timer ${runner.timer}`}
            </Badge>
            {runner.running ? (
              <Badge className="bg-tr-blue/15 text-tr-blue border-tr-blue/30" variant="outline">
                <span className="bg-tr-blue size-1.5 animate-pulse rounded-full" />a run is in
                progress
              </Badge>
            ) : null}
            {!runner.claude ? (
              <Badge className="bg-tr-amber/15 text-tr-amber border-tr-amber/30" variant="outline">
                claude not found
              </Badge>
            ) : null}
            <Badge variant="outline">
              {runner.handled} handled · ${runner.spend}
            </Badge>
            {runner.update ? (
              <Badge className="bg-tr-amber/15 text-tr-amber border-tr-amber/30" variant="outline">
                {runner.update} available · run update
              </Badge>
            ) : null}
          </>
        ) : null}
      </div>

      <span className="flex-1" />

      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "flex items-center gap-1.5 font-mono text-xs",
              connection === "live" ? "text-tr-green" : "text-muted-foreground"
            )}
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                connection === "live" ? "bg-tr-green" : "bg-tr-amber animate-pulse"
              )}
            />
            {connection === "live" ? "live" : connection === "connecting" ? "connecting…" : "reconnecting…"}
          </span>
        </TooltipTrigger>
        <TooltipContent>event stream</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon" onClick={refresh} aria-label="reread the board now">
            <RefreshCw />
          </Button>
        </TooltipTrigger>
        <TooltipContent>reread the board now</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="icon" onClick={toggle} aria-label="switch theme">
            {theme === "dark" ? <Sun /> : <Moon />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{theme === "dark" ? "go light" : "go dark"}</TooltipContent>
      </Tooltip>
    </header>
  )
}
