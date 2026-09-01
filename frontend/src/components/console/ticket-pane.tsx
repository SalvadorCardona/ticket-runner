import * as React from "react"
import { ExternalLink } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useConsole } from "@/hooks/use-console"
import { why } from "@/lib/api"
import { useStickToBottom } from "@/hooks/use-stick-to-bottom"

import { Steps } from "./steps"
import { Turn } from "./turn"

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

/** An instant as this browser would write it, or nothing at all. */
function moment(at?: string): string {
  if (!at) return ""
  const date = new Date(at)
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" })
}

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

/* One ticket's terminal.
 *
 * The console's two halves — a transcript and a field — pointed at a single
 * ticket. What you type is a comment on it, and a comment is already how a
 * ticket is answered: a reply under the question a run asked puts the ticket
 * back in the queue, and one that names the runner asks it for words instead.
 * So there is nothing new to learn here, and nothing kept on the side: the
 * discussion is Notion's, and the same words typed into Notion do the same.
 */
export function TicketPane() {
  const { ticket, talk, mention, ticketSteps, board, tell, rereadTalk, talkLoading } =
    useConsole()
  const [text, setText] = React.useState("")
  const [sending, setSending] = React.useState(false)
  const [problem, setProblem] = React.useState("")
  const view = useStickToBottom<HTMLDivElement>(talk, ticketSteps, ticket?.id)

  const send = async () => {
    if (!text.trim() || !ticket || sending) return
    setSending(true)
    setProblem("")
    try {
      await tell(text)
      setText("")
    } catch (error) {
      setProblem(`not written: ${why(error)}`)
    } finally {
      setSending(false)
    }
  }

  const column = ticket
    ? board.columns.find((item) => item.key === ticket.column)?.name ||
      LABEL[ticket.column] ||
      ticket.column
    : ""

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1 border-b px-3.5 py-2.5">
        <div className="min-w-0 flex-1 max-sm:basis-full">
          <h2 className="text-base font-semibold sm:truncate">
            {ticket ? ticket.title : "No ticket open"}
          </h2>
          <p className="text-muted-foreground mt-0.5 text-xs">
            {ticket
              ? ticket.progress
                ? `${column} · ${ticket.progress}`
                : column
              : "Click a card on the board. What you type here is a comment on that ticket — which is how a ticket is answered."}
          </p>
        </div>
        <div className="flex items-center gap-3 max-sm:w-full">
          {ticket ? (
            <>
              <Away label="Notion" href={ticket.url} />
              {ticket.pull_request ? (
                <Away label="pull request" href={ticket.pull_request} />
              ) : null}
              {ticket.session_link ? <Away label="session" href={ticket.session_link} /> : null}
              <span className="text-muted-foreground font-mono text-xs">#{ticket.short}</span>
            </>
          ) : null}
        </div>
      </div>

      <div ref={view} className="scroll-thin min-h-0 flex-1 space-y-2 overflow-y-auto p-3.5">
        {talk.map((message, index) => (
          <Turn
            key={index}
            role={message.role}
            text={message.text}
            who={[
              message.role === "you" ? "you" : message.role === "error" ? "problem" : "the runner",
              moment(message.at),
            ]
              .filter(Boolean)
              .join(" · ")}
          />
        ))}
        {!talk.length && ticket && !talkLoading ? (
          <p className="text-muted-foreground text-sm">
            Nothing has been said on this ticket yet.
          </p>
        ) : null}
        {/* The steps of a running session are not part of the discussion and are
            not reread with it: they keep scrolling underneath. */}
        <Steps steps={ticketSteps} />
      </div>

      <div className="space-y-2 border-t p-3">
        {ticket ? (
          <p className="text-muted-foreground text-xs">
            a comment on the ticket · an answer to its question runs it again ·{" "}
            <code className="bg-muted rounded px-1 py-0.5 font-mono">{mention}</code> asks it for
            words instead
          </p>
        ) : null}
        {problem ? <p className="text-destructive text-xs">{problem}</p> : null}
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault()
              void send()
            }
          }}
          disabled={!ticket}
          rows={1}
          spellCheck={false}
          autoComplete="off"
          className="max-h-50 min-h-9"
          placeholder="Answer the ticket, or ask it something"
        />
        <div className="flex items-center gap-2">
          <Button onClick={send} disabled={!ticket || sending || !text.trim()}>
            {sending ? "sending…" : "Send"}
          </Button>
          <Button
            variant="outline"
            onClick={rereadTalk}
            disabled={!ticket || talkLoading}
            title="read the discussion again"
          >
            {talkLoading ? "reading…" : "reread"}
          </Button>
        </div>
      </div>
    </div>
  )
}
