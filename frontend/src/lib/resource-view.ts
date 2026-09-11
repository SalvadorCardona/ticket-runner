import {
  configureApi,
  configurePorts,
  setCurrentScope,
  type ApiDialectInterface,
} from "react-resource-view"

// The dictionary has to be in place before a resource is declared: the words
// the views are built with go through it. See `i18n.ts`, which applies it on
// import.
import "./i18n"
import { navigation } from "./router"

/* Wiring react-resource-view into the console, once, before a resource is
 * declared — `createViewResource` reads the dialect as it builds.
 *
 * The package knows neither this router nor this API; both arrive here. The
 * API side is small: every resource brings its own reads and writes (the
 * board comes off the stream, a ticket off `/api/tickets/<id>`), so the
 * dialect's only real job is to say what a ticket's identity is — the bare
 * page id, which is also the segment a URL carries.
 */

/** Every resource of the console lives under this scope, which is the first segment of every address. */
export const SCOPE = "console"

const ticketDialect: ApiDialectInterface = {
  name: "ticket-runner",
  buildRequest(operation) {
    // Every resource declares its own reads and writes; nothing builds a
    // request from the path alone.
    throw new Error(`no request for ${operation.name} on ${operation.path}`)
  },
  readCollection(payload) {
    const collection = (payload ?? {}) as { items?: unknown[]; member?: unknown[] }
    const items = (collection.items ?? collection.member ?? []) as Record<string, unknown>[]
    return { items, totalItems: items.length }
  },
  readItem: (payload) => (payload ?? undefined) as Record<string, unknown> | undefined,
  getId: (item) => (item?.id as string | undefined) ?? undefined,
  getIdentifier: (item) => (item?.id as string | undefined) ?? undefined,
  normalizeError(payload, status) {
    const said = (payload as { error?: string } | undefined)?.error
    return { status, detail: said }
  },
  referencesAreIris: false,
}

let done = false

export function configureConsoleViews() {
  if (done) return
  done = true

  setCurrentScope(SCOPE)

  configurePorts({
    navigation,
    // The one page the Python server serves is `/`; the rest is the query
    // string, so a deep link survives a reload.
    routing: { mode: "query", param: "view", basePath: "/" },
    appName: "ticket-runner",
    // `index.html` names the page; the views are not to rename it.
    ownsDocumentHead: false,
    isDev: false,
  })

  configureApi({ baseUrl: "", dialect: ticketDialect })
}

// On import, so that a resource declared in any module finds the dialect in place.
configureConsoleViews()
