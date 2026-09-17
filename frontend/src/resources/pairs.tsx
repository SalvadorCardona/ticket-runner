import { FolderGit2, GitPullRequest } from "lucide-react"
import { ActionList, type FormInterface } from "react-data-form"
import {
  createResourceCollection,
  createViewResource,
  type IconType,
  type ViewResourceInterface,
} from "react-resource-view"

import { api } from "@/lib/api"
import { t } from "@/lib/i18n"
import { SCOPE } from "@/lib/resource-view"
import { currentSettings, publishSettings } from "@/lib/settings-store"
import type { Pair } from "@/lib/types"

/* The `name = value` tables of `config.toml`, each as a resource of its own.
 *
 * Every other section of the file is a list of keys somebody described; these
 * two are mappings you add rows to — `[projects]`, a Notion name and a path,
 * and `[github]`, an owner and the account it is worked under — and rows are
 * what a resource is for. So they are declared here and hung under the settings
 * page as sub-resources: react-resource-view draws the table, the "add" dialog
 * and the confirmation before a row goes, and those sections stop being the one
 * place in the console with a hand-rolled table of inputs in them.
 *
 * Two tables, one shape, their own words: what changes from one to the other is
 * a sentence, so the difference is a `Words` and not a second file.
 *
 * There is no endpoint for one row: `/api/settings` takes a whole mapping and
 * answers with what it wrote. So a write here is the list as it should now be —
 * the row added, renamed or gone — and the answer is published to the store the
 * rest of the page reads.
 */

/** Which table of the file a resource here is. `Section.pairs`, server-side. */
export type PairTable = "projects" | "github"

/** A row as the views hold it: the mapping, and an identity to address it by. */
export interface PairItem extends Pair {
  "@id": string
  "@type": string
  /** The left-hand side is the identity — the file keys the table by it. */
  id: string
}

/** One side of a row, in the words of the table it belongs to. */
interface Side {
  label: string
  placeholder: string
  /** Said under the field. Read from the dictionary, see `form` below. */
  description: string
  /** What is refused when the field is left empty. */
  missing: string
}

interface Words {
  /** The name the package files the resource under, and the list's own name. */
  resource: string
  list: string
  /** What one row is called, over the form that edits it. */
  row: string
  icon: IconType
  name: Side
  value: Side
  /** What stands where the rows would be, when the table is empty. */
  empty: string
  /** The button, and the dialog it opens. The console reads `create` as
   *  "New ticket", which is what the board means by it and not what this does. */
  add: string
}

const PROJECTS: Words = {
  resource: "project-paths",
  list: "Projects",
  row: "Project",
  icon: FolderGit2,
  name: {
    label: "Project",
    placeholder: "Site vitrine",
    description: "Spelled as the project page is, or the ticket finds no repository.",
    missing: "A row with no name maps nothing.",
  },
  value: {
    label: "Where it is",
    placeholder: "~/workspace/that-repository",
    description: "The repository itself. Worktrees are made beside it, never in it.",
    missing: "A project mapped to nothing is a row to remove.",
  },
  empty: "No mapping here — the project pages carry it.",
  add: "add a project",
}

const GITHUB: Words = {
  resource: "github-accounts",
  list: "Accounts",
  row: "Account",
  // No brand marks in lucide, and the pull request is what the mapping is for.
  icon: GitPullRequest,
  name: {
    label: "Owner",
    placeholder: "acme-corp",
    description: "As GitHub spells it in the URL of a repository, before the slash.",
    missing: "A row with no owner names nobody.",
  },
  value: {
    label: "Account",
    placeholder: "salva-at-acme",
    description: "The account `gh auth status` lists, logged in once with `gh auth login`.",
    missing: "An owner mapped to nothing is a row to remove.",
  },
  empty: "One GitHub here — everything goes out as whoever gh is signed in as.",
  add: "add an account",
}

const item = (table: PairTable, row: Pair): PairItem => ({
  ...row,
  id: row.name,
  "@id": `/api/settings/${table}/${encodeURIComponent(row.name)}`,
  "@type": table,
})

