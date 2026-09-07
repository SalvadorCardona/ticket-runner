import * as React from "react"
import type { NavigationPortInterface, ViewResourceContextParams } from "react-resource-view"
import { parseLink } from "react-resource-view"

/* The console's addresses.
 *
 * Everything the page shows is named in the query string, because the server
 * behind it is `http.server` and the standard library: `/` is the one page it
 * serves, and a deep path would be a 404 before the JavaScript had a chance
 * to read it. So the board is `/?view=console/tickets/list`, a ticket is
 * `/?view=console/tickets/read/<id>` — the shape react-resource-view writes in
 * its `query` routing mode — and the panes that are not resources are
 * `/?page=live`, `/?page=settings`.
 *
 * The four primitives below are what that package asks of a router. Written
 * here rather than taken from TanStack: a console with three pages has no use
 * for a route tree, and the History API is the whole of what is needed.
 */

const CHANGED = "ticket-runner:navigate"

const current = () => window.location.pathname + window.location.search

function subscribe(listener: () => void) {
  window.addEventListener("popstate", listener)
  window.addEventListener(CHANGED, listener)
  return () => {
    window.removeEventListener("popstate", listener)
    window.removeEventListener(CHANGED, listener)
  }
}

/** The address bar, read reactively. */
export function useHref(): string {
  return React.useSyncExternalStore(subscribe, current)
}

/** Go somewhere, without reloading the page. */
export function go(to: string, replace = false) {
  if (current() === to) return
  if (replace) window.history.replaceState(null, "", to)
  else window.history.pushState(null, "", to)
  window.dispatchEvent(new Event(CHANGED))
}

const plainClick = (event: React.MouseEvent<HTMLAnchorElement>) =>
  !event.defaultPrevented &&
  event.button === 0 &&
  !event.metaKey &&
  !event.ctrlKey &&
  !event.shiftKey &&
  !event.altKey

/** What react-resource-view navigates and links with. */
export const navigation: NavigationPortInterface = {
  useNavigate: () => (options) => go(options.to, options.replace),
  useLocation: () => {
    const href = useHref()
    const url = new URL(href, window.location.origin)
    return { pathname: url.pathname, searchStr: url.search }
  },
  Link: ({ to, onClick, children, ...rest }) => (
    <a
      href={to}
      onClick={(event) => {
        onClick?.(event)
        if (!plainClick(event) || rest.target === "_blank") return
        event.preventDefault()
        go(to)
      }}
      {...rest}
    >
      {children}
    </a>
  ),
  Navigate: ({ to, replace }) => {
    React.useEffect(() => go(to, replace ?? true), [to, replace])
    return null
  },
}

/* -- what an address means ------------------------------------------------ */

export type Page = "live" | "settings" | "console"

export type Route =
  | { kind: "page"; page: Page }
  | { kind: "resource"; params: ViewResourceContextParams }

const PAGES: Page[] = ["live", "settings", "console"]

export const pageHref = (page: Page) => `/?page=${page}`

export function routeOf(href: string): Route {
  const url = new URL(href, window.location.origin)
  const page = url.searchParams.get("page") as Page | null
  if (page && PAGES.includes(page)) return { kind: "page", page }
  return { kind: "resource", params: parseLink(url.pathname + url.search) }
}

export function useRoute(): Route {
  const href = useHref()
  return React.useMemo(() => routeOf(href), [href])
}
