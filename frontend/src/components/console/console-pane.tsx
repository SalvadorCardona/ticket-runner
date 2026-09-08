import * as React from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useConsole } from "@/hooks/use-console"

import { Eyebrow } from "./frame"
import { Flow } from "./text"
import { Steps } from "./steps"
import { Line, Transcript } from "./transcript"
import { Turn } from "./turn"

/* A sentence talks to your workspace; a line that starts with `>` runs a
 * ticket-runner command. Both land in the same transcript, because both are
 * things you did to the same machine. */
const isCommand = (text: string) => text.trimStart().startsWith(">")

export function ConsolePane() {
  const { transcript, busy, submit, resetChat, runner } = useConsole()
  const [text, setText] = React.useState("")

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
      <div className="border-b px-3.5 py-2.5">
        <Eyebrow>the workspace</Eyebrow>
        <h3 className="mt-1 text-base leading-tight font-semibold tracking-[-0.01em]">
          Talking to your machine
        </h3>
        <p className="text-muted-foreground mt-1 text-xs">
          A sentence reaches your repositories and the board; a line that starts with{" "}
          <code className="bg-muted rounded px-1 py-0.5 font-mono">&gt;</code> reaches the CLI.
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
                  {entry.code ? `\n[exit ${entry.code}]` : ""}
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
