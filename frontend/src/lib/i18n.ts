import * as React from "react"
import { setFormConfig } from "react-data-form"
import { setTranslation, translate } from "react-mini-i18n"

import { FRENCH } from "./french"

/* Which language the console speaks.
 *
 * The console is written in English and the sentence in the source *is* the
 * key — which is what react-mini-i18n is for: a key nobody translated is
 * rendered as it stands, so English needs no dictionary of its own beyond the
 * handful of words the packages under the console say differently. French is
 * the other dictionary, and it lives in `french.ts`.
 *
 * Nobody is asked which one they read. The browser already says — `Accept-
 * Language` is the setting somebody actually made — and where it says nothing
 * useful the time zone answers for it: a machine set to Europe/Paris is a
 * machine whose owner reads French, whatever the browser was installed in.
 * The choice is then one line in `localStorage`, like the theme, and the
 * select in the header is how you take it back.
 *
 * What is *not* translated here is everything that comes from somewhere else:
 * a ticket's title is Notion's, a column's name is the board's, the output of
 * a command is the CLI's. The console says its own words in your language and
 * repeats everybody else's in theirs.
 */

export type Language = "en" | "fr"

/** The two, with the flag the select shows. */
export const LANGUAGES: { code: Language; flag: string; name: string }[] = [
  { code: "en", flag: "🇬🇧", name: "English" },
  { code: "fr", flag: "🇫🇷", name: "Français" },
]

const KEY = "ticket-runner-language"

/* The words the packages say, in the console's own. A board with nothing on it
 * is not "No data yet", and the action called `read` is `Open`. */
const ENGLISH: Record<string, string> = {
  "No data yet": "Nothing on the board.",
  "Nothing here": "nothing",
  Saved: "Moved",
  create: "New ticket",
  read: "Open",
  "Une erreur est survenue": "Something went wrong",
  Continuer: "Continue",
  Fermer: "Close",
}

const DICTIONARIES: Record<Language, Record<string, string>> = {
  en: ENGLISH,
  fr: FRENCH,
}

/* Where French is the language of the work, whatever the browser was installed
 * in. A hint rather than a census: a zone that is not here only means the
 * browser's own languages have the last word. */
const FRENCH_ZONES = new Set([
  "Europe/Paris",
  "Europe/Brussels",
  "Europe/Luxembourg",
  "Europe/Monaco",
  "America/Montreal",
  "Africa/Algiers",
  "Africa/Tunis",
  "Africa/Casablanca",
  "Africa/Dakar",
  "Africa/Abidjan",
  "Indian/Reunion",
  "Pacific/Noumea",
])

const known = (code: string): code is Language =>
  LANGUAGES.some((language) => language.code === code)

/** What this browser reads, as best as it can be told without asking. */
export function detect(): Language {
  const said = navigator.languages?.length ? navigator.languages : [navigator.language]
  for (const tag of said) {
    const code = String(tag ?? "")
      .slice(0, 2)
      .toLowerCase()
    if (known(code)) return code
  }
  try {
    if (FRENCH_ZONES.has(Intl.DateTimeFormat().resolvedOptions().timeZone)) return "fr"
  } catch {
    // A browser without `Intl` reads the console in English, like every other
    // one that said nothing.
  }
  return "en"
}

function remembered(): Language {
  try {
    const kept = localStorage.getItem(KEY)
    if (kept && known(kept)) return kept
  } catch {
    // Storage switched off: the browser is asked again on every load, which is
    // the same answer it gave the first time.
  }
  return detect()
}

let language: Language = remembered()
const listeners = new Set<() => void>()

function apply(next: Language) {
  setTranslation(DICTIONARIES[next])
  document.documentElement.lang = next
  // These two are handed to a toast as they stand rather than translated on
  // the way, so they are written again whenever the dictionary changes.
  setFormConfig({
    defaultForm: {
      label: {
        success: translate("Written to Notion"),
        error: translate("Some fields need another look"),
      },
    },
  })
}

// On import, before a resource is declared: `createViewResource` reads the
// dictionary as it builds.
apply(language)

/** The language the console is in. */
export const currentLanguage = () => language

/** Change it, and redraw everything that says anything. */
export function setLanguage(next: Language) {
  if (next === language) return
  language = next
  apply(next)
  try {
    localStorage.setItem(KEY, next)
  } catch {
    // Kept for as long as the tab is open, then. That is the whole cost.
  }
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** The language, read reactively: a component that asks is redrawn when it changes. */
export function useLanguage(): Language {
  return React.useSyncExternalStore(subscribe, currentLanguage)
}

/** Outside a render — a toast, an event handler, a string built on the way to one. */
export const t = translate

/* Inside one. The function is the same; what the hook adds is the redraw, so a
 * pane that says anything at all asks for it here rather than importing `t`. */
export function useT(): typeof translate {
  useLanguage()
  return translate
}