const rows = (table: PairTable): Pair[] => currentSettings()?.[table] ?? []

/** One mapping as it should now be, written whole and read back whole. */
async function write(table: PairTable, wanted: Pair[]) {
  const payload: Parameters<typeof api.saveSettings>[0] = { settings: {} }
  payload[table] = wanted
  await api.saveSettings(payload)
  publishSettings(await api.settings())
}

/* What a row asks for.
 *
 * A label and the buttons are translated by the package as it draws them; the
 * sentence under a field is not — it is used as it is given. Which is what the
 * getters are for: the declaration is built once, and the language can change
 * after it.
 */
function form(words: Words): FormInterface {
  const side = (of: Side) => ({
    label: of.label,
    required: true,
    placeholder: of.placeholder,
    get description() {
      return t(of.description)
    },
    validator: (value: unknown) => {
      if (!String(value ?? "").trim()) throw new Error(t(of.missing))
      return value
    },
  })
  return {
    // The console's own "Written to Notion" is what a ticket is saved with;
    // this one writes a line to a file on this machine and says so. Handed to
    // a toast as it stands, so it is read from the dictionary here.
    label: {
      submit: "Save",
      get success() {
        return t("Written to the file")
      },
    },
    inputs: { name: side(words.name), value: side(words.value) },
  }
}

/** The board's empty line is the board's; these lists have one of their own. */
function nothingHere(sentence: string) {
  return function Nothing() {
    return (
      <p className="text-muted-foreground rounded-lg border border-dashed px-3 py-6 text-center text-sm">
        {t(sentence)}
      </p>
    )
  }
}

function pairResource(table: PairTable, words: Words) {
  const rowForm = form(words)
  return createViewResource<PairItem>(words.resource, {
    name: words.list,
    scope: SCOPE,
    path: `/api/settings/${table}`,
    icon: words.icon,
    canList: true,
    canRead: false,
    canCreate: true,
    canUpdate: true,
    canDelete: true,

    getCollection: async () =>
      ({
        data: createResourceCollection({
          id: `/api/settings/${table}`,
          items: rows(table).map((row) => item(table, row)),
        }),
      }) as never,
    getItem: async ({ id }) => {
      const found = rows(table).find((row) => row.name === String(id))
      return { data: item(table, found ?? { name: String(id), value: "" }) }
    },
    createItem: async (fresh) => {
      const row = { name: String(fresh.name ?? "").trim(), value: String(fresh.value ?? "").trim() }
      await write(table, [...rows(table), row])
      return { data: item(table, row) }
    },
    updateItem: async (patch) => {
      const was = String(patch.id ?? "")
      const row = { name: String(patch.name ?? "").trim(), value: String(patch.value ?? "").trim() }
      await write(
        table,
        rows(table).map((current) => (current.name === was ? row : current))
      )
      return { data: item(table, row) }
    },
    removeItem: async ({ id }) => {
      await write(
        table,
        rows(table).filter((row) => row.name !== String(id))
      )
    },

    views: {
      [ActionList.list]: {
        name: words.list,
        form: {
          inputs: {
            name: { label: words.name.label, readonly: true },
            value: { label: words.value.label, readonly: true },
          },
        },
        // There is nothing to read that the row does not already show.
        behavior: { rowActions: [ActionList.update, ActionList.delete] },
        components: { noResult: nothingHere(words.empty) },
      },
      // Over the section rather than instead of it: two boxes are not a page,
      // and the table behind them is what says whether the row is a duplicate.
      [ActionList.create]: {
        name: words.add,
        label: { create: words.add },
        form: rowForm,
        behavior: { openIn: "popup" },
      },
      [ActionList.update]: {
        name: words.row,
        form: rowForm,
        behavior: { openIn: "popup" },
      },
    },
  })
}

/** The resource that draws one table, by the name `Section.pairs` gives it. */
export const pairResources: Record<PairTable, ViewResourceInterface<PairItem>> = {
  projects: pairResource("projects", PROJECTS),
  github: pairResource("github", GITHUB),
}
