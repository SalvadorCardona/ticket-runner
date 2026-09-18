import { ActionList } from "react-data-form"
import {
  ViewResourceContextProvider,
  findResource,
  useResolvedViewParams,
  type ViewResourceContextParams,
} from "react-resource-view"

import { useLanguage, useT } from "@/lib/i18n"
import { SCOPE } from "@/lib/resource-view"
import { cn } from "@/lib/utils"
import { TICKETS, tickets } from "@/resources/tickets"

// Imported for the side effect of declaring themselves: the address is all the
// package needs to find a resource, and it finds it in the registry.
import "@/resources/projects"
import "@/resources/schedules"
import "@/resources/settings"

/* Where react-resource-view draws.
 *
 * The address names a resource, an action and maybe an id; this hands that to
 * the package's context, which fetches and renders the matching view — the
 * board for `list`, the ticket page for `read`, the settings page and its
 * sub-pages. An address that names nothing is the board.
 */
const ACTIONS = new Set<string>(Object.values(ActionList))

export function ResourcePane({ params }: { params: ViewResourceContextParams }) {
  const t = useT()
  const language = useLanguage()
  const action =
    params.resourceAction && ACTIONS.has(params.resourceAction)
      ? params.resourceAction
      : ActionList.list
  const resourceId = params.resourceId ?? TICKETS
  const resolved = useResolvedViewParams({
    ...params,
    resource: findResource({ scope: SCOPE, resourceId }),
    resourceAction: action,
  })
  if (!resolved.resource) {
    return <p className="text-muted-foreground p-3.5 text-sm">{t("No such page.")}</p>
  }
  // A ticket's page is a pane of its own — its own bar, its own scroller, its
  // own margins — so the room around a view is given to the views that want it
  // and withheld from the one that does not.
  const bare = resolved.resource === tickets && action === ActionList.read
  return (
    <div className={cn("h-full", !bare && "p-3.5 sm:p-5")}>
      {/* The language is part of the key: what the package draws — the view's
          name, a column header, the words on a form — it reads from the
          dictionary as it builds, not as it renders. The resource and the
          action are in it too, because the context resolves them once. */}
      <ViewResourceContextProvider
        key={`${language}:${resourceId}:${action}:${String(resolved.id ?? "")}`}
        {...resolved}
      />
    </div>
  )
}
