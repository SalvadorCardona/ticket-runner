import type { MenuItemInterface } from "react-resource-view"

import type { Page } from "./router"

/* What the left menu is made of.
 *
 * `MenuItemInterface` is react-resource-view's own: the console now has
 * addresses — a pane is a URL, not React state — so the shape that package
 * expects of a menu is the shape this menu has, `href` included.
 */
export type { MenuItemInterface }

/* What the console adds: which pane the entry is, and what it counts.
 *
 * A name and a number, and nothing else. Every entry used to carry a sentence
 * under it as well — how many tickets were ready, whether the timer was on —
 * which made the menu a page of its own to read: seven entries, fourteen lines,
 * and the one you were looking for said in the smaller type. What a menu owes
 * its reader is where to go and whether something is waiting there.
 */
export interface PaneMenuItem extends MenuItemInterface {
  href: string
  /** Which pane the entry is, for the ones that are not a resource's address. */
  page?: Page
  /** Which resource the entry opens, for the ones that are. */
  resource?: string
  /** A number worth showing beside the name — tickets on the board, sessions live. */
  badge?: string | number
}

/** The declared order, with `hidden` honoured and `priority` respected. */
export function visible(items: PaneMenuItem[]): PaneMenuItem[] {
  return items
    .filter((item) => !item.hidden)
    .sort((left, right) => (right.priority ?? 0) - (left.priority ?? 0))
}
