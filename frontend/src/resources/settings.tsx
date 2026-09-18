import * as React from "react"
import {
  Activity,
  Bell,
  Bot,
  CalendarClock,
  Columns3,
  FileStack,
  FolderGit2,
  GitBranch,
  GitPullRequest,
  Globe,
  MessageSquareText,
  NotebookText,
  RefreshCw,
  Settings2,
  TableProperties,
  Timer,
} from "lucide-react"
import { ActionList } from "react-data-form"
import {
  ViewResourceContextProvider,
  createViewResource,
  generateLink,
  useCurrentViewResourceContext,
  type IconType,
  type SubViewResourceInterface,
} from "react-resource-view"

import { PageHead } from "@/components/console/frame"
import { LanguagePicker } from "@/components/console/language-picker"
import { SectionForm, type SaveNote } from "@/components/console/settings-bits"
import { Rich } from "@/components/console/text"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { api } from "@/lib/api"
import { useT } from "@/lib/i18n"
import { SCOPE } from "@/lib/resource-view"
import {
  currentSettings,
  publishSettings,
  sectionOf,
  somethingIsEdited,
  useSettingsRevision,
} from "@/lib/settings-store"
import type { SettingSection, Settings } from "@/lib/types"

import { pairResources, type PairTable } from "./pairs"

/* The configuration, declared once for react-resource-view.
 *
 * `config.toml` is one thing, so it is one record: the page is the `read` view
 * of a resource with a single item, and each of the file's sections is a
 * sub-page of it. That is what the package's `subViewResource` is — one page,
 * its sub-pages, and the tab you are on carried in the address, so a link to
 * the notification settings is a link you can send somebody.
 *
 * It replaces a column of collapsibles that drew all seventy fields at once,
 * open or folded, and redrew every one of them on every keystroke. A tab draws
 * the section you are looking at and nothing else, which is most of what made
 * the page slow; what you type in a section you leave is kept in the store and
 * given back when you come to it again.
 *
 * The tabs are built from what the server says the file holds — a section the
 * runner gains is a sub-page the day it is described — which is why the list
 * is read from the store rather than written down here. See `settings-store`.
 */

export const SETTINGS = "settings"

/** The file is the record, and there is only ever the one. */
const THE_FILE = "config"

/** The configuration as the views hold it: the description, and an identity. */
export interface SettingsItem extends Settings {
  "@id": string
  "@type": string
  id: string
}

/* What each section is, at a glance. Decoration rather than a second list of
 * sections: a key nobody has drawn an icon for gets the page's own. */
const ICONS: Record<string, IconType> = {
  notion: NotebookText,
  runner: Timer,
  openrouter: Bot,
  git: GitBranch,
  schedules: CalendarClock,
  live: Activity,
  prompts: MessageSquareText,
  notify: Bell,
  web: Globe,
  update: RefreshCw,
  projects: FolderGit2,
  github: GitPullRequest,
  status: Columns3,
  properties: TableProperties,
  pages: FileStack,
}

/** The line under a section's name: the file's own words, code spans and all. */
function Blurb({ text }: { text: string }) {
  const t = useT()
  return (
    <p className="text-muted-foreground mb-5 max-w-prose text-xs leading-relaxed">
      <Rich text={t(text)} />
    </p>
  )
}

/* -- one sub-page ---------------------------------------------------------- */

function SectionPage({ sectionKey }: { sectionKey: string }) {
  const revision = useSettingsRevision()
  const [note, setNote] = React.useState<SaveNote | null>(null)
  const section = sectionOf(sectionKey)

  React.useEffect(() => {
    // A problem stays until it is read; a confirmation has been read by then.
    if (!note || note.bad) return
    const timer = window.setTimeout(() => setNote(null), 8000)
    return () => window.clearTimeout(timer)
  }, [note])

  if (!section) return null

  return (
    <div className="min-w-0">
      <Blurb text={section.blurb} />
      {/* The console's own language, at the top of the section that is about
          this console. It is the browser's rather than the file's, so it is
          not a field of the form under it — but it is a setting, and this is
          where somebody looking for a setting looks. */}
      {sectionKey === "web" ? <LanguagePicker /> : null}
      {note ? (
        <Alert variant={note.bad ? "destructive" : "success"} className="mb-4">
          <AlertDescription>
            <Rich text={note.text} />
          </AlertDescription>
        </Alert>
      ) : null}
      {/* Keyed by the revision: a save reads the file again, and the fields of
          every section are redrawn from what it now says. */}
      <SectionForm key={revision} section={section} onSaved={setNote} />
    </div>
  )
}

/* The sections that are a list rather than a list of keys — `[projects]` and
 * `[github]`. Each is a resource of its own, drawn here as a resource is drawn
 * — the package's table, its own dialogs — under the sentence that says what
 * the mapping is for. */
