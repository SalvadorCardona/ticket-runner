import * as React from "react"
import { LayoutGrid } from "lucide-react"
import {
  ActionList,
  BooleanInputController,
  SelectInputController,
  type FormInterface,
} from "react-data-form"
import {
  Link,
  RowWrapperColumnComponent,
  columnViewOptionFactory,
  createResourceCollection,
  createViewResource,
  generateLinkByResource,
  tableViewOptionFactory,
  useCurrentViewResourceContext,
  type ListComponentPropsInterface,
  type RowComponentPropsInterface,
} from "react-resource-view"

import { MarkdownInputController } from "@/components/console/markdown-editor"
import {
  EDGE,
  LABEL,
  SEED,
  TicketActions,
  TicketFoot,
  TicketTags,
  ago,
  lasted,
  when,
} from "@/components/console/ticket-bits"
import { TicketPage } from "@/components/console/ticket-page"
import { api } from "@/lib/api"
import { addTicket, boardOnce, currentBoard, patchTicket, subscribeBoard, useBoard } from "@/lib/board-store"
import { t } from "@/lib/i18n"
import { SCOPE, layoutOf, useLayoutInTheAddress } from "@/lib/resource-view"
import type { ColumnKey, Ticket, TicketDetail } from "@/lib/types"
import { cn } from "@/lib/utils"

/* The tickets, declared once for react-resource-view.
 *
 * One declaration says what the board is: where its rows come from (the
 * stream), what a card looks like (`TicketCard`), which columns it is laid out
 * in (the board's own), how a card is moved (a drop is a status change), what
 * a new ticket asks for (the create form), and what opening one shows (the
 * ticket page). The package does the rest — the list, its header, the panel a
 * form opens in, the URL.
 */

export const TICKETS = "tickets"

/** A ticket as the views hold it: the row, and an IRI so the package can address it. */
export type TicketItem = Ticket & {
  "@id": string
  "@type": string
  content?: string
  /** The cost as a table cell reads it — the number is for the badges. */
  spent: string
  /** How long the run took, in words. */
  took: string
  /** When it is due, written the way the console writes a date. */
  due: string
}

/** What the console writes about a ticket: a new one, or the column an old one moves to. */
export interface TicketWrite {
  id?: string
  column?: ColumnKey
  title?: string
  body?: string
  project?: string
  ready?: boolean
}

const item = (ticket: Ticket | TicketDetail): TicketItem => ({
  ...ticket,
  "@id": `/api/tickets/${ticket.id}`,
  "@type": TICKETS,
  spent: typeof ticket.cost === "number" && ticket.cost ? `$${ticket.cost.toFixed(2)}` : "",
  took: typeof ticket.duration === "number" && ticket.duration ? lasted(ticket.duration) : "",
  due: when(ticket.scheduled),
})

/** The column's name, as the board spells it. */
export function columnName(key: string): string {
  return (
    currentBoard()?.columns.find((column) => column.key === key)?.name || t(LABEL[key] ?? "") || key
  )
}

/* -- the forms ------------------------------------------------------------ */
/* What a new ticket asks for. Drawn by react-data-form, submitted to
 * `createItem`.
 *
 * A label and the button are translated by the package as it draws them; the
 * sentence under a field and the greyed example in it are not — they are used
 * as they are given. Those two are read from the dictionary here, as the field
 * is drawn, which is what the getters are for: the declaration is built once,
 * and the language can change after it.
 */
const createForm: FormInterface = {
  // The dialog already says "New ticket" over it.
  label: { submit: "Create" },
  inputs: {
    title: {
      label: "Title",
      get description() {
        return t("What has to be done, in one line. It is what the board shows.")
      },
      required: true,
      placeholder: "Retirer le bandeau du dashboard",
    },
    body: {
      label: "The brief",
      get description() {
        return t(
          "The whole of what the runner is told. Written on the ticket's page, and read from there."
        )
      },
      get placeholder() {
        return t("What must change, where, and how you will know it is done.")
      },
      controller: MarkdownInputController,
    },
    project: {
      label: "Project",
      get description() {
        return t("A project with a repository gets a pull request; none at all gets a document.")
      },
      controller: SelectInputController,
      getValueOptions: async () => {
        const { projects } = await api.projects().catch(() => ({ projects: [] }))
        return [
          { value: "", label: "no project — a document" },
          // The kind said the way the rest of the console says it: the list of
          // projects says "code work", and this said "code".
          ...projects.map((project) => ({
            value: project.id,
            label: `${project.name} — ${project.kind === "code" ? t("code work") : t("document work")}`,
          })),
        ]
      },
    },
    ready: {
      label: "Ready to run",
      get description() {
        return t("Off, and the ticket is a draft the runner leaves alone.")
      },
      controller: BooleanInputController,
      defaultValue: true,
    },
  },
}

