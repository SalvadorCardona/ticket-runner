import { useConsole } from "@/hooks/use-console"

import { Steps } from "./steps"

/* What the running tickets are doing, straight from their session logs — no
 * Notion in the way. The newest session to say something is at the top. */
export function LivePane() {
  const { sessions } = useConsole()

  return (
    <div className="p-3.5">
      <div className="mb-4">
        <h2 className="text-base font-semibold">Sessions</h2>
        <p className="text-muted-foreground mt-0.5 text-xs">
          What the running tickets are doing, straight from their session logs — no Notion in the
          way.
        </p>
      </div>

      {sessions.length ? (
        <div className="space-y-3">
          {sessions.map((session) => (
            <div key={session.source} className="bg-card rounded-xl border p-3">
              <h3 className="mb-2 font-mono text-xs font-semibold">{session.source}</h3>
              <Steps steps={session.steps} className="max-h-72" />
            </div>
          ))}
        </div>
      ) : (
        <p className="text-muted-foreground text-sm">
          Nothing is running. A session that starts writes here as it works.
        </p>
      )}
    </div>
  )
}
