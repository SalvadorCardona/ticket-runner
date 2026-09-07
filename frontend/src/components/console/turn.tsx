import { Message, MessageContent, MessageFooter, MessageHeader } from "@/components/ui/message"
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
 * palette is: a problem reads red, the workspace reads as a card.
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
  const mine = role === "you"
  return (
    <Message align={mine ? "end" : "start"} className={className}>
      <MessageContent className="max-w-[92%]">
        <MessageHeader
          className={cn("uppercase tracking-wide", role === "error" && "text-destructive")}
        >
          {who ?? WHO[role] ?? role}
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
        {when ? <MessageFooter>{when}</MessageFooter> : null}
      </MessageContent>
    </Message>
  )
}