/* The columns of the table layout. Read only: a ticket is moved on the board,
 * not typed into here. The headings go through the dictionary on their way to
 * the page, and the two cells that are a number on the card — what it cost and
 * how long it took — are read from the words `item` writes them in. */
const rowForm: FormInterface = {
  inputs: {
    title: { label: "Ticket", readonly: true },
    project: { label: "Project", readonly: true },
    status: { label: "Status", readonly: true },
    priority: { label: "Priority", readonly: true },
    model: { label: "Model", readonly: true },
    spent: { label: "Cost", readonly: true },
    took: { label: "Took", readonly: true },
    due: { label: "Scheduled", readonly: true },
  },
}

/* -- one card ------------------------------------------------------------- */

/* How a ticket is drawn on the board. The card is the way into the ticket's
 * page — its title is the link, and so is the id over it.
 *
 * Read top to bottom it answers, in order: which one is this, how long has it
 * been sitting there, what is it, what is said about it, what is it doing,
 * where does the work go and what has it cost. The `-m-4` is the frame
 * react-resource-view draws around every record being pushed back out of the
 * way: the coloured edge has to be the card's own edge, not a stripe inside a
 * second border.
 */
function TicketCard({ row }: RowComponentPropsInterface) {
  const ticket = row?.data as TicketItem | undefined
  const { resource } = useCurrentViewResourceContext()
  if (!ticket) return null
  const href = generateLinkByResource({ resource, resourceAction: ActionList.read, id: ticket.id })

  return (
    <div
      className={cn(
        "-m-4 flex flex-col gap-2.5 rounded-2xl border-l-3 p-3.5",
        EDGE[ticket.column] ?? "border-l-border"
      )}
    >
      <div className="flex items-center gap-2 font-mono text-[0.7rem]">
        <Link to={href} className="font-medium tracking-wide hover:underline">
          #{ticket.short}
        </Link>
        <span className="flex-1" />
        <span className="text-muted-foreground">{ago(ticket.created)}</span>
      </div>

      <Link to={href} className="text-[0.93rem] leading-snug font-semibold hover:underline">
        {ticket.title}
      </Link>

      <TicketTags ticket={ticket} />

      {ticket.progress ? (
        <p className="text-muted-foreground line-clamp-3 text-xs leading-relaxed">
          {ticket.progress}
        </p>
      ) : null}

      <TicketActions ticket={ticket} className="-mx-1" />
      <TicketFoot ticket={ticket} />
    </div>
  )
}

/* -- the board ------------------------------------------------------------ */

/* What sits above whatever react-resource-view is drawing.
 *
 * One job, and it draws nothing: it asks the list to reread the store whenever
 * the stream moves the board. The heading is the package's own since 0.7.0 —
 * the resource's icon, the view's name and the line under it — so the board no
 * longer opens with a `PageHead` of its own, which would say it all twice.
 */
function BoardTop() {
  const { fetchData } = useCurrentViewResourceContext()
  useLayoutInTheAddress(TICKETS)
  const latest = React.useRef(fetchData)
  latest.current = fetchData
  React.useEffect(() => subscribeBoard(() => latest.current()), [])
  return null
}

/* The board's own empty line.
 *
 * Left to the package, a board with nothing on it said "No results yet —
 * nothing matched your search", in English, on a console set to French and on a
 * page where nobody has searched for anything. An empty board is not a failed
 * search: it is a board waiting for its first ticket, and the button that makes
 * one is already at the top of the page. */
function NoTicket() {
  return (
    <p className="text-muted-foreground rounded-lg border border-dashed px-3 py-6 text-center text-sm">
      {t("Nothing on the board yet — a ticket moved to the ready column is a session that starts.")}
    </p>
  )
}

/** A column's name as a heading: the board's own word, with a capital, under its colour. */
function heading(key: string, name: string) {
  const said = name.charAt(0).toUpperCase() + name.slice(1)
  return (
    <span className="inline-flex items-center gap-2">
      <span className={cn("size-1.5 shrink-0 rounded-full", SEED[key] ?? "bg-muted-foreground")} />
      {said}
    </span>
  )
}

/** The board's columns, in the board's order and words, each a drop target. */
function BoardColumns({ rows = [] }: ListComponentPropsInterface) {
  const board = useBoard()
  const [dragging, setDragging] = React.useState(false)

  const columns = board.columns.filter(
    (column) =>
      // Offered only where the runner would honour a card dropped there.
      (column.key !== "validated" || board.validate) &&
      // A column of what is elsewhere is drawn only when something is.
      (column.key !== "other" || rows.some((row) => row.data?.column === "other"))
  )

  return (
    <div className="scroll-thin flex items-start gap-3 overflow-x-auto pb-2">
      {columns.map((column) => (
        <RowWrapperColumnComponent
          key={column.key}
          identifierKey="column"
          valueIdentifier={{
            value: column.key,
            label: heading(column.key, column.name || t(LABEL[column.key] ?? "")),
          }}
          isDragging={dragging}
          handleDragging={setDragging}
          rows={rows}
        />
      ))}
    </div>
  )
}

