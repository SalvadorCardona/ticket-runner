import * as React from "react"

import { signedOut } from "@/lib/api"

export type Connection = "connecting" | "live" | "reconnecting"

type Handlers = Record<string, (payload: never) => void>

/* One `EventSource`, for as long as the tab is open.
 *
 * The rule the hand-written console kept and this one keeps: **the stream is the
 * truth.** A click posts and says nothing; what appears on the screen is what
 * came back here. So two open tabs show the same thing, and a message sent from
 * a phone shows up on the laptop.
 *
 * The handlers live in a ref rather than in the dependency list: they close over
 * fresh state on every render, and a dependency list would tear the connection
 * down and put it back up each time — which, with `Last-Event-ID`, is not even
 * wrong, just wasteful and visibly flickering in the header.
 *
 * A browser reconnects on its own after a dropped connection — but not after a
 * refused one. A 401 closes the stream for good, and the menu used to sit on
 * "reconnecting…" for as long as the tab stayed open. So a stream that closes
 * is asked why: a session that expired goes back to the sign-in, anything else
 * is tried again a few seconds later, from the last event it saw.
 */

/** How long a closed stream waits before it is opened again. */
const RETRY_MS = 3000

export function useStream(handlers: Handlers): Connection {
  const [connection, setConnection] = React.useState<Connection>("connecting")
  const latest = React.useRef(handlers)
  latest.current = handlers

  React.useEffect(() => {
    let stream: EventSource | null = null
    let retry = 0
    let stopped = false
    let seen = ""

    const open = () => {
      // `after` rather than the header a browser sends on its own: a stream
      // opened again by hand has no `Last-Event-ID`, and without it the events
      // of the seconds it was down would never arrive.
      stream = new EventSource(seen ? `/api/events?after=${seen}` : "/api/events", {
        withCredentials: true,
      })
      stream.onopen = () => setConnection("live")
      stream.onerror = () => {
        setConnection("reconnecting")
        if (!stream || stream.readyState !== EventSource.CLOSED) return
        stream.close()
        void signedOut().then((gone) => {
          if (gone || stopped) return
          retry = window.setTimeout(open, RETRY_MS)
        })
      }
      for (const name of Object.keys(latest.current)) {
        stream.addEventListener(name, ((event: MessageEvent<string>) => {
          if (event.lastEventId) seen = event.lastEventId
          let payload: unknown = null
          try {
            payload = event.data ? JSON.parse(event.data) : null
          } catch {
            return // a half-written frame is not an event
          }
          latest.current[name]?.(payload as never)
        }) as EventListener)
      }
    }

    open()
    return () => {
      stopped = true
      window.clearTimeout(retry)
      stream?.close()
    }
    // Opened once. The names are fixed at mount, which is true of every event
    // this console knows how to receive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return connection
}
