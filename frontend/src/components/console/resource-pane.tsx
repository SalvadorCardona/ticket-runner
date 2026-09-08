import { ActionList } from "react-data-form"
import {
  ViewResourceContextProvider,
  useResolvedViewParams,
  type ViewResourceContextParams,
} from "react-resource-view"

import { cn } from "@/lib/utils"
import { TICKETS, tickets } from "@/resources/tickets"

/* Where react-resource-view draws.
 *
 * The address names a resource, an action and maybe an id; this hands that to
 * the package's context, which fetches and renders the matching view — the
 * board for `list`, the ticket page for `read`, the form for `create`. An
 * address that names nothing is the board.
 */
const ACTIONS = new Set<string>(Object.values(ActionList))

export function ResourcePane({ params }: { params: ViewResourceContextParams }) {
  const action =
    params.resourceAction && ACTIONS.has(params.resourceAction)
      ? params.resourceAction
      : ActionList.list
  const resolved = useResolvedViewParams({
    ...params,
    resource: params.resourceId === TICKETS || !params.resourceId ? tickets : undefined,
    resourceAction: action,
  })
  if (!resolved.resource) {
    return <p className="text-muted-foreground p-3.5 text-sm">No such page.</p>
  }
  return (
    // A ticket's page is a pane of its own — its own bar, its own scroller,
    // its own margins — so the room around a view is given to the views that
    // want it and withheld from the one that does not.
    <div className={cn("h-full", action !== ActionList.read && "p-3.5 sm:p-5")}>
      <ViewResourceContextProvider
        key={`${action}:${String(resolved.id ?? "")}`}
        {...resolved}
      />
    </div>
  )
}
