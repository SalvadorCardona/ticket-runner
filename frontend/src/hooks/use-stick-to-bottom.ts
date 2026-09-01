import * as React from "react"

/** Keep a scrolling box at its end while new lines land in it.
 *
 * Only while it *is* at its end: a transcript that yanks itself back down while
 * you are reading something further up is a transcript you cannot read.
 */
export function useStickToBottom<T extends HTMLElement>(
  ...watch: unknown[]
): React.RefObject<T | null> {
  const ref = React.useRef<T>(null)
  const stuck = React.useRef(true)

  React.useEffect(() => {
    const node = ref.current
    if (!node) return
    const onScroll = () => {
      const room = node.scrollHeight - node.scrollTop - node.clientHeight
      stuck.current = room < 80
    }
    node.addEventListener("scroll", onScroll, { passive: true })
    return () => node.removeEventListener("scroll", onScroll)
  }, [])

  React.useEffect(() => {
    const node = ref.current
    if (node && stuck.current) node.scrollTop = node.scrollHeight
  })

  // `watch` is what the caller redraws on; reading it is what makes the effect
  // above run when they change.
  void watch

  return ref
}
