import * as React from "react"
import { CalendarClock, CalendarOff } from "lucide-react"
import {
  ActionList,
  MomentInputController,
  SelectInputController,
  SwitchInputController,
  useFormContext,
  type FormInterface,
  type InputControllerComponentInterface,
} from "react-data-form"
import {
  NoResultComponent,
  calendarViewOptionFactory,
  createResourceCollection,
  createViewResource,
  generateLinkByResource,
  tableViewOptionFactory,
  type RowInterface,
} from "react-resource-view"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { api, why } from "@/lib/api"
import { t } from "@/lib/i18n"
import { SCOPE, layoutOf, useLayoutInTheAddress } from "@/lib/resource-view"
import type { Schedule, Schedules } from "@/lib/types"

/* What comes back on its own, declared once for react-resource-view.
 *
 * It used to be a pane of its own: cards drawn here, a form written here, a
 * date formatted here into "in 6 days". Every one of those already exists in
 * the package the board and the projects are drawn with — so a schedule is a
 * resource like them, and what draws it is the package's table, its calendar,
 * its form and its empty page. Nothing on this screen is styled twice.
 *
 * Two layouts, and the pair is the point. **A table** to compare them, and to
 * turn one off: `Active` is the one cell that is not read-only, so unticking a
 * row in the list is the whole gesture — which is the gesture this feature was
 * designed around, since it stops everything without deleting a single row.
 * **A calendar** because the only question a schedule really answers is when
 * the next one lands, and `Next` is a date: the package lays the rows out by
 * day, week or month, and a row with no date is a row nothing is due from.
 *
 * What neither form offers is the three columns a *pass* writes back — `Next`,
 * `Last` and the ticket the last occurrence made. They are how the runner knows
 * an occurrence has been taken, and a console that let you edit them would let
 * you make an occurrence happen twice, or never. The table shows the first two,
 * read-only.
 *
 * The rows are asked for when the page is opened rather than watched like the
 * board: a schedule moves four times a day at the very most, and a tab left
 * open here has no business polling that database.
 */

export const SCHEDULES = "schedules"

/** A schedule as the views hold it: the row, and an IRI to address it by. */
export type ScheduleItem = Schedule & {
  "@id": string
  "@type": string
}

/** What the console writes about a schedule: the seven columns a row is written in. */
export interface ScheduleWrite {
  id?: string
  name?: string
  cadence?: string
  at?: string
  day?: string
  active?: boolean
  model?: string
  priority?: string
}

const item = (schedule: Schedule): ScheduleItem => ({
  ...schedule,
  "@id": `/api/schedules/${schedule.id}`,
  "@type": SCHEDULES,
})

/* -- what the list last read ---------------------------------------------- */

/* The payload says three things a row does not: whether the workspace has the
 * database at all, what that page is called, and whether `runner.schedule` is
 * on. All three are read outside the rows that came with them — the foot of the
 * page, the empty page, the button that writes a new row — so what the server
 * last said is kept here, the way the projects keep theirs.
 *
 * The refusal is kept with it rather than swallowed: "something went wrong" is
 * all a view component is handed, and a token that expired and a workspace
 * without that database are two different afternoons.
 */
interface LastRead {
  drawn: Schedules | null
  problem: string
}

let read: LastRead = { drawn: null, problem: "" }
const listeners = new Set<() => void>()

