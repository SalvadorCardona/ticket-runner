import * as React from "react"

const MOBILE = 768

/** Whether the window is narrow enough that the sidebar becomes a drawer. */
export function useIsMobile() {
  const [isMobile, setIsMobile] = React.useState<boolean | undefined>(undefined)

  React.useEffect(() => {
    const query = window.matchMedia(`(max-width: ${MOBILE - 1}px)`)
    const answer = () => setIsMobile(window.innerWidth < MOBILE)
    query.addEventListener("change", answer)
    answer()
    return () => query.removeEventListener("change", answer)
  }, [])

  return !!isMobile
}
