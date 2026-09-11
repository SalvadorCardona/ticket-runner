import * as React from "react"
import { CalendarClock, RefreshCw } from "lucide-react"
import { Link } from "react-resource-view"

import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { t, useT } from "@/lib/i18n"
import type { Schedule, Schedules } from "@/lib/types"
import { cn } from "@/lib/utils"
import { ticketHref } from "@/resources/tickets"

import { Eyebrow, Fact, Facts, PageHead, Panel } from "./frame"
import { Chip } from "./ticket-bits"

/* What comes back on its own.
 *
 * The Schedules database, read the way `ticket-runner schedules` reads it: what
 * repeats, when the next one is due, and how the last one went. Nothing is
 * written from here — a schedule is a Notion page, and the way to change one is
 * to open it, which is what the link on its name is for.
 *
 * The page asks the server when it is opened rather than living on the stream:
 * a schedule moves four times a day at the very most, and this is the only pane
 * whose data nothing else on the screen already holds.
 */

/** "2026-09-14 09:00 — in 6 days", the way the CLI says a date. */
function when(at: string): string {
  const moment = new Date(at)
  if (Number.isNaN(moment.getTime())) return at
  const said = at.replace("T", " ").slice(0, 16)
  const hours = (moment.getTime() - Date.now()) / 3_600_000
  if (hours < 0) return `${said} — ${t("overdue")}`
  if (hours < 48) return `${said} — ${t("in {{count}} h", { count: String(Math.round(hours)) })}`
  return `${said} — ${t("in {{count}} days", { count: String(Math.round(hours / 24)) })}`
}

/** The rhythm, in the words the row is written in: "Weekly · Monday 09:00". */
function rhythm(schedule: Schedule): string {
  const clock = [schedule.day, schedule.at].filter(Boolean).join(" ")
  // The cadence is the row's own word, as Notion holds it; only its absence is
  // the console's to say.
  return [schedule.cadence || t("no cadence"), clock].filter(Boolean).join(" · ")
}

function Row({ schedule }: { schedule: Schedule }) {
  const t = useT()
  return (
    <Panel
      eyebrow={rhythm(schedule)}
      title={
        <a
          href={schedule.url}
          target="_blank"
          rel="noreferrer noopener"
          className="underline-offset-2 hover:underline"
        >
          {schedule.name}
        </a>
      }
      action={
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
            schedule.active
              ? "border-tr-green/30 bg-tr-green/10 text-tr-green"
              : "text-muted-foreground"
          )}
        >
          <span
            className={cn(
              "size-1.5 rounded-full",
              schedule.active ? "bg-tr-green" : "bg-muted-foreground"
            )}
          />
          {schedule.active ? t("on") : t("unticked")}
        </span>
      }
    >
      {/* A schedule nobody can read holds nobody up — the pass steps over it —
          so it says what is wrong with it instead of a date it does not have. */}
      {schedule.problem ? (
        <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-lg border px-3 py-2 text-xs">
          {schedule.problem}
        </p>
      ) : (
        <Facts>
          <Fact label={t("next")}>
            <span className="font-mono text-xs">
              {!schedule.active
                ? t("nothing is born")
                : schedule.next
                  ? when(schedule.next)
                  : t("at the next pass")}
            </span>
          </Fact>
          <Fact label={t("last")}>
            <span className="font-mono text-xs">
              {schedule.last ? schedule.last.replace("T", " ").slice(0, 16) : t("never")}
            </span>
          </Fact>
        </Facts>
      )}

      {schedule.project || schedule.model || schedule.priority || schedule.ticket ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {schedule.project ? <Chip>{schedule.project}</Chip> : null}
          {schedule.model ? <Chip>{schedule.model}</Chip> : null}
          {schedule.priority ? <Chip>{schedule.priority}</Chip> : null}
          {schedule.ticket ? (
            <Link
              to={ticketHref(schedule.ticket)}
              className="text-muted-foreground hover:text-foreground text-xs underline-offset-2 hover:underline"
            >
              {t("its last ticket")}
            </Link>
          ) : null}
        </div>
      ) : null}
    </Panel>
  )
}

export function SchedulesPane() {
  const t = useT()
  const [drawn, setDrawn] = React.useState<Schedules | null>(null)
  const [problem, setProblem] = React.useState("")

  const load = React.useCallback(async () => {
    try {
      setDrawn(await api.schedules())
      setProblem("")
    } catch (error) {
      setProblem(why(error))
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  const rows = drawn?.schedules ?? []
  const active = rows.filter((schedule) => schedule.active && !schedule.problem).length

  return (
    <div className="p-3.5 sm:p-5">
      <PageHead
        crumbs={[t("workspace"), t("schedules")]}
        title={t("What comes back on its own.")}
        blurb={t(
          "A row says what to make and how often; when the moment comes the runner writes the ticket into the ready column and steps back."
        )}
        action={
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw />
            {t("Reread")}
          </Button>
        }
      >
        <span className="text-muted-foreground inline-flex items-center gap-1.5 font-mono text-[0.7rem]">
          <CalendarClock className="size-3.5" />
          {rows.length
            ? t("{{count}} of {{total}} on", {
                count: String(active),
                total: String(rows.length),
              })
            : t("nothing yet")}
        </span>
      </PageHead>

      {/* Three ways this page has nothing to show, and they are three different
          things to do about it: the token failed, the workspace has no such
          database, or the database is there and empty. */}
      {problem ? (
        <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-xl border px-4 py-3 text-sm">
          {problem}
        </p>
      ) : !drawn ? (
        <p className="text-muted-foreground text-sm">{t("Reading the schedules…")}</p>
      ) : !drawn.database ? (
        <p className="text-muted-foreground rounded-xl border border-dashed px-4 py-10 text-center text-sm">
          {t("Nothing repeats here — this workspace has no “{{page}}” page.", {
            page: drawn.page,
          })}
          <br />
          <code className="font-mono text-xs">ticket-runner init &lt;page-url&gt;</code>{" "}
          {t("builds it.")}
        </p>
      ) : !rows.length ? (
        <p className="text-muted-foreground rounded-xl border border-dashed px-4 py-10 text-center text-sm">
          {t(
            "Nothing repeats here yet — the “{{page}}” database is empty. A row in it is a ticket that comes back.",
            { page: drawn.page }
          )}
        </p>
      ) : (
        <div className="space-y-3">
          {rows.map((schedule) => (
            <Row key={schedule.id} schedule={schedule} />
          ))}
        </div>
      )}

      {/* One switch turns the whole calendar off, and a page of ticked rows
          that never fire is the thing it would otherwise be read as. */}
      {drawn && drawn.database && !drawn.enabled ? (
        <p className="text-tr-amber mt-4 text-xs">
          <Eyebrow className="text-tr-amber">runner.schedule = false</Eyebrow> —{" "}
          {t("none of this runs.")}
        </p>
      ) : null}
    </div>
  )
}
