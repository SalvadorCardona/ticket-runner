import * as React from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useConsole } from "@/hooks/use-console"
import { useT } from "@/lib/i18n"

import { Eyebrow } from "./frame"
import { Flow, Rich } from "./text"
import { Steps } from "./steps"
import { Line, Transcript } from "./transcript"
import { Turn } from "./turn"

/* A sentence talks to your workspace; a line that starts with `>` runs a
 * ticket-runner command. Both land in the same transcript, because both are
 * things you did to the same machine. */
const isCommand = (text: string) => text.trimStart().startsWith(">")

export function ConsolePane() {
  const { transcript, busy, submit, resetChat, runner } = useConsole()
  const t = useT()
  const [text, setText] = React.useState("")

  const [sending, setSending] = React.useState(false)

  // The field is emptied once the server has taken the line, not before: a
  // message refused — the console restarting, a command it will not run — used
  // to be gone from the field and nowhere else.
  const send = async () => {
    if (!text.trim() || busy || sending) return
    const line = text
    setSending(true)
    try {
      if (await submit(line)) setText((current) => (current === line ? "" : current))
    } finally {
      setSending(false)
    }
  }

  const hint = isCommand(text)
    ? `${t("a ticket-runner command")} · ${(runner?.commands ?? []).join(" · ")}`
    : t("a sentence talks to your workspace · > runs a ticket-runner command")

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Room at the right for the drawer's own close, which floats over this
          corner: a heading that ran under it would be a heading with a cross
          in the middle of it. */}
      <div className="border-b py-2.5 pr-12 pl-3.5">
        <Eyebrow>{t("the workspace")}</Eyebrow>
        <h3 className="mt-1 text-base leading-tight font-semibold tracking-[-0.01em]">
          {t("Talking to your machine")}
        </h3>
        <p className="text-muted-foreground mt-1 text-xs">
          {/* One sentence, one key: split around the `>` it was two halves
              that a translation could not reorder. */}
          <Rich
            text={t(
              "A sentence reaches your repositories and the board; a line that starts with `>` reaches the CLI."
            )}
          />
        </p>
      </div>

      <Transcript>
        {transcript.map((entry) => {
          const id = String(entry.id)
          if (entry.kind === "turn")
            return (
              <Line key={id} id={id} anchor={entry.role === "you"}>
                <Turn role={entry.role} text={entry.text} />
              </Line>
            )
          if (entry.kind === "steps")
            return (
              <Line key={id} id={id}>
                <Steps steps={entry.steps} done={entry.done} />
              </Line>
            )
          if (entry.kind === "note")
            return (
              <Line key={id} id={id}>
                <p className="text-muted-foreground text-xs">{entry.text}</p>
              </Line>
            )
          return (
            <Line key={id} id={id} anchor>
              <div className="bg-card rounded-lg border px-3 py-2">
                <div className="text-muted-foreground mb-1 font-mono text-[0.7rem]">
                  ticket-runner {entry.argv.join(" ")}
                </div>
                <pre className="scroll-thin max-h-96 overflow-auto font-mono text-xs leading-relaxed whitespace-pre-wrap">
                  {entry.lines.map((line, index) => (
                    <React.Fragment key={index}>
                      <Flow text={line} />
                      {"\n"}
                    </React.Fragment>
                  ))}
                  {entry.code ? `\n[${t("exit {{code}}", { code: String(entry.code) })}]` : ""}
                </pre>
              </div>
            </Line>
          )
        })}
      </Transcript>

      <div className="flex flex-col gap-2 border-t p-3">
        <p className="text-muted-foreground text-xs">{hint}</p>
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault()
              void send()
            }
          }}
          rows={1}
          spellCheck={false}
          autoComplete="off"
          className={
            "max-h-50 min-h-9 " + (isCommand(text) ? "font-mono text-tr-amber" : "")
          }
          placeholder={t("Ask the workspace, or type >status")}
        />
        <div className="flex items-center gap-2">
          <Button onClick={() => void send()} disabled={busy || sending || !text.trim()}>
            {busy ? t("working…") : t("Send")}
          </Button>
          <Button variant="outline" onClick={resetChat} title={t("start a new conversation")}>
            {t("new conversation")}
          </Button>
          <span className="flex-1" />
          <span className="text-muted-foreground truncate font-mono text-xs">
            {runner?.chat.session_id
              ? `${t("{{count}} turn(s)", { count: String(runner.chat.turns) })} · ${runner.chat.resume_command}`
              : t("no conversation yet")}
          </span>
        </div>
      </div>
    </div>
  )
}
