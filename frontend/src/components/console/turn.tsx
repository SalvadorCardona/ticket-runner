import { Message, MessageContent, MessageHeader } from "@/components/ui/message"
import { useT } from "@/lib/i18n"
import type { Role } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Flow } from "./text"

const WHO: Record<Role, string> = {
  you: "you",
  workspace: "workspace",
  error: "problem",
  command: "command",
}

/* One thing that was said, by you or by the other side.
 *
 * shadcn's `Message` lays it out — yours against the right edge, theirs
 * against the left — and the bubble inside is the console's own, because the
 * palette is: a problem reads red, the workspace reads as a card, and what you
 * said carries the accent so a transcript can be skimmed for your own turns.
 *
 * Who said it and when are one line, set in the mono face: they are a stamp on
 * the message, not a sentence in it.
 */
export function Turn({
  role,
  text,
  who,
  when,
  className,
}: {
  role: Role
  text: string
  who?: string
  when?: string
  className?: string
}) {
  const t = useT()
  const mine = role === "you"
  return (
    <Message align={mine ? "end" : "start"} className={className}>
      <MessageContent className="max-w-[92%]">
        <MessageHeader
          className={cn(
            "font-mono text-[0.65rem] font-semibold tracking-[0.14em] uppercase",
            role === "error" && "text-destructive"
          )}
        >
          {who ?? t(WHO[role] ?? role)}
          {when ? <span className="font-normal normal-case">{` · ${when}`}</span> : null}
        </MessageHeader>
        <div
          className={cn(
            "rounded-lg border px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap",
            mine && "bg-primary/10 border-primary/25",
            role === "workspace" && "bg-card",
            role === "error" && "bg-destructive/10 border-destructive/30"
          )}
        >
          <Flow text={text} />
        </div>
      </MessageContent>
    </Message>
  )
}