function publish(fresh: LastRead) {
  read = fresh
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** What the list last read, redrawn with it. */
function useSchedules(): LastRead {
  return React.useSyncExternalStore(subscribe, () => read)
}

/** The rows, and the three facts that travel with them. */
async function load(): Promise<Schedules> {
  try {
    const fresh = await api.schedules()
    publish({ drawn: fresh, problem: "" })
    return fresh
  } catch (error) {
    publish({ drawn: null, problem: why(error) })
    throw error
  }
}

/* -- the forms ------------------------------------------------------------- */

/** What a cadence may say. The same four `schedules.py` knows, and no free text. */
const CADENCES = ["Hourly", "Daily", "Weekly", "Monthly"]
const MODELS = ["opus", "sonnet", "haiku"]
const PRIORITIES = ["Urgent", "High", "Normal", "Low"]

/* A list of words as the package's select reads them, with the empty one first:
 * "nobody picked a cadence" is an answer, and a select with no option for it is
 * a field you cannot take back. */
const choices = (words: string[]) => [
  { value: "", label: "nothing said" },
  ...words.map((word) => ({ value: word, label: word })),
]

/* The six fields a schedule is written in.
 *
 * A label, the button and a select's options are translated by the package as
 * it draws them; the sentence under a field and the greyed example in it are
 * not — they are used as they are given. Those are read from the dictionary as
 * the field is drawn, which is what the getters are for: the declaration is
 * built once, and the language can change after it.
 */
const fields: FormInterface["inputs"] = {
  name: {
    label: "Schedule",
    get description() {
      return t("What the ticket it makes will be called. Every occurrence carries this name.")
    },
    required: true,
    get placeholder() {
      return t("Weekly dependency review")
    },
    validator: (value: unknown) => {
      if (!String(value ?? "").trim()) throw new Error(t("A schedule needs a name"))
      return value
    },
  },
  cadence: {
    label: "Cadence",
    controller: SelectInputController,
    valueOptions: choices(CADENCES),
  },
  at: {
    label: "At",
    get description() {
      return t("The hour, written 09:00. Empty, and the hour the pass runs at answers.")
    },
    placeholder: "09:00",
  },
  day: {
    label: "Day",
    get description() {
      return t("Which day a weekly or monthly one lands on.")
    },
    get placeholder() {
      return t("Monday, or 1 to 31")
    },
  },
  model: {
    label: "Model",
    controller: SelectInputController,
    valueOptions: choices(MODELS),
  },
  priority: {
    label: "Priority",
    controller: SelectInputController,
    valueOptions: choices(PRIORITIES),
  },
}

/* A new row, and the switch is deliberately not on it: a schedule is created
 * unticked whatever a form says, so offering the choice would be offering one
 * that is not taken. The form says so instead. */
const createForm: FormInterface = {
  label: {
    submit: "Create",
    get description() {
      return t("Created unticked: nothing is born until you turn it on.")
    },
  },
  inputs: fields,
}

const editForm: FormInterface = {
  label: { submit: "Save" },
  inputs: {
    ...fields,
    active: {
      label: "On",
      get description() {
        return t("Off, and nothing is born — the row is kept, and the hours with it.")
      },
      controller: SwitchInputController,
    },
  },
}

/* The name, and the way to the page it is written on.
 *
 * A schedule's page *body* is the brief of every ticket it makes — the one
 * thing about a schedule this console does not write — so a list that did not
 * lead there would be a list you leave to go and find the page by hand. The
 * package's own way of drawing a cell otherwise is a controller, and this is
 * the whole of it: the row's name, linked where the row says its page is.
 */
const PageLink: InputControllerComponentInterface = ({ formInput }) => {
  const { form } = useFormContext()
  const said = String(formInput.value ?? "")
  // The row the cell belongs to, which is what the form was built from: a
  // controller is handed its own field and nothing else.
  const url = String((form?.data as { url?: string } | undefined)?.url ?? "")
  if (!url) return <>{said}</>
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      className="underline-offset-2 hover:underline"
    >
      {said}
    </a>
  )
}

/* The columns of the table, and the fields the calendar's preview lists.
 *
 * Read-only but one: `active` carries the switch, and the package saves a cell
 * it is given a controller for — so turning a schedule off is one click in the
 * list rather than a form. `Next` and `Last` are dates, drawn as the package
 * draws a date; `Problem` is empty on every row that is fine, which is what
 * makes it worth a column of its own.
 *
 * Model and priority are not here: they are what the ticket inherits, they are
 * in the form that writes them, and two more columns would push the dates off
 * the edge of a pane that shares its screen with the console.
 */