function pairsPage(sectionKey: string, table: PairTable): React.FC {
  return function PairsPage() {
    const section = sectionOf(sectionKey)
    return (
      <div className="min-w-0">
        {section ? <Blurb text={section.blurb} /> : null}
        <ViewResourceContextProvider
          resource={pairResources[table]}
          resourceAction={ActionList.list}
        />
      </div>
    )
  }
}

/* One component per section rather than one built as the tabs are drawn: a
 * component born in a render is a component React remounts on the next one. */
const PAGES = new Map<string, React.FC>()

function pageFor(section: SettingSection): React.FC {
  const known = PAGES.get(section.key)
  if (known) return known
  // A `pairs` the console has no resource for is drawn as any other section:
  // no fields described, so nothing but the sentence — which is a good deal
  // better than a tab that throws.
  const table = section.pairs in pairResources ? (section.pairs as PairTable) : ""
  const page = table
    ? pairsPage(section.key, table)
    : () => <SectionPage sectionKey={section.key} />
  PAGES.set(section.key, page)
  return page
}

/* The tabs, as the description last read says them.
 *
 * Read as they are drawn rather than fixed when the resource is declared: the
 * sections arrive with the configuration, and the page is drawn from what the
 * server says the file holds — never from a list kept here.
 */
function tabs(): SubViewResourceInterface[] {
  return (currentSettings()?.sections ?? []).map((section) => ({
    slug: section.key,
    // Drawn by the package, which translates it as it draws.
    name: section.title,
    icon: ICONS[section.key] ?? Settings2,
    viewComponent: pageFor(section),
  }))
}

/* -- the page itself ------------------------------------------------------- */

/* What sits above the tabs: where you are, what the page is for, which file it
 * is writing, and whatever `doctor` would refuse to start over. */
function SettingsHead() {
  const { fetchData } = useCurrentViewResourceContext()
  const t = useT()
  useSettingsRevision()
  const drawn = currentSettings()

  const latest = React.useRef(fetchData)
  latest.current = fetchData
  React.useEffect(() => {
    // Another tab saved, or `ticket-runner config` did. Read it again — unless
    // a section is in the middle of an edit, which is not something to take
    // away from you.
    const listener = () => {
      if (!somethingIsEdited()) void latest.current()
    }
    window.addEventListener("ticket-runner:settings", listener)
    return () => window.removeEventListener("ticket-runner:settings", listener)
  }, [])

  if (!drawn)
    return <p className="text-muted-foreground text-sm">{t("Reading the configuration…")}</p>

  return (
    <>
      <PageHead
        title={t("Configure the runner.")}
        blurb={t(
          "A field left blank says nothing, and the runner’s own default answers — shown greyed beside it. Your tokens stay on the machine: they are never sent to this page."
        )}
        action={<span className="text-muted-foreground font-mono text-xs">{drawn.path}</span>}
      />
      {drawn.problem ? (
        <Alert variant="destructive" className="mb-3">
          <AlertDescription>{drawn.problem}</AlertDescription>
        </Alert>
      ) : null}
    </>
  )
}

export const settings = createViewResource<SettingsItem>(SETTINGS, {
  name: "Settings",
  scope: SCOPE,
  path: "/api/settings",
  icon: Settings2,
  canRead: true,
  canList: false,
  canCreate: false,
  canUpdate: false,
  canDelete: false,

  getCollection: async () => {
    throw new Error("there is one configuration; it is not listed")
  },
  getItem: async () => {
    const drawn = await api.settings()
    // Published before it is returned: the tabs are built from the store, and
    // they are drawn the moment this resolves.
    publishSettings(drawn)
    return { data: { ...drawn, id: THE_FILE, "@id": "/api/settings", "@type": SETTINGS } }
  },
  createItem: async () => {
    throw new Error("the configuration is not created from the console")
  },
  updateItem: async () => {
    throw new Error("a section saves itself; see settings-bits")
  },
  removeItem: async () => {
    throw new Error("the configuration is not deleted from the console")
  },

  views: {
    [ActionList.read]: {
      name: "Settings",
      viewComponent: SettingsHead,
      // The object is what the package reads the tabs off, so the getter on it
      // survives the copy `createViewResource` makes of the view itself.
      subViewResource: {
        // Fourteen sections read as a column: a bar would push most of them off
        // the screen, and the one you are on with them.
        orientation: "vertical",
        get list() {
          return tabs()
        },
      },
    },
  },
})

/** Where the settings are — or one section of them. */
export const settingsHref = (section?: string) =>
  generateLink({
    scope: SCOPE,
    resourceId: SETTINGS,
    resourceAction: ActionList.read,
    id: THE_FILE,
    subResource: section,
  })
