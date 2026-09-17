import { FolderGit2 } from "lucide-react"
import { ActionList, type FormInterface } from "react-data-form"
import { createResourceCollection, createViewResource } from "react-resource-view"

import { api } from "@/lib/api"
import { t } from "@/lib/i18n"
import { SCOPE } from "@/lib/resource-view"
import { currentSettings, publishSettings } from "@/lib/settings-store"
import type { ProjectPath } from "@/lib/types"

/* The `[projects]` table of `config.toml`, as a resource of its own.
 *
 * Every other section of the file is a list of keys somebody described; this
 * one is a mapping you add rows to, and rows are what a resource is for. So it
 * is declared here and hung under the settings page as a sub-resource —
 * react-resource-view draws the table, the "add" dialog and the confirmation
 * before a row goes, and the section stops being the one place in the console
 * with a hand-rolled table of inputs in it.
 *
 * There is no endpoint for one row: `/api/settings` takes the whole mapping
 * and answers with what it wrote. So a write here is the list as it should
 * now be — the row added, renamed or gone — and the answer is published to the
 * store the rest of the page reads.
 */

export const PROJECT_PATHS = "project-paths"

/** A row as the views hold it: the mapping, and an identity to address it by. */
export interface ProjectPathItem extends ProjectPath {
  "@id": string
  "@type": string
  /** The project's name is its identity — the file keys the table by it. */
  id: string
}

const item = (row: ProjectPath): ProjectPathItem => ({
  ...row,
  id: row.name,
  "@id": `/api/settings/projects/${encodeURIComponent(row.name)}`,
  "@type": PROJECT_PATHS,
})

const rows = (): ProjectPath[] => currentSettings()?.projects ?? []

/** The mapping as it should now be, written whole and read back whole. */
async function write(wanted: ProjectPath[]) {
  await api.saveSettings({ settings: {}, projects: wanted })
  publishSettings(await api.settings())
}

/* What a row asks for.
 *
 * A label and the buttons are translated by the package as it draws them; the
 * sentence under a field is not — it is used as it is given. Which is what the
 * getters are for: the declaration is built once, and the language can change
 * after it.
 */
const pathForm: FormInterface = {
  // The console's own "Written to Notion" is what a ticket is saved with; this
  // one writes a line to a file on this machine and says so. Handed to a toast
  // as it stands, so it is read from the dictionary here.
  label: {
    submit: "Save",
    get success() {
      return t("Written to the file")
    },
  },
  inputs: {
    name: {
      label: "Project",
      required: true,
      placeholder: "Site vitrine",
      get description() {
        return t("Spelled as the project page is, or the ticket finds no repository.")
      },
      validator: (value) => {
        if (!String(value ?? "").trim()) throw new Error(t("A row with no name maps nothing."))
        return value
      },
    },
    path: {
      label: "Where it is",
      required: true,
      placeholder: "~/workspace/that-repository",
      get description() {
        return t("The repository itself. Worktrees are made beside it, never in it.")
      },
      validator: (value) => {
        if (!String(value ?? "").trim())
          throw new Error(t("A project mapped to nothing is a row to remove."))
        return value
      },
    },
  },
}

/** The board's empty line is the board's; this list has one of its own. */
function NoMapping() {
  return (
    <p className="text-muted-foreground rounded-lg border border-dashed px-3 py-6 text-center text-sm">
      {t("No mapping here — the project pages carry it.")}
    </p>
  )
}

export const projectPaths = createViewResource<ProjectPathItem>(PROJECT_PATHS, {
  name: "Projects",
  scope: SCOPE,
  path: "/api/settings/projects",
  icon: FolderGit2,
  canList: true,
  canRead: false,
  canCreate: true,
  canUpdate: true,
  canDelete: true,

  getCollection: async () =>
    ({
      data: createResourceCollection({
        id: "/api/settings/projects",
        items: rows().map(item),
      }),
    }) as never,
  getItem: async ({ id }) => {
    const found = rows().find((row) => row.name === String(id))
    return { data: item(found ?? { name: String(id), path: "" }) }
  },
  createItem: async (fresh) => {
    const row = { name: String(fresh.name ?? "").trim(), path: String(fresh.path ?? "").trim() }
    await write([...rows(), row])
    return { data: item(row) }
  },
  updateItem: async (patch) => {
    const was = String(patch.id ?? "")
    const row = { name: String(patch.name ?? "").trim(), path: String(patch.path ?? "").trim() }
    await write(rows().map((current) => (current.name === was ? row : current)))
    return { data: item(row) }
  },
  removeItem: async ({ id }) => {
    await write(rows().filter((row) => row.name !== String(id)))
  },

  views: {
    [ActionList.list]: {
      name: "Projects",
      form: {
        inputs: {
          name: { label: "Project", readonly: true },
          path: { label: "Where it is", readonly: true },
        },
      },
      // There is nothing to read that the row does not already show.
      behavior: { rowActions: [ActionList.update, ActionList.delete] },
      components: { noResult: NoMapping },
    },
    // Over the section rather than instead of it: two boxes are not a page,
    // and the table behind them is what says whether the row is a duplicate.
    //
    // The button is named here rather than left to the action's own word: the
    // console already reads `create` as "New ticket", which is what the board
    // means by it and not what this list does.
    [ActionList.create]: {
      name: "add a project",
      label: { create: "add a project" },
      form: pathForm,
      behavior: { openIn: "popup" },
    },
    [ActionList.update]: {
      name: "Project",
      form: pathForm,
      behavior: { openIn: "popup" },
    },
  },
})
