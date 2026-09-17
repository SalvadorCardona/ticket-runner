import * as React from "react"

import type { SettingSection, Settings, SettingValue } from "./types"

/* The configuration, as the server last described it.
 *
 * The settings page is a resource with one sub-page per section, and a
 * sub-page is declared before anything has been fetched — `subViewResource`
 * is read off the view as the tabs are drawn. So the description has to be
 * reachable from outside React: `getItem` writes it here, the tab list reads
 * it back, and the page stays what it has always been — drawn from what the
 * server says the configuration holds, never from a list kept in the console.
 *
 * Two other things live here for the same reason.
 *
 * A *draft* is what you have typed in a section and not saved. Only one
 * sub-page is mounted at a time — that is the whole point of tabs, and it is
 * why the page no longer draws seventy fields at once — so a form leaving the
 * screen would otherwise take your edits with it. It writes them here instead
 * and reads them back on the way in.
 *
 * And the *revision*, which is how a save reaches the sections it did not
 * touch: every form is keyed by it, so a fresh description redraws them all —
 * previews, defaults and what the file now states included.
 */

let drawn: Settings | null = null
let revision = 0

const listeners = new Set<() => void>()
const drafts = new Map<string, Record<string, SettingValue>>()

const tell = () => listeners.forEach((listener) => listener())

/** What the server just said the file holds. */
export function publishSettings(fresh: Settings) {
  drawn = fresh
  revision += 1
  tell()
}

export const currentSettings = (): Settings | null => drawn

/** One section of it, by the key the server names it with. */
export const sectionOf = (key: string): SettingSection | undefined =>
  drawn?.sections.find((section) => section.key === key)

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** How many times the description has been redrawn. Read to be redrawn with it. */
export function useSettingsRevision(): number {
  return React.useSyncExternalStore(subscribe, () => revision)
}

/** What a section holds that the file does not — or nothing, once it is saved. */
export function rememberDraft(key: string, data: Record<string, SettingValue>, dirty: boolean) {
  if (dirty) drafts.set(key, data)
  else drafts.delete(key)
}

export const draftOf = (key: string): Record<string, SettingValue> | undefined => drafts.get(key)

export const forgetDraft = (key: string) => drafts.delete(key)

/** Whether anything typed is waiting to be saved — asked before a redraw takes it away. */
export const somethingIsEdited = (): boolean => drafts.size > 0
