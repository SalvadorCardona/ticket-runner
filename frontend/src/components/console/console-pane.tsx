import * as React from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useConsole } from "@/hooks/use-console"
import { useStickToBottom } from "@/hooks/use-stick-to-bottom"

import { Flow } from "./text"
import { Steps } from "./steps"
import { Turn } from "./turn"

/* A sentence talks to your workspace; a line that starts with `>` runs a
 * ticket-runner command. Both land in the same transcript, because both are
 * things you did to the same machine. */
const isCommand = (text: string) => text.trimStart().startsWith(">")

export function ConsolePane() {
  const { transcript, busy, submit, resetChat, runner } = useConsole()
  const [text, setText] = React.useState("")
  const view = useStickToBottom<HTMLDivElement>(transcript)

  const send = () => {
    if (!text.trim() || busy) return
    const line = text
    setText("")
    void submit(line)
  }

  const hint = isCommand(text)
    ? `a ticket-runner command · ${(runner?.commands ?? []).join(" · ")}`
    : "a sentence talks to your workspace · > runs a ticket-runner command"

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={view} className="scroll-thin min-h-0 flex-1 space-y-2 overflow-y-auto p-3.5">
        {transcript.map((entry) => {
          if (entry.kind === "turn")
            return <Turn key={entry.id} role={entry.role} text={entry.text} />
          if (entry.kind === "steps")
            return <Steps key={entry.id} steps={entry.steps} done={entry.done} />
          if (entry.kind === "note")
            return (
              <p key={entry.id} className="text-muted-foreground text-xs">
                {entry.text}
              </p>
            )
          return (
            <div key={entry.id} className="bg-card rounded-lg border px-3 py-2">
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
                {entry.code ? `\n[exit ${entry.code}]` : ""}
              </pre>
            </div>
          )
        })}
      </div>

      <div className="space-y-2 border-t p-3">
        <p className="text-muted-foreground text-xs">{hint}</p>
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault()
              send()
            }
          }}
          rows={1}
          spellCheck={false}
          autoComplete="off"
          className={
            "max-h-50 min-h-9 " + (isCommand(text) ? "font-mono text-tr-amber" : "")
          }
          placeholder="Ask the workspace, or type >status"
        />
        <div className="flex items-center gap-2">
          <Button onClick={send} disabled={busy || !text.trim()}>
            {busy ? "working…" : "Send"}
          </Button>
          <Button variant="outline" onClick={resetChat} title="start a new conversation">
            new conversation
          </Button>
          <span className="flex-1" />
          <span className="text-muted-foreground truncate font-mono text-xs">
            {runner?.chat.session_id
              ? `${runner.chat.turns} turn(s) · ${runner.chat.resume_command}`
              : "no conversation yet"}
          </span>
        </div>
      </div>
    </div>
  )
}
