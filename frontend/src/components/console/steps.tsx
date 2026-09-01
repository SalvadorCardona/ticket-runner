import { cn } from "@/lib/utils"
import type { Step } from "@/lib/types"

import { Flow } from "./text"

/* What a session is doing, one tool call to a line.
 *
 * A block of its own rather than part of the transcript: it scrolls inside
 * itself, so a run that reads forty files does not push the answer above it off
 * the screen — and when the run ends the block stays, dimmed, as the record of
 * how the answer was arrived at.
 */
export function Steps({
  steps,
  done = false,
  className,
}: {
  steps: Step[]
  done?: boolean
  className?: string
}) {
  if (!steps.length) return null
  return (
    <div
      className={cn(
        "scroll-thin bg-muted/40 max-h-48 overflow-y-auto rounded-lg border px-3 py-2 font-mono text-xs leading-relaxed",
        done && "opacity-60",
        className
      )}
    >
      {steps.map((step, index) => (
        <div key={index} className="text-muted-foreground">
          <span className="text-tr-violet font-medium">{step.label}</span>
          {step.detail ? (
            <>
              {" "}
              <Flow text={step.detail} />
            </>
          ) : null}
        </div>
      ))}
    </div>
  )
}