const rowForm: FormInterface = {
  inputs: {
    name: { label: "Schedule", readonly: true, controller: PageLink },
    // The row's own word, and not the select the form offers: a cadence the
    // runner does not know is still what the board says, and a select asked for
    // a word it has no option for answers with the wrong one.
    cadence: { label: "Cadence", readonly: true },
    at: { label: "At", readonly: true },
    day: { label: "Day", readonly: true },
    active: { label: "On", controller: SwitchInputController },
    next: { label: "Next", readonly: true, controller: MomentInputController },
    last: { label: "Last", readonly: true, controller: MomentInputController },
    project: { label: "Project", readonly: true },
    problem: { label: "Problem", readonly: true },
  },
}

/* -- what sits around the list -------------------------------------------- */

/** How many of them are on, said where the list opens — and why nothing was read, where nothing was. */
function SchedulesTop() {
  const { drawn, problem } = useSchedules()
  useLayoutInTheAddress(SCHEDULES)
  if (problem)
    return (
      <Alert variant="destructive" className="mb-2">
        <AlertDescription>{problem}</AlertDescription>
      </Alert>
    )
  if (!drawn) return null
  const rows = drawn.schedules
  const active = rows.filter((schedule) => schedule.active && !schedule.problem).length
  return (
    <p className="text-muted-foreground mb-2 inline-flex items-center gap-1.5 font-mono text-[0.7rem]">
      <CalendarClock className="size-3.5" />
      {rows.length
        ? t("{{count}} of {{total}} on", {
            count: String(active),
            total: String(rows.length),
          })
        : t("nothing yet")}
    </p>
  )
}

/** One switch turns the whole calendar off, and a page of ticked rows that never fire is what it would otherwise read as. */
function SchedulesFoot() {
  const { drawn } = useSchedules()
  if (!drawn?.database || drawn.enabled) return null
  return (
    <Alert className="mt-4">
      {/* One paragraph, because the description lays its children out in a
          grid: two of them are two lines, and the sentence would start on the
          one after the key it is about. */}
      <AlertDescription>
        <p>
          <span className="font-mono">runner.schedule = false</span> —{" "}
          {t("none of this runs.")}
        </p>
      </AlertDescription>
    </Alert>
  )
}

/* Two ways this page has nothing to show, and they are two different things to
 * do about it: the workspace has no such database, or the database is there and
 * empty. The create button under the sentence is the package's, and it is gone
 * in the first case — `canCreate` answers for a board that has nowhere to write
 * a row to. */
function NoSchedule() {
  const { drawn } = useSchedules()
  // Named rather than left blank: an empty parameter is not substituted, so the
  // sentence would show the placeholder itself. See `react-mini-i18n`.
  const page = drawn?.page || "Schedules"
  return drawn && !drawn.database ? (
    <NoResultComponent
      icon={CalendarOff}
      title={t("Nothing repeats here")}
      body={() => (
        <>
          {t("This workspace has no “{{page}}” page.", { page })}{" "}
          <code className="font-mono text-xs">ticket-runner init &lt;page-url&gt;</code>{" "}
          {t("builds it.")}
        </>
      )}
    />
  ) : (
    <NoResultComponent
      icon={CalendarClock}
      title={t("Nothing repeats here yet")}
      body={() => <>{t("A row in the “{{page}}” database is a ticket that comes back.", { page })}</>}
    />
  )
}

/* -- the declaration ------------------------------------------------------ */

