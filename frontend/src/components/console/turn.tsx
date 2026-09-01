import type { Role } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Flow } from "./text"

const WHO: Record<Role, string> = {
  you: "you",
  workspace: "workspace",
  error: "problem",
  command: "command",
}

/** One thing that was said, by you or by the workspace. */
export function Turn({
  role,
  text,
  who,
  className,
}: {
  role: Role
  text: string
  who?: string
  className?: string
}) {
  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2",
        role === "you" && "bg-primary/10 border-primary/25",
        role === "workspace" && "bg-card",
        role === "error" && "bg-destructive/10 border-destructive/30",
        className
      )}
    >
      <div
        className={cn(
          "mb-1 text-[0.7rem] font-medium tracking-wide uppercase",
          role === "error" ? "text-destructive" : "text-muted-foreground"
        )}
      >
        {who ?? WHO[role] ?? role}
      </div>
      <div className="text-sm leading-relaxed whitespace-pre-wrap">
        <Flow text={text} />
      </div>
    </div>
  )
}
