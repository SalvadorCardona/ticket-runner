import * as React from "react"
import { ChevronDown, ExternalLink, Terminal } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { useConsole } from "@/hooks/use-console"
import { why } from "@/lib/api"
import type { ColumnKey, Ticket } from "@/lib/types"
import { cn } from "@/lib/utils"

const LABEL: Record<string, string> = {
  ready: "Ready",
  running: "In progress",
  review: "In review",
  validated: "Validated",
  blocked: "Blocked",
  failed: "Failed",
  done: "Done",
  other: "Elsewhere",
}

/* Done is real but it is not news: it would be most of the board within a week,
 * and push everything worth looking at below the fold. */
const ORDER: ColumnKey[] = [
  "ready",
  "running",
  "review",
  "validated",
  "blocked",
  "failed",
  "other",
]

const EDGE: Record<string, string> = {
  ready: "border-l-tr-green",
  running: "border-l-tr-blue",
  review: "border-l-tr-violet",
  validated: "border-l-tr-pink",
  blocked: "border-l-tr-amber",
  failed: "border-l-tr-red",
}

/** The project picker's "no project" answer. Radix has no empty-string value. */
const NO_PROJECT = "—"

function Away({ label, href }: { label: string; href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline-offset-2 hover:underline"
    >
      {label}
      <ExternalLink className="size-3" />
    </a>
  )
}

function TicketCard({ ticket }: { ticket: Ticket }) {
  const { openTicket, move, board } = useConsole()

  // The card is the way into the ticket's terminal — except where it already
  // carries a gesture of its own: a click on "validate" is not a click on the
  // card it happens to sit in.
  const enter = (event: React.MouseEvent) => {
    if (!(event.target as HTMLElement).closest("a, button")) openTicket(ticket)
  }

  return (
    <div
      role="button"
      tabIndex={0}
      title="open this ticket’s terminal"
      onClick={enter}
      onKeyDown={(event) => {
        if (event.key === "Enter" && event.target === event.currentTarget) openTicket(ticket)
      }}
      className={cn(
        "bg-card hover:border-ring/40 focus-visible:ring-ring/50 cursor-pointer rounded-lg border border-l-3 p-3 text-left transition-colors focus-visible:ring-[3px] focus-visible:outline-none",
        EDGE[ticket.column] ?? "border-l-border"
      )}
    >
      <div className="text-[0.93rem] leading-snug font-semibold">{ticket.title}</div>

      <div className="mt-1.5 flex flex-wrap gap-1">
        <Badge variant="secondary" className="font-normal">
          {ticket.project || "no project — document"}
        </Badge>
        {ticket.priority ? (
          <Badge variant="outline" className="font-normal">
            {ticket.priority}
          </Badge>
        ) : null}
        {ticket.model ? (
          <Badge variant="outline" className="font-normal">
            {ticket.model}
          </Badge>
        ) : null}
        {ticket.scheduled ? (
          <Badge variant="outline" className="font-normal">
            ⏱ {ticket.scheduled.replace("T", " ")}
          </Badge>
        ) : null}
        {typeof ticket.cost === "number" && ticket.cost ? (
          <Badge variant="outline" className="font-normal">
            ${ticket.cost.toFixed(2)}
          </Badge>
        ) : null}
      </div>

      {ticket.progress ? (
        <p className="text-muted-foreground mt-2 line-clamp-3 text-xs leading-relaxed">
          {ticket.progress}
        </p>
      ) : null}

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {/* The whole card opens it too; this is the one you can reach with a
            keyboard and the one that says the terminal is there at all. */}
        <Button
          variant="ghost"
          size="xs"
          className="text-muted-foreground hover:text-foreground -ml-2"
          onClick={() => openTicket(ticket)}
        >
          <Terminal />
          terminal
        </Button>
        <Away label="Notion" href={ticket.url} />
        {ticket.pull_request ? <Away label="pull request" href={ticket.pull_request} /> : null}
        {ticket.session_link ? <Away label="session" href={ticket.session_link} /> : null}

        {ticket.column !== "ready" && ticket.column !== "running" ? (
          <Button
            variant="ghost"
            size="xs"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => move(ticket, "ready")}
          >
            {ticket.column === "review" ? "run again" : "make ready"}
          </Button>
        ) : null}
        {/* Validating is the gesture the runner acts on — it merges the pull
            request, or publishes what the ticket holds — where "done" only
            files the ticket away yourself. Offered only on a board that has
            the column. */}
        {ticket.column === "review" && board.validate ? (
          <Button
            variant="ghost"
            size="xs"
            className="text-tr-pink hover:text-tr-pink"
            onClick={() => move(ticket, "validated")}
          >
            validate
          </Button>
        ) : null}
        {ticket.column === "review" ? (
          <Button
            variant="ghost"
            size="xs"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => move(ticket, "done")}
          >
            done
          </Button>
        ) : null}
        {ticket.column === "ready" ? (
          <Button
            variant="ghost"
            size="xs"
            className="text-muted-foreground hover:text-foreground"
            onClick={() => move(ticket, "blocked")}
          >
            hold
          </Button>
        ) : null}
      </div>
    </div>
  )
}

