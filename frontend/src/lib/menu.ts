import type { ComponentType } from "react"

/* What the left menu is made of.
 *
 * The shape is `MenuItemInterface` from
 * [react-resource-view](https://github.com/SalvadorCardona/react-resource-view),
 * written out here rather than imported. That package's menu module is a *type*
 * plus two "is this the current item" helpers, and those helpers answer by
 * comparing `href` against the location its routing port reports. This console
 * has no router and no addresses: a pane is React state, not a URL. Taking the
 * dependency would mean installing `react-data-form`, `resource-registry`,
 * `react-mini-i18n` and a router to end up re-implementing `isActive` anyway.
 *
 * So the vocabulary is shared and the machinery is not. `href` is kept in the
 * shape even though nothing sets it today: the day the console grows real
 * addresses — or mounts a `ResourceView` screen of its own — the menu it already
 * has is the one that package expects, and `useIsActiveItemMenu` becomes usable
 * without rewriting this file.
 */
export interface MenuItemInterface {
  /** What the entry is called. Also its tooltip when the rail is collapsed. */
  name: string
  icon?: ComponentType<{ className?: string }>
  href?: string
  items?: MenuItemInterface[]
  hidden?: boolean
  isSelected?: boolean
  /** Bigger sorts first, so a section can be pushed up without moving its code. */
  priority?: number
}

/** What the console adds: which pane the entry shows, and what it counts. */
export interface PaneMenuItem extends MenuItemInterface {
  pane: Pane
  /** A number worth showing beside the name — tickets ready, sessions live. */
  badge?: string | number
  /** Said under the name, and only where it says something. */
  detail?: string
}

export type Pane = "board" | "ticket" | "console" | "live" | "settings"

/** The declared order, with `hidden` honoured and `priority` respected. */
export function visible(items: PaneMenuItem[]): PaneMenuItem[] {
  return items
    .filter((item) => !item.hidden)
    .sort((left, right) => (right.priority ?? 0) - (left.priority ?? 0))
}
