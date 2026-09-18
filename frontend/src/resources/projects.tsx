import * as React from "react"
import { FolderGit2 } from "lucide-react"
import { ActionList, TextAreaInputController, type FormInterface } from "react-data-form"
import {
  Link,
  cardViewOptionFactory,
  createResourceCollection,
  createViewResource,
  generateLinkByResource,
  tableViewOptionFactory,
  useCurrentViewResourceContext,
  type RowComponentPropsInterface,
} from "react-resource-view"

import { Eyebrow, Fact, Facts } from "@/components/console/frame"
import { ProjectPage } from "@/components/console/project-page"
import { Chip } from "@/components/console/ticket-bits"
import { api } from "@/lib/api"
import { t } from "@/lib/i18n"
import { SCOPE, layoutOf, useLayoutInTheAddress } from "@/lib/resource-view"
import type { Project, Projects } from "@/lib/types"

/* The projects, declared once for react-resource-view.
 *
 * They were a pane that only read: a list of what this installation knows of,
 * and a link out to Notion for anything you wanted to change. But a project is
 * where every ticket of that project starts from — its repository, and the
 * brief that gives an answer your voice rather than nobody's — so it is worth
 * opening, and worth changing without leaving the console.
 *
 * Which makes it a resource like the board: a list, a page per record, a form
 * that writes it back. It is drawn in two layouts, and the pair is the point —
 * **cards** to look at a workspace you half remember, since a project is
 * recognised by its name and its shape rather than read; **a table** to compare
 * them, because "which of these eleven has no repository" is a question a grid
 * of cards will not answer. The package holds both and the address carries
 * which one you are on, so the layout you work in is the one that comes back.
 *
 * Three sources still, as the pane had them: the board's own database, the
 * `[projects]` table of the configuration, and where the repository turned out
 * to be. A project the file names and the board has never heard of has no page
 * to open — it is a line in `config.toml` — so it is addressed here by its name
 * under a `config:` prefix, and its page says where it is really edited. Every
 * project is clickable; only the ones that are a page are written from here.
 */

export const PROJECTS = "projects"

/** A project as the views hold it: the row, an IRI, and the two cells a table reads. */
export type ProjectItem = Project & {
  "@id": string
  "@type": string
  /** The brief, on the page of the ones that have a page. */
  content?: string
  /** `kind`, in the words the console says it in. */
  work: string
  /** The path this machine finds it at, whoever declared it. */
  where: string
}

/** What the console writes about a project: the page's three columns, and the brief. */
export interface ProjectWrite {
  id?: string
  name?: string
  repository?: string
  path?: string
  content?: string
}

/** A project the configuration names and the board has never heard of. */
const FILE = "config:"

/** How a row is addressed: its page, or its name where there is no page. */
const idOf = (project: Project): string => project.id || `${FILE}${project.name}`

/** Whether that address is a page — the only kind this console writes to. */
export const isAPage = (id: string): boolean => Boolean(id) && !id.startsWith(FILE)

const item = (project: Project & { content?: string }): ProjectItem => ({
  ...project,
  id: idOf(project),
  "@id": `/api/projects/${idOf(project)}`,
  "@type": PROJECTS,
  work: project.kind === "code" ? t("code work") : t("document work"),
  where: project.configured || project.path || "",
})

/* -- what the list last read ---------------------------------------------- */

/* The payload says two things a row does not: where repositories are looked
 * for, and what a project the file alone names is. Both are read outside the
 * row that carries them — the foot of the list, and the page of a project with
 * no page — so what the server last said is kept here, the way the settings
 * keep their description. */

let drawn: Projects | null = null
const listeners = new Set<() => void>()

