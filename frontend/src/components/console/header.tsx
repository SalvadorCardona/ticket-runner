import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useConsole } from "@/hooks/use-console"
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
export function Header({ title }: { title: string }) {
  const { runner } = useConsole()

  return (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-3 py-2">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-1 !h-4" />
      <span className="text-sm font-semibold tracking-tight">{title}</span>

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
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge
                    className="bg-tr-amber/15 text-tr-amber border-tr-amber/30"
                    variant="outline"
                  >
                    {runner.update} available · run update
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>
                  v{runner.version} — {runner.update} is waiting, run: ticket-runner update
                </TooltipContent>
              </Tooltip>
            ) : null}
          </>
        ) : null}
      </div>
    </header>
  )
}
