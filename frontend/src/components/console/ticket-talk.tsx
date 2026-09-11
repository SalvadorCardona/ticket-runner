import * as React from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useConsole } from "@/hooks/use-console"
import { why } from "@/lib/api"
import { currentLanguage, t as translate, useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

import { Eyebrow } from "./frame"
import { Steps } from "./steps"
import { Line, Transcript } from "./transcript"
import { Turn } from "./turn"

/** An instant as the language the console is in would write it, or nothing at all. */
function moment(at?: string): string {
  if (!at) return ""
  const date = new Date(at)
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleString(currentLanguage(), { dateStyle: "short", timeStyle: "short" })
}

/* One ticket's terminal.
 *
 * A transcript and a field, pointed at a single ticket. What you type is a
 * comment on it, and a comment is already how a ticket is answered: a reply
 * under the question a run asked puts the ticket back in the queue, and one
 * that names the runner asks it for words instead. So there is nothing new to
 * learn here, and nothing kept on the side: the discussion is Notion's, and
 * the same words typed into Notion do the same.
 */
export function TicketTalk({
  className,
  bounded = false,
}: {
  className?: string
  /** Given a height of its own rather than the pane's, for when it sits under the page. */
  bounded?: boolean
}) {
  const { ticket, talk, mention, ticketSteps, tell, rereadTalk, talkLoading } = useConsole()
  const t = useT()
  const [text, setText] = React.useState("")
  const [sending, setSending] = React.useState(false)
  const [problem, setProblem] = React.useState("")

  const send = async () => {
    if (!text.trim() || !ticket || sending) return
    setSending(true)
    setProblem("")
    try {
      await tell(text)
      setText("")
    } catch (error) {
      setProblem(translate("not written: {{why}}", { why: why(error) }))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className={cn("flex min-h-0 flex-col", bounded ? "h-[70svh]" : "h-full", className)}>
      <div className="border-b px-3.5 py-2.5">
        <Eyebrow>{t("the ticket")}</Eyebrow>
        <h3 className="mt-1 text-base leading-tight font-semibold tracking-[-0.01em]">
          {ticket ? (
            <>
              {t("Talking to")} <span className="text-primary font-mono">#{ticket.short}</span>
            </>
          ) : (
            t("No ticket open")
          )}
        </h3>
        <p className="text-muted-foreground mt-1 text-xs">
          {ticket
            ? t("Everything said on the ticket, oldest first. What you type is a comment on it.")
            : t("Open a ticket from the board.")}
        </p>
      </div>

      <Transcript>
        {talk.map((message, index) => (
          <Line key={index} id={`talk-${index}`} anchor={message.role === "you"}>
            <Turn
              role={message.role}
              text={message.text}
              who={
                message.role === "you"
                  ? t("you")
                  : message.role === "error"
                    ? t("problem")
                    : t("the runner")
              }
              when={moment(message.at)}
            />
          </Line>
        ))}
        {!talk.length && ticket && !talkLoading ? (
          <Line id="talk-none">
            <p className="text-muted-foreground text-sm">
              {t("Nothing has been said on this ticket yet.")}
            </p>
          </Line>
        ) : null}
        {talkLoading && !talk.length ? (
          <Line id="talk-loading">
            <p className="text-muted-foreground text-sm">{t("reading the discussion…")}</p>
          </Line>
        ) : null}
        {/* The steps of a running session are not part of the discussion and
            are not reread with it: they keep scrolling underneath. */}
        {ticketSteps.length ? (
          <Line id="talk-steps">
            <Steps steps={ticketSteps} />
          </Line>
        ) : null}
      </Transcript>

      <div className="flex flex-col gap-2 border-t p-3">
        {ticket ? (
          <p className="text-muted-foreground text-xs">
            {t("an answer to its question runs it again")} ·{" "}
            <code className="bg-muted rounded px-1 py-0.5 font-mono">{mention}</code>{" "}
            {t("asks it for words instead")}
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
          placeholder={t("Answer the ticket, or ask it something")}
        />
        <div className="flex items-center gap-2">
          <Button onClick={send} disabled={!ticket || sending || !text.trim()}>
            {sending ? t("sending…") : t("Send")}
          </Button>
          <Button
            variant="outline"
            onClick={rereadTalk}
            disabled={!ticket || talkLoading}
            title={t("read the discussion again")}
          >
            {talkLoading ? t("reading…") : t("reread")}
          </Button>
        </div>
      </div>
    </div>
  )
}
