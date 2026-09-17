import { Bubble, BubbleContent } from "@/components/ui/bubble"
import { Message, MessageContent, MessageHeader } from "@/components/ui/message"
import { useT } from "@/lib/i18n"
import type { Role } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Markdown } from "./markdown"

const WHO: Record<Role, string> = {
  you: "you",
  workspace: "workspace",
  error: "problem",
  command: "command",
}

/** The surface a turn is said on, in shadcn's own palette. */
const SURFACE: Record<Role, "tinted" | "outline" | "destructive"> = {
  you: "tinted",
  workspace: "outline",
  error: "destructive",
  command: "outline",
}

/* One thing that was said, by you or by the other side.
 *
 * shadcn's `Message` lays it out — yours against the right edge, theirs against
 * the left — and `Bubble` draws the surface it is said on, so the palette is the
 * one the components already carry: a problem reads red, the workspace reads as
 * a card, and what you said is tinted with the accent so a transcript can be
 * skimmed for your own turns.
 *
 * What is inside is markdown, because both sides write markdown: a session
 * answers in headings and lists and fenced code, and a bubble that showed the
 * source of that would be asking a reader to parse it themselves.
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
      <MessageContent>
        <MessageHeader
          className={cn(
            "font-mono text-[0.65rem] font-semibold tracking-[0.14em] uppercase",
            role === "error" && "text-destructive"
          )}
        >
          {who ?? t(WHO[role] ?? role)}
          {when ? <span className="font-normal normal-case">{` · ${when}`}</span> : null}
        </MessageHeader>
        <Bubble
          variant={SURFACE[role] ?? "outline"}
          align={mine ? "end" : "start"}
          className="max-w-[92%]"
        >
          <BubbleContent>
            <Markdown text={text} />
          </BubbleContent>
        </Bubble>
      </MessageContent>
    </Message>
  )
}