function Compose() {
  const { projects, createTicket, say } = useConsole()
  const [open, setOpen] = React.useState(false)
  const [title, setTitle] = React.useState("")
  const [body, setBody] = React.useState("")
  const [project, setProject] = React.useState(NO_PROJECT)
  const [ready, setReady] = React.useState(true)
  const [saving, setSaving] = React.useState(false)

  const create = async () => {
    if (!title.trim() || saving) return
    setSaving(true)
    try {
      await createTicket({
        title: title.trim(),
        body,
        project: project === NO_PROJECT ? "" : project,
        ready,
      })
      setTitle("")
      setBody("")
      setOpen(false)
    } catch (error) {
      say("error", `could not create the ticket: ${why(error)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-card mb-4 rounded-xl border p-3">
      <Input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Enter") void create()
        }}
        autoComplete="off"
        placeholder="New ticket — what has to be done, in one line"
      />
      {open ? (
        <div className="mt-2.5 space-y-2.5">
          <Textarea
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={4}
            placeholder="The brief: what must change, where, and how you will know it is done."
          />
          <div className="flex flex-wrap items-center gap-3">
            <Select value={project} onValueChange={setProject}>
              <SelectTrigger className="min-w-56">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_PROJECT}>no project — a document</SelectItem>
                {projects.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.name} — {item.kind}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Label className="cursor-pointer">
              <Checkbox
                checked={ready}
                onCheckedChange={(value) => setReady(value === true)}
              />
              ready to run
            </Label>
            <span className="flex-1" />
            <Button onClick={create} disabled={saving || !title.trim()}>
              {saving ? "creating…" : "Create"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export function BoardPane() {
  const { board } = useConsole()

  const groups = new Map<string, Ticket[]>()
  for (const ticket of board.tickets) {
    const bucket = groups.get(ticket.column) ?? []
    bucket.push(ticket)
    groups.set(ticket.column, bucket)
  }
  const done = (groups.get("done") ?? []).length

  return (
    <div className="p-3.5">
      <Compose />

      <div className="flex flex-col gap-5">
        {ORDER.map((key) => {
          const tickets = groups.get(key) ?? []
          if (!tickets.length && key !== "ready") return null
          const name =
            board.columns.find((column) => column.key === key)?.name || LABEL[key] || key
          return (
            <section key={key}>
              <h2 className="text-muted-foreground mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide uppercase">
                <ChevronDown className="size-3.5" />
                {name}
                <span className="bg-muted text-muted-foreground rounded-full px-1.5 py-0.5 text-[0.7rem]">
                  {tickets.length}
                </span>
              </h2>
              {tickets.length ? (
                <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(15rem,1fr))]">
                  {tickets.map((ticket) => (
                    <TicketCard key={ticket.id} ticket={ticket} />
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">
                  Nothing ready. Write a ticket above.
                </p>
              )}
            </section>
          )
        })}
        {done ? (
          <p className="text-muted-foreground text-sm">{done} done, kept in Notion.</p>
        ) : null}
      </div>
    </div>
  )
}
