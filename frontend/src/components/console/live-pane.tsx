import { Activity, Gauge, Timer } from "lucide-react"

import { useConsole } from "@/hooks/use-console"
import { cn } from "@/lib/utils"

import { Eyebrow, PageHead, Panel } from "./frame"
import { Steps } from "./steps"

/* What the running tickets are doing, straight from their session logs — no
 * Notion in the way. The newest session to say something is at the top.
 *
 * Above them, the three numbers somebody opens this page for: how many
 * sessions are writing, how often the timer comes round, what the runner has
 * cost so far. They are read off the state the header already has — this page
 * asks the server for nothing of its own.
 */

/** An interval, as somebody would say it out loud. */
function every(seconds: number): string {
  if (!seconds) return "—"
  return seconds < 120 ? `${seconds}s` : `${Math.round(seconds / 60)} min`
}

function Tile({
  icon: Icon,
  label,
  value,
  note,
  tone,
}: {
  icon: typeof Activity
  label: string
  value: string
  note: string
  tone?: string
}) {
  return (
    <div className="bg-card rounded-xl border px-4 py-3.5">
      <div className="flex items-center gap-1.5">
        <Icon className="text-muted-foreground size-3.5" />
        <Eyebrow>{label}</Eyebrow>
      </div>
      <p
        className={cn(
          "mt-2 text-3xl leading-none font-bold tracking-[-0.04em] tabular-nums",
          tone
        )}
      >
        {value}
      </p>
      <p className="text-muted-foreground mt-2 font-mono text-[0.7rem]">{note}</p>
    </div>
  )
}

export function LivePane() {
  const { sessions, runner, board } = useConsole()
  const running = board.tickets.filter((item) => item.column === "running").length

  return (
    <div className="p-3.5 sm:p-5">
      <PageHead
        crumbs={["workspace", "live"]}
        title="See the work happen."
        blurb="What the running tickets are doing, straight from their session logs — no Notion in the way."
        action={
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
              sessions.length
                ? "border-tr-green/30 bg-tr-green/10 text-tr-green"
                : "text-muted-foreground"
            )}
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                sessions.length ? "bg-tr-green animate-pulse" : "bg-muted-foreground"
              )}
            />
            {sessions.length ? "writing now" : "quiet"}
          </span>
        }
      />

      <div className="mb-5 grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(11rem,1fr))]">
        <Tile
          icon={Activity}
          label="sessions"
          value={String(sessions.length)}
          note={running ? `${running} ticket(s) in progress` : "nothing in progress"}
          tone={sessions.length ? "text-tr-green" : undefined}
        />
        <Tile
          icon={Timer}
          label="timer"
          value={runner?.timer === "enabled" ? every(runner.interval_seconds) : "off"}
          note={runner?.timer === "enabled" ? "between two runs" : `timer ${runner?.timer ?? "—"}`}
          tone={runner?.timer === "enabled" ? undefined : "text-tr-amber"}
        />
        <Tile
          icon={Gauge}
          label="handled"
          value={String(runner?.handled ?? 0)}
          note={`$${runner?.spend ?? 0} spent so far`}
        />
      </div>

      {sessions.length ? (
        <div className="space-y-3">
          {sessions.map((session) => (
            <Panel
              key={session.source}
              eyebrow="session"
              title={<span className="font-mono text-sm">{session.source}</span>}
              action={
                <span className="text-muted-foreground font-mono text-[0.7rem]">
                  {session.steps.length} step(s)
                </span>
              }
            >
              <Steps steps={session.steps} className="max-h-72" />
            </Panel>
          ))}
        </div>
      ) : (
        <p className="text-muted-foreground rounded-xl border border-dashed px-4 py-10 text-center text-sm">
          Nothing is running. A session that starts writes here as it works.
        </p>
      )}
    </div>
  )
}
