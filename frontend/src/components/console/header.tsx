import type * as React from "react"
import { PanelRightClose, PanelRightOpen } from "lucide-react"

import { Button } from "@/components/ui/button"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useConsole } from "@/hooks/use-console"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

import { Eyebrow } from "./frame"
import { LanguagePicker } from "./language-picker"

/** An interval, as somebody would say it out loud. */
function every(seconds: number): string {
  if (!seconds) return ""
  return seconds < 120 ? `${seconds}s` : `${Math.round(seconds / 60)} min`
}

/* What the runner is doing, above everything else.
 *
 * Every pill here answers a question somebody would otherwise open a terminal
 * for: is the timer on, is something running now, is `claude` even installed,
 * what has this cost, is there a version waiting. At the right edge, the
 * language the console is in and the switch that folds the second column away
 * — a board of seven columns wants the width more often than not.
 *
 * The bar names where you are and nothing more: the page under it opens with
 * its own heading, and a title said twice is a title read neither time.
 */

/** One reading of the runner's state: a dot, a word, and the colour of the news. */
function Pill({
  tone,
  dot,
  pulse = false,
  children,
}: {
  tone?: "green" | "amber" | "blue"
  dot?: boolean
  pulse?: boolean
  children: React.ReactNode
}) {
  const skin = {
    green: "border-tr-green/30 bg-tr-green/10 text-tr-green",
    amber: "border-tr-amber/30 bg-tr-amber/10 text-tr-amber",
    blue: "border-tr-blue/30 bg-tr-blue/10 text-tr-blue",
  }
  const seed = {
    green: "bg-tr-green",
    amber: "bg-tr-amber",
    blue: "bg-tr-blue",
  }
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium whitespace-nowrap",
        tone ? skin[tone] : "text-muted-foreground"
      )}
    >
      {dot ? (
        <span
          className={cn(
            "size-1.5 shrink-0 rounded-full",
            tone ? seed[tone] : "bg-muted-foreground",
            pulse && "animate-pulse"
          )}
        />
      ) : null}
      {children}
    </span>
  )
}

export function Header({
  crumbs,
  aside,
  asideLabel,
  onToggleAside,
}: {
  /** Where you are, said as a path: the sidebar's entry, then what is open under it. */
  crumbs: string[]
  aside: boolean
  asideLabel: string
  onToggleAside: () => void
}) {
  const { runner } = useConsole()
  const t = useT()
  const fold = aside
    ? t("hide {{pane}}", { pane: asideLabel })
    : t("show {{pane}}", { pane: asideLabel })

  return (
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-3 py-2">
      <SidebarTrigger className="-ml-1" />
      <div className="min-w-0 truncate">
        <Eyebrow>
          {crumbs.map((part, index) => (
            <span key={part}>
              {index ? <span className="text-border mx-1.5">/</span> : null}
              {part}
            </span>
          ))}
        </Eyebrow>
      </div>

      <span className="flex-1" />

      <div className="flex flex-wrap items-center gap-1.5">
        {runner ? (
          <>
            <Pill tone={runner.timer === "enabled" ? "green" : "amber"} dot>
              {/* systemd's own word for anything but "on": it is the word
                  `systemctl` would print, and translating it would be
                  translating a state nobody but systemd names. */}
              {runner.timer === "enabled"
                ? `${t("timer on")} · ${every(runner.interval_seconds)}`
                : t("timer {{state}}", { state: runner.timer })}
            </Pill>
            {runner.running ? (
              <Pill tone="blue" dot pulse>
                {t("a run is in progress")}
              </Pill>
            ) : null}
            {/* A timer that is on and a board that does not move: without this
                pill, the only honest reading of that is "it is broken". */}
            {runner.credits ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span>
                    <Pill tone="amber" dot>
                      {t("out of credit · back at {{at}}", { at: runner.credits_at })}
                    </Pill>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  {t(
                    "The subscription's window is spent. Tickets stay where they are and the first run after {{at}} takes them again.",
                    { at: runner.credits_at }
                  )}
                </TooltipContent>
              </Tooltip>
            ) : null}
            {!runner.claude ? <Pill tone="amber">{t("claude not found")}</Pill> : null}
            <Pill>
              <span className="font-mono tabular-nums">{runner.handled}</span> {t("handled")} ·{" "}
              <span className="font-mono tabular-nums">${runner.spend}</span>
            </Pill>
            {runner.update ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span>
                    <Pill tone="amber">
                      {t("{{version}} available · run update", { version: runner.update })}
                    </Pill>
                  </span>
                </TooltipTrigger>
                <TooltipContent>
                  {t("v{{version}} — {{waiting}} is waiting, run: ticket-runner update", {
                    version: runner.version,
                    waiting: runner.update,
                  })}
                </TooltipContent>
              </Tooltip>
            ) : null}
          </>
        ) : null}
      </div>

      <LanguagePicker />

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground max-[860px]:hidden"
            onClick={onToggleAside}
            aria-label={fold}
          >
            {aside ? <PanelRightClose /> : <PanelRightOpen />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{fold}</TooltipContent>
      </Tooltip>
    </header>
  )
}