/* -- the declaration ------------------------------------------------------ */

export const tickets = createViewResource<TicketItem, TicketItem, TicketWrite>(TICKETS, {
  name: "Board",
  scope: SCOPE,
  path: "/api/board",
  icon: LayoutGrid,
  canList: true,
  canRead: true,
  canCreate: true,
  canUpdate: false,
  canDelete: false,

  // The rows are the stream's; asking Notion again here would be asking it
  // for what every open tab already holds.
  getCollection: async () => {
    const board = await boardOnce()
    return {
      data: createResourceCollection({ id: "/api/board", items: board.tickets.map(item) }),
    } as never
  },
  getItem: async ({ id }) => ({ data: item(await api.ticket(String(id))) }),
  // A card dropped in a column is a status change, and nothing else about a
  // ticket is written from the board.
  updateItem: async (patch) => {
    const id = String(patch.id)
    const column = patch.column as ColumnKey | undefined
    const before = currentBoard()?.tickets.find((ticket) => ticket.id === id)
    if (column && before && column !== before.column) {
      patchTicket(id, { column })
      await api.setStatus(id, column)
    }
    const after = currentBoard()?.tickets.find((ticket) => ticket.id === id) ?? before
    return { data: after ? item(after) : (patch as unknown as TicketItem) }
  },
  createItem: async (fresh) => {
    const made = await api.createTicket({
      title: String(fresh.title ?? ""),
      body: String(fresh.body ?? ""),
      project: String(fresh.project ?? ""),
      ready: fresh.ready !== false,
    })
    const projects = await api.projects().catch(() => ({ projects: [] }))
    const project = projects.projects.find((candidate) => candidate.id === fresh.project)
    const card: Ticket = {
      id: made.id.replace(/-/g, ""),
      short: made.id.replace(/-/g, "").slice(-8),
      title: made.title,
      url: "",
      status: "",
      column: fresh.ready === false ? "other" : "ready",
      project: project?.name ?? "",
      kind: project?.kind ?? "",
      priority: "",
      model: "",
      progress: "",
      runner: "",
      pull_request: "",
      session: "",
      session_link: "",
      cost: null,
      duration: null,
      scheduled: "",
      created: new Date().toISOString(),
    }
    addTicket(card)
    return { data: item(card) }
  },
  removeItem: async () => {
    throw new Error("a ticket is not deleted from the console; Notion keeps it")
  },

  view: {
    name: "Board",
    form: rowForm,
    /* The two tabs over the list. A variant's name is drawn as it is given and
     * its id is slugged from it where none is said, so the id is said here and
     * the name read from the dictionary as the tab is drawn: the address stays
     * `board` in every language. */
    viewVariants: [
      {
        ...columnViewOptionFactory({
          id: "board",
          listComponent: BoardColumns,
          rowComponent: TicketCard,
          identifierKey: "column",
        }),
        get name() {
          return t("board")
        },
      },
      {
        ...tableViewOptionFactory({ id: "table", behavior: { rowActions: [ActionList.read] } }),
        get name() {
          return t("table")
        },
      },
    ],
    components: { top: BoardTop },
  },
  views: {
    // The name and the line under it are what the list's own header says, next
    // to the resource's icon: the board opens on its own words.
    [ActionList.list]: {
      name: "Board",
      // What the board is, without naming where it is kept: the same console
      // draws a Notion workspace and a directory of Markdown files, and a
      // sentence that names one of them is wrong half the time.
      description:
        "Your board, live. Drop a card in another column and the runner is told.",
      // A row of the table opens the ticket, as a card does. Without it the
      // table is a list you cannot get out of.
      behavior: { rowActions: [ActionList.read] },
      components: { noResult: NoTicket },
    },
    [ActionList.create]: {
      name: "New ticket",
      form: createForm,
      // Over the board rather than instead of it, and against the edge rather
      // than in the middle of it: a brief is written at full height.
      behavior: { openIn: "drawer" },
    },
    [ActionList.read]: { name: "Ticket", viewComponent: TicketPage },
  },
})

/** Where the board is, in the layout it was last worked in. */
export const boardHref = () =>
  generateLinkByResource({
    resource: tickets,
    resourceAction: ActionList.list,
    viewVariantId: layoutOf(TICKETS),
  })

/** Where a ticket is. */
export const ticketHref = (id: string) =>
  generateLinkByResource({ resource: tickets, resourceAction: ActionList.read, id })
