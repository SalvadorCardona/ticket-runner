import * as React from "react"

const KEY = "ticket-runner-theme"

export type Theme = "dark" | "light"

/** Which of the two the console is in, and the switch that changes it.
 *
 * Dark is the default because the console it replaces had no other: it sits
 * beside a terminal and a Notion board, and the thing it shows most of the time
 * is a log. The choice is one line in `localStorage`, read before the first
 * paint by the script in `index.html` so the page never flashes white.
 */
export function useTheme() {
  const [theme, setTheme] = React.useState<Theme>(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light"
  )

  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
    try {
      localStorage.setItem(KEY, theme)
    } catch {
      // A browser with storage switched off still gets the theme it asked for,
      // for as long as the tab is open. That is the whole cost.
    }
  }, [theme])

  const toggle = React.useCallback(
    () => setTheme((current) => (current === "dark" ? "light" : "dark")),
    []
  )

  return { theme, setTheme, toggle }
}