export const schedules = createViewResource<ScheduleItem, ScheduleItem, ScheduleWrite>(SCHEDULES, {
  name: "Schedules",
  scope: SCOPE,
  path: "/api/schedules",
  icon: CalendarClock,
  canList: true,
  // There is nothing about a schedule the row does not already say, and its own
  // page is on the board — which its name in the list leads to.
  canRead: false,
  // A board with no Schedules database has nowhere to write a row to, and the
  // package asks this every time it draws the button.
  canCreate: () => Boolean(read.drawn?.database),
  canUpdate: true,
  // A schedule that has fired is a page with a history; unticking it is what
  // the switch is for, and there is no endpoint that removes one.
  canDelete: false,

  getCollection: async () => {
    const fresh = await load()
    return {
      data: createResourceCollection({
        id: "/api/schedules",
        items: fresh.schedules.map(item),
      }),
    } as never
  },
  // There is no route for one schedule: the database is read whole, and cheaply.
  // Read again rather than taken from what is held, so a link opened cold — a
  // tab that has never listed anything — answers too.
  getItem: async ({ id }) => {
    const wanted = String(id)
    const held = read.drawn?.schedules.find((schedule) => schedule.id === wanted)
    if (held) return { data: item(held) }
    const fresh = await load()
    const found = fresh.schedules.find((schedule) => schedule.id === wanted)
    if (!found) throw new Error(t("This schedule is no longer on the board."))
    return { data: item(found) }
  },
  updateItem: async (patch) => {
    const id = String(patch.id ?? "")
    // Written field by field rather than as the row arrived: a row carries the
    // three columns a pass writes back, and the project it points at as a name
    // rather than as the page the column holds.
    await api.saveSchedule(id, {
      name: patch.name ?? "",
      cadence: patch.cadence ?? "",
      at: patch.at ?? "",
      day: patch.day ?? "",
      active: patch.active === true,
      model: patch.model ?? "",
      priority: patch.priority ?? "",
    })
    const fresh = await load()
    const found = fresh.schedules.find((schedule) => schedule.id === id)
    return { data: found ? item(found) : (patch as unknown as ScheduleItem) }
  },
  createItem: async (fresh) => {
    const made = await api.createSchedule({
      name: fresh.name ?? "",
      cadence: fresh.cadence ?? "",
      at: fresh.at ?? "",
      day: fresh.day ?? "",
      model: fresh.model ?? "",
      priority: fresh.priority ?? "",
    })
    const after = await load()
    const found = after.schedules.find((schedule) => schedule.id === made.id)
    return { data: found ? item(found) : ({ ...fresh, ...made } as unknown as ScheduleItem) }
  },
  removeItem: async () => {
    throw new Error("a schedule is not deleted from the console; unticking it stops it")
  },

  view: {
    form: rowForm,
    /* The two layouts. A variant's name is drawn as it is given and its id is
     * slugged from it where none is said, so the id is said here and the name
     * read from the dictionary as the tab is drawn: the address stays `table`
     * in every language. */
    viewVariants: [
      {
        ...tableViewOptionFactory({ id: "table" }),
        get name() {
          return t("table")
        },
      },
      {
        ...calendarViewOptionFactory({
          id: "calendar",
          dateKey: "next",
          titleKey: "name",
          // The month, because that is the span a cadence is read in — the day
          // and the week are a tab away, on the package's own switch.
          mode: "month",
          getIcon: (row: RowInterface<Record<string, unknown>>) =>
            row.data?.active ? CalendarClock : CalendarOff,
        }),
        get name() {
          return t("calendar")
        },
      },
    ],
  },
  views: {
    [ActionList.list]: {
      name: "Schedules",
      // Declared on the list rather than on the view every action inherits: a
      // `top` posted there is drawn over the create dialog too, and the count
      // of what is on belongs to the page, not to the form over it.
      components: { top: SchedulesTop, bottom: SchedulesFoot, noResult: NoSchedule },
      // What a schedule is, without naming where it is kept: the same console
      // draws a Notion workspace and a directory of Markdown files.
      description:
        "A row says what to make and how often; when the moment comes the runner writes the ticket into the ready column and steps back.",
      // The switch in the row is one gesture, the form is the other, and there
      // is no third: nothing here is read on a page of its own.
      behavior: { rowActions: [ActionList.update] },
    },
    [ActionList.create]: {
      name: "A ticket that comes back",
      label: { create: "New schedule" },
      form: createForm,
      // Over the list rather than instead of it: six short fields are not a
      // page, and the list behind them is what says whether the row is a
      // duplicate of one that already fires.
      behavior: { openIn: "popup" },
    },
    [ActionList.update]: {
      name: "A ticket that comes back",
      form: editForm,
      behavior: { openIn: "popup" },
    },
  },
})

/** Where the schedules are, in the layout they were last worked in. */
export const schedulesHref = () =>
  generateLinkByResource({
    resource: schedules,
    resourceAction: ActionList.list,
    viewVariantId: layoutOf(SCHEDULES),
  })
