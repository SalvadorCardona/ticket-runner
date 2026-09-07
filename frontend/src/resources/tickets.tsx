import * as React from "react"
import { LayoutGrid, MessageSquare } from "lucide-react"
import {
  ActionList,
  BooleanInputController,
  SelectInputController,
  TextAreaInputController,
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

import { EDGE, LABEL, TicketActions, TicketBadges, TicketLinks } from "@/components/console/ticket-bits"
import { TicketPage } from "@/components/console/ticket-page"
import { api } from "@/lib/api"
import { addTicket, boardOnce, currentBoard, patchTicket, subscribeBoard, useBoard } from "@/lib/board-store"
import { SCOPE } from "@/lib/resource-view"
import type { ColumnKey, Ticket, TicketDetail } from "@/lib/types"
import { cn } from "@/lib/utils"

/* The tickets, declared once for react-resource-view.
 *
 * One declaration says what the board is: where its rows come from (the
 * stream), what a card looks like (`TicketCard`), which columns it is laid out
 * in (the board's own), how a card is moved (a drop is a status change), what
 * a new ticket asks for (the create form), and what opening one shows (the
 * ticket page). The package does the rest — the list, the popup, the URL.
 */

export const TICKETS = "tickets"

/** A ticket as the views hold it: the row, and an IRI so the package can address it. */
export type TicketItem = Ticket & {
  "@id": string
  "@type": string
  content?: string
  /** The cost as a table cell reads it — the number is for the badges. */
  spent: string
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
})

/** The column's name, as the board spells it. */
export function columnName(key: string): string {
  return currentBoard()?.columns.find((column) => column.key === key)?.name || LABEL[key] || key
}

/* -- the forms ------------------------------------------------------------ */
/** What a new ticket asks for. Drawn by react-data-form, submitted to `createItem`. */
const createForm: FormInterface = {
  // The dialog already says "New ticket" over it.
  label: { submit: "Create" },
  inputs: {
    title: {
      label: "What has to be done, in one line",
      required: true,
      placeholder: "Retirer le bandeau du dashboard",
    },
    body: {
      label: "The brief",
      placeholder: "What must change, where, and how you will know it is done.",
      controller: TextAreaInputController,
    },
    project: {
      label: "Project",
      description: "A project with a repository gets a pull request; none at all gets a document.",
      controller: SelectInputController,
      getValueOptions: async () => {
        const { projects } = await api.projects().catch(() => ({ projects: [] }))
        return [
          { value: "", label: "no project — a document" },
          ...projects.map((project) => ({
            value: project.id,
            label: `${project.name} — ${project.kind}`,
          })),
        ]
      },
    },
    ready: {
      label: "Ready to run",
      description: "Off, and the ticket is a draft the runner leaves alone.",
      controller: BooleanInputController,
      defaultValue: true,
    },
  },
}

/** The columns of the table layout. Read only: the board is Notion's. */
const rowForm: FormInterface = {
  inputs: {
    title: { label: "Ticket", readonly: true },
    project: { label: "Project", readonly: true },
    status: { label: "Status", readonly: true },
    priority: { label: "Priority", readonly: true },
    model: { label: "Model", readonly: true },
    spent: { label: "Cost", readonly: true },
    scheduled: { label: "Scheduled", readonly: true },
  },
}

/* -- one card ------------------------------------------------------------- */

/** How a ticket is drawn on the board. The card is the way into the ticket's page. */
function TicketCard({ row }: RowComponentPropsInterface) {
  const ticket = row?.data as TicketItem | undefined
  const { resource } = useCurrentViewResourceContext()
  if (!ticket) return null
  const href = generateLinkByResource({ resource, resourceAction: ActionList.read, id: ticket.id })

  return (
    <div className={cn("-m-4 flex flex-col gap-2 rounded-2xl border-l-3 p-3", EDGE[ticket.column] ?? "border-l-border")}>
      <Link to={href} className="text-[0.93rem] leading-snug font-semibold hover:underline">
        {ticket.title}
      </Link>
      <TicketBadges ticket={ticket} />
      {ticket.progress ? (
        <p className="text-muted-foreground line-clamp-3 text-xs leading-relaxed">{ticket.progress}</p>
      ) : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Link
          to={href}
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs"
        >
          <MessageSquare className="size-3" />
          open
        </Link>
        <TicketLinks ticket={ticket} />
        <TicketActions ticket={ticket} className="-ml-1" />
      </div>
    </div>
  )
}

/* -- the board ------------------------------------------------------------ */

/** Nothing on screen: it asks the list to reread the store whenever the stream moves the board. */
function FollowsTheStream() {
  const { fetchData } = useCurrentViewResourceContext()
  const latest = React.useRef(fetchData)
  latest.current = fetchData
  React.useEffect(() => subscribeBoard(() => latest.current()), [])
  return null
}

/** A column's name as a heading: the board's own word, with a capital. */
const heading = (name: string) => name.charAt(0).toUpperCase() + name.slice(1)

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
          valueIdentifier={{ value: column.key, label: heading(column.name || LABEL[column.key]) }}
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
    viewVariants: [
      columnViewOptionFactory({
        name: "board",
        listComponent: BoardColumns,
        rowComponent: TicketCard,
        identifierKey: "column",
      }),
      tableViewOptionFactory({ name: "table", behavior: { rowActions: [ActionList.read] } }),
    ],
    components: { top: FollowsTheStream },
  },
  views: {
    [ActionList.list]: { name: "Board" },
    [ActionList.create]: {
      name: "New ticket",
      form: createForm,
      // Over the board rather than instead of it.
      behavior: { openIn: "popup" },
    },
    [ActionList.read]: { name: "Ticket", viewComponent: TicketPage },
  },
})

/** Where the board is. */
export const boardHref = () =>
  generateLinkByResource({ resource: tickets, resourceAction: ActionList.list })

/** Where a ticket is. */
export const ticketHref = (id: string) =>
  generateLinkByResource({ resource: tickets, resourceAction: ActionList.read, id })
