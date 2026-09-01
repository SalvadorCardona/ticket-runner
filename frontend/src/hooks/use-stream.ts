import * as React from "react"

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
 */
export function useStream(handlers: Handlers): Connection {
  const [connection, setConnection] = React.useState<Connection>("connecting")
  const latest = React.useRef(handlers)
  latest.current = handlers

  React.useEffect(() => {
    const stream = new EventSource("/api/events", { withCredentials: true })
    stream.onopen = () => setConnection("live")
    stream.onerror = () => setConnection("reconnecting")

    const names = Object.keys(latest.current)
    const listeners = names.map((name) => {
      const listener = (event: MessageEvent<string>) => {
        let payload: unknown = null
        try {
          payload = event.data ? JSON.parse(event.data) : null
        } catch {
          return // a half-written frame is not an event
        }
        latest.current[name]?.(payload as never)
      }
      stream.addEventListener(name, listener as EventListener)
      return [name, listener] as const
    })

    return () => {
      for (const [name, listener] of listeners)
        stream.removeEventListener(name, listener as EventListener)
      stream.close()
    }
    // Opened once. The names are fixed at mount, which is true of every event
    // this console knows how to receive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return connection
}
