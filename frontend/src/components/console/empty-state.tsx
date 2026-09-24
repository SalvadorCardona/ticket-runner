import * as React from "react"
import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/* What a pane says when it has nothing to show.
 *
 * One shape for all of them: the board with no card, the sessions with nothing
 * running, the projects nobody declared, the schedules nobody wrote. They used
 * to be four dashed boxes of four sizes, and the schedules' a fifth thing
 * drawn by the package — an empty page is read the same way whichever page it
 * is, so it looks the same too. An icon says which page, a sentence says why
 * it is empty, and where there is something to do about it, the way to do it.
 */
export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
  className,
}: {
  icon?: LucideIcon
  title?: string
  children: React.ReactNode
  /** The gesture that fills it, where there is one. */
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "text-muted-foreground flex flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-10 text-center text-sm",
        className
      )}
    >
      {Icon ? <Icon className="size-5 opacity-80" aria-hidden /> : null}
      {title ? <p className="text-foreground font-medium">{title}</p> : null}
      <div className="max-w-prose leading-relaxed">{children}</div>
      {action ? <div className="mt-2 flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  )
}