function publish(fresh: Projects) {
  drawn = fresh
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** What the list last read, redrawn with it. */
export function useProjects(): Projects | null {
  return React.useSyncExternalStore(subscribe, () => drawn)
}

/* Why the last project read failed, for the page to say rather than swallow.
 *
 * What a view component is handed is `error: true` and nothing else, so the
 * page could only say that something went wrong. On 18 September 2026 that
 * sentence was the whole of what a browser showed while the server was
 * answering `no such route: /api/projects/<id>` — a console left running the
 * code of the day before, serving the page built that morning. The server's own
 * words are what tell those apart from a project that is simply gone.
 */
let refusal = ""

/** What the server said the last time a project could not be read. */
export const whyNotRead = (): string => refusal

/** One project, from wherever it is held: its page, or the line that names it. */
async function one(id: string): Promise<ProjectItem> {
  if (isAPage(id)) return item(await api.project(id))
  // No page to read: the row is a line in the file, and the list is where it
  // was read from. Read again rather than taken from what is held, so a link
  // opened cold — a tab that has never listed anything — answers too.
  const read = await api.projects()
  publish(read)
  const found = read.projects.find((project) => idOf(project) === id)
  if (!found) throw new Error(t("No project called “{{name}}”.", { name: id.slice(FILE.length) }))
  return item(found)
}

/* -- the forms ------------------------------------------------------------ */

/* What a project page holds, as a form.
 *
 * A label and the button are translated by the package as it draws them; the
 * sentence under a field and the greyed example in it are not — they are used
 * as they are given. Those are read from the dictionary as the field is drawn,
 * which is what the getters are for: the declaration is built once, and the
 * language can change after it.
 */
const editForm: FormInterface = {
  label: { submit: "Save" },
  inputs: {
    name: {
      label: "Project",
      get description() {
        return t("What the board calls it. A ticket points at this page, not at this name.")
      },
      required: true,
    },
    repository: {
      label: "Repository",
      get description() {
        return t("owner/repo, or the clone URL. Empty, and its tickets come back as a document.")
      },
      placeholder: "SalvadorCardona/ticket-runner",
    },
    path: {
      label: "Where it is",
      get description() {
        return t(
          "Only needed where the repository cannot be found on its own. Worktrees are made beside it, never in it."
        )
      },
      placeholder: "~/workspace/that-repository",
    },
    content: {
      label: "The brief",
      get description() {
        return t(
          "The audience, the voice, the conventions, the things never to do. Every ticket of this project is told it before it is told the ticket."
        )
      },
      // Said here, because the package's own default for a text area is
      // “Votre message…” — the placeholder of a chat box, on the one field of
      // this console that is a page of standing instructions.
      get placeholder() {
        return t("Write it as you would brief somebody joining the project.")
      },
      controller: TextAreaInputController,
    },
  },
}

/** The columns of the table layout. The headings go through the dictionary on their way to the page. */
const rowForm: FormInterface = {
  inputs: {
    name: { label: "Project", readonly: true },
    work: { label: "Kind", readonly: true },
    repository: { label: "Repository", readonly: true },
    where: { label: "On this machine", readonly: true },
    tickets: { label: "Tickets", readonly: true },
  },
}

/* -- one card ------------------------------------------------------------- */

/* How a project is drawn in the card layout. The card is the way into the
 * project's page — its name is the link — and it says the same three things
 * the pane's rows said: what kind of work it is, what it declares, and where
 * that declaration comes from.
 *
 * The frame, the padding and the row of actions under it are the package's:
 * `cardViewOptionFactory` draws a record in a card and hands the inside of it
 * to this.
 */
function ProjectCard({ row }: RowComponentPropsInterface) {
  const project = row?.data as ProjectItem | undefined
  const { resource } = useCurrentViewResourceContext()
  if (!project) return null
  const href = generateLinkByResource({
    resource,
    resourceAction: ActionList.read,
    id: project.id,
  })

  return (
    <div className="flex min-w-0 flex-col gap-2.5">
      <div className="flex items-baseline gap-2">
        <Eyebrow>{project.work}</Eyebrow>
        <span className="flex-1" />
        {project.tickets ? (
          <span className="text-muted-foreground font-mono text-[0.7rem] tabular-nums">
            {t("{{count}} ticket(s)", { count: String(project.tickets) })}
          </span>
        ) : null}
      </div>

      <Link
        to={href}
        className="text-[0.95rem] leading-snug font-semibold hover:underline"
      >
        {project.name}
      </Link>

      {project.repository || project.where ? (
        <Facts>
          {/* A fact is one line and these two are longer than it — three cards
              across, a path is cut about where it stops being a path. The title
              is what makes the cut recoverable without opening the project. */}
          <Fact label={t("repository")}>
            <span className="font-mono text-xs" title={project.repository || undefined}>
              {project.repository || "—"}
            </span>
          </Fact>
          <Fact label={t("on this machine")}>
            <span className="font-mono text-xs" title={project.where || undefined}>
              {project.where || t("wherever the clone is")}
            </span>
          </Fact>
        </Facts>
      ) : (
        <p className="text-muted-foreground text-sm">
          {t(
            "Nothing declares a repository, so its tickets produce a document rather than a pull request."
          )}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        {project.source === "config" ? <Chip>{t("from the configuration")}</Chip> : null}
        {project.configured && project.source === "board" ? (
          <Chip>{t("path set in the configuration")}</Chip>
        ) : null}
      </div>
    </div>
  )
}

/* -- what sits around the list -------------------------------------------- */

/** How many of them are worked on in git, said where the list opens. */
function ProjectsTop() {
  const read = useProjects()
  useLayoutInTheAddress(PROJECTS)
  if (!read) return null
  const code = read.projects.filter((project) => project.kind === "code").length
  return (
    <p className="text-muted-foreground mb-2 inline-flex items-center gap-1.5 font-mono text-[0.7rem]">
      <FolderGit2 className="size-3.5" />
      {read.projects.length
        ? t("{{count}} of {{total}} on a repository", {
            count: String(code),
            total: String(read.projects.length),
          })
        : t("nothing yet")}
    </p>
  )
}

/** Where a repository is looked for, which is the answer to half of "why was it not found". */
function ProjectsFoot() {
  const read = useProjects()
  if (!read) return null
  return (
    <p className="text-muted-foreground mt-4 text-xs">
      <Eyebrow>runner.workspace_root</Eyebrow> —{" "}
      <span className="font-mono">{read.workspace_root}</span>{" "}
      {t("is where a repository is looked for, and cloned into when it is nowhere.")}
    </p>
  )
}

/** The list's own empty line: a board with no projects is not a broken board. */
function NoProject() {
  return (
    <p className="text-muted-foreground rounded-lg border border-dashed px-3 py-6 text-center text-sm">
      {t("No project yet — a ticket without one comes back as a document.")}
    </p>
  )
}

/* -- the declaration ------------------------------------------------------ */

export const projects = createViewResource<ProjectItem, ProjectItem, ProjectWrite>(PROJECTS, {
  name: "Projects",
  scope: SCOPE,
  path: "/api/projects",
  icon: FolderGit2,
  canList: true,
  canRead: true,
  canCreate: false,
  // A project page is made in Notion, or by a line in `config.toml`; what is
  // written from here is what an existing one says.
  canUpdate: true,
  canDelete: false,

  getCollection: async () => {
    const read = await api.projects()
    publish(read)
    return {
      data: createResourceCollection({
        id: "/api/projects",
        items: read.projects.map((project) => item(project)),
      }),
    } as never
  },
  getItem: async ({ id }) => {
    const wanted = String(id)
    try {
      const data = await one(wanted)
      refusal = ""
      return { data }
    } catch (error) {
      refusal = error instanceof Error ? error.message : String(error)
      throw error
    }
  },
  updateItem: async (patch) => {
    const id = String(patch.id ?? "")
    if (!isAPage(id))
      throw new Error(
        t("This project is a line in config.toml; it is changed in the settings.")
      )
    const written = await api.saveProject(id, {
      name: patch.name ?? "",
      repository: patch.repository ?? "",
      path: patch.path ?? "",
      content: patch.content ?? "",
    })
    // The list is drawn from what was last read, and a rename that only showed
    // on the page you renamed it on would be a rename made twice.
    await api.projects().then(publish)
    return { data: item(written) }
  },
  createItem: async () => {
    throw new Error("a project page is made on the board, not from the console")
  },
  removeItem: async () => {
    throw new Error("a project is not deleted from the console; its tickets point at it")
  },

  view: {
    form: rowForm,
    /* The two layouts. A variant's name is drawn as it is given and its id is
     * slugged from it where none is said, so the id is said here and the name
     * read from the dictionary as the tab is drawn: the address stays `cards`
     * in every language. */
    viewVariants: [
      {
        ...cardViewOptionFactory({ id: "cards", rowComponent: ProjectCard, grid: 3 }),
        get name() {
          return t("cards")
        },
      },
      {
        ...tableViewOptionFactory({ id: "table", behavior: { rowActions: [ActionList.read] } }),
        get name() {
          return t("table")
        },
      },
    ],
  },
  views: {
    [ActionList.list]: {
      name: "Projects",
      description:
        "What the tickets are about: where the work happens, and what conventions hold there. One with no repository is not a mistake — its tickets come back as a document.",
      // There is one way in, and it is the page: what a project is changed
      // through is the form that page opens.
      behavior: { rowActions: [ActionList.read] },
      components: { top: ProjectsTop, bottom: ProjectsFoot, noResult: NoProject },
    },
    [ActionList.read]: { name: "Project", viewComponent: ProjectPage },
    [ActionList.update]: {
      name: "Project",
      form: editForm,
      // Against the edge and at full height: the brief is the field that is
      // actually written here, and it is a page of text.
      behavior: { openIn: "drawer" },
    },
  },
})

/** Where the projects are, in the layout they were last worked in. */
export const projectsHref = () =>
  generateLinkByResource({
    resource: projects,
    resourceAction: ActionList.list,
    viewVariantId: layoutOf(PROJECTS),
  })

/** Where one project is. */
export const projectHref = (id: string) =>
  generateLinkByResource({ resource: projects, resourceAction: ActionList.read, id })
