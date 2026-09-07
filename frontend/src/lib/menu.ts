import type { MenuItemInterface } from "react-resource-view"

import type { Page } from "./router"

/* What the left menu is made of.
 *
 * `MenuItemInterface` is react-resource-view's own: the console now has
 * addresses — a pane is a URL, not React state — so the shape that package
 * expects of a menu is the shape this menu has, `href` included.
 */
export type { MenuItemInterface }

/** What the console adds: what the entry counts, and what it says under its name. */
export interface PaneMenuItem extends MenuItemInterface {
  href: string
  /** Which pane the entry is, for the one that is not an address of the board. */
  page?: Page
  /** A number worth showing beside the name — tickets on the board, sessions live. */
  badge?: string | number
  /** Said under the name, and only where it says something. */
  detail?: string
}

/** The declared order, with `hidden` honoured and `priority` respected. */
export function visible(items: PaneMenuItem[]): PaneMenuItem[] {
  return items
    .filter((item) => !item.hidden)
    .sort((left, right) => (right.priority ?? 0) - (left.priority ?? 0))
}
