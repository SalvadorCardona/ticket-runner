import { SidebarTrigger } from "@/components/ui/sidebar"

import { Eyebrow } from "./frame"

/* Where you are, and nothing else.
 *
 * The bar used to carry a row of pills across its right half — the timer, a run
 * in flight, what had been spent, a version waiting — and the language the
 * console reads in. All of it was true and none of it was being read: a state
 * you cannot act on, repeated on every page, is noise with a border around it.
 * What a run is doing is what the Live pane is for, a version waiting is said
 * once at the foot of the menu, and a language is a setting, so it sits with
 * the settings.
 *
 * What is left is the path — the sidebar's entry, then what is open under it.
 * The bar names where you are and nothing more: the page under it opens with
 * its own heading, and a title said twice is a title read neither time.
 */
export function Header({ crumbs }: { crumbs: string[] }) {
  return (
    <header className="flex items-center gap-x-3 border-b px-3 py-2">
      <SidebarTrigger className="-ml-1" />
      <div className="min-w-0 truncate">
        <Eyebrow>
          {crumbs.map((part, index) => (
            <span key={part}>
              {index ? <span className="text-border mx-1.5">/</span> : null}
              {part}
            </span>
          ))}
        </Eyebrow>
      </div>
    </header>
  )
}
