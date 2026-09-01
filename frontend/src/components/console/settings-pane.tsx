import * as React from "react"
import { ChevronRight } from "lucide-react"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useConsole } from "@/hooks/use-console"
import { api, why } from "@/lib/api"
import type { ProjectPath, SettingField, Settings, SettingValue } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Rich } from "./text"

/* The settings tab.
 *
 * Drawn from what the server says the configuration holds, never from a list
 * kept here: a setting the runner gains appears in this tab the day it is
 * described, and one it loses stops being offered.
 *
 * A field carries three states, not two — what the file says, what the runner
 * falls back on when it says nothing, and what you have just typed. Clearing a
 * field is how you go back to the third, and it removes the line rather than
 * writing an empty one. So `edited` holds only what you actually touched: a
 * field left alone is a line the file keeps, comment and all — and a token you
 * did not retype is a token that never left the machine.
 */

/** Radix has no empty-string value, and "the file says nothing" needs one. */
const UNSET = "default:unset"

// The command each section is checked with. The CLI already knows how to say
// whether a token works; the settings tab does not need a second opinion.
const CHECKS: Record<string, [string, string]> = {
  notion: ["doctor", "does that token reach your board?"],
  notify: ["notify", "send yourself a test message"],
  runner: ["enable", "apply the interval to the timer"],
}

// Open where somebody arriving would start, folded where they would not:
// seventy fields at once is a file, not a page.
const OPEN = new Set(["notion", "runner", "notify"])

function same(left: unknown, right: unknown): boolean {
  if (Array.isArray(left) && Array.isArray(right))
    return left.length === right.length && left.every((item, index) => item === right[index])
  return left === right
}

function Field({
  field,
  edited,
  remember,
}: {
  field: SettingField
  edited: Map<string, SettingValue>
  remember: (name: string, value: SettingValue, initial: SettingValue) => void
}) {
  const [forgotten, setForgotten] = React.useState(false)
  const touched = edited.has(field.name)

  const control = () => {
    if (field.kind === "bool") {
      // Three answers, because the file has three: yes, no, and nothing — which
      // is the runner's own default and says so.
      const shown = touched ? edited.get(field.name) : field.value
      return (
        <Select
          value={shown === null || shown === undefined ? UNSET : String(shown)}
          onValueChange={(value) =>
            remember(
              field.name,
              value === UNSET ? null : value === "true",
              field.value as SettingValue
            )
          }
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNSET}>default · {field.fallback ? "yes" : "no"}</SelectItem>
            <SelectItem value="true">yes</SelectItem>
            <SelectItem value="false">no</SelectItem>
          </SelectContent>
        </Select>
      )
    }

    if (field.kind === "choice") {
      const initial = (field.value as string) || ""
      const shown = touched ? ((edited.get(field.name) as string) ?? "") : initial
      return (
        <Select
          value={shown || UNSET}
          onValueChange={(value) =>
            remember(field.name, value === UNSET ? null : value, initial)
          }
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNSET}>default · {String(field.fallback)}</SelectItem>
            {field.choices.map((choice) => (
              <SelectItem key={choice} value={choice}>
                {choice}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )
    }

    if (field.kind === "events") {
      const fallback = Array.isArray(field.fallback) ? (field.fallback as string[]) : []
      const initial = field.value as string[] | null
      const chosen = new Set<string>(
        touched ? ((edited.get(field.name) as string[]) ?? []) : (initial ?? fallback)
      )
      return (
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {field.choices.map((choice) => (
            <Label key={choice} className="text-muted-foreground cursor-pointer font-normal">
              <Checkbox
                checked={chosen.has(choice)}
                onCheckedChange={(value) => {
                  const next = new Set(chosen)
                  if (value === true) next.add(choice)
                  else next.delete(choice)
                  remember(
                    field.name,
                    field.choices.filter((name) => next.has(name)),
                    initial
                  )
                }}
              />
              {choice}
            </Label>
          ))}
        </div>
      )
    }

    if (field.kind === "secret") {
      const shown = touched ? edited.get(field.name) : ""
      return (
        <div className="flex items-center gap-2">
          <Input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={typeof shown === "string" ? shown : ""}
            placeholder={
              forgotten ? "not set" : field.preview ? `set · ends ${field.preview}` : "not set"
            }
            onChange={(event) => {
              setForgotten(false)
              remember(field.name, event.target.value.trim(), "")
            }}
          />
          {field.preview && !forgotten ? (
            // Emptying the box means "I did not retype it", so forgetting a
            // token has to be a gesture of its own rather than the absence of
            // one.
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setForgotten(true)
                remember(field.name, null, "")
              }}
            >
              forget
            </Button>
          ) : null}
        </div>
      )
    }

    const initial = field.value === null ? "" : String(field.value)
    const held = touched ? edited.get(field.name) : field.value
    return (
      <Input
        type={field.kind === "int" ? "number" : "text"}
        autoComplete="off"
        spellCheck={false}
        value={held === null || held === undefined ? "" : String(held)}
        placeholder={
          field.fallback === "" || field.fallback === null
            ? "nothing"
            : `default · ${String(field.fallback)}`
        }
        onChange={(event) => {
          const text = event.target.value.trim()
          if (field.kind === "int")
            remember(field.name, text === "" ? null : Number(text), field.value as SettingValue)
          else remember(field.name, text, initial)
        }}
      />
    )
  }

  return (
    <div className={cn("space-y-1.5", field.kind === "events" && "col-span-full")}>
      <span className="text-sm font-medium">{field.label}</span>
      {control()}
      {field.help ? (
        <p className="text-muted-foreground text-xs leading-relaxed">
          <Rich text={field.help} />
        </p>
      ) : null}
      {field.after ? (
        <p className="text-muted-foreground text-xs">
          takes effect once <Rich text={field.after} />
        </p>
      ) : null}
    </div>
  )
}

function ProjectRows({
  rows,
  setRows,
}: {
  rows: ProjectPath[]
  setRows: (rows: ProjectPath[]) => void
}) {
  const change = (index: number, patch: Partial<ProjectPath>) =>
    setRows(rows.map((row, at) => (at === index ? { ...row, ...patch } : row)))

  return (
    <div className="space-y-2">
      {rows.map((row, index) => (
        <div key={index} className="flex flex-wrap items-center gap-2">
          <Input
            className="min-w-40 flex-1"
            value={row.name}
            placeholder="the project, as Notion names it"
            onChange={(event) => change(index, { name: event.target.value })}
          />
          <Input
            className="min-w-40 flex-1"
            value={row.path}
            placeholder="~/workspace/that-repository"
            onChange={(event) => change(index, { path: event.target.value })}
          />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setRows(rows.filter((_, at) => at !== index))}
          >
            remove
          </Button>
        </div>
      ))}
      {!rows.length ? (
        <p className="text-muted-foreground text-sm">
          No mapping here — the project pages carry it.
        </p>
      ) : null}
      <Button
        variant="outline"
        size="sm"
        onClick={() => setRows([...rows, { name: "", path: "" }])}
      >
        add a project
      </Button>
    </div>
  )
}

export function SettingsPane({ onCheck }: { onCheck: (verb: string) => void }) {
  const { say, reloadState } = useConsole()
  const [drawn, setDrawn] = React.useState<Settings | null>(null)
  const [edited, setEdited] = React.useState<Map<string, SettingValue>>(new Map())
  const [rows, setRows] = React.useState<ProjectPath[] | null>(null)
  const [note, setNote] = React.useState<{ text: string; bad: boolean } | null>(null)
  const [saving, setSaving] = React.useState(false)

  const load = React.useCallback(async () => {
    try {
      const payload = await api.settings()
      setDrawn(payload)
      setEdited(new Map())
      setRows(null)
    } catch (error) {
      say("error", `could not read the configuration: ${why(error)}`)
    }
  }, [say])

  React.useEffect(() => {
    void load()
  }, [load])

  // Another tab saved, or `ticket-runner config` did. Redraw — unless this tab
  // is in the middle of an edit, which is not something to take away from you.
  const dirty = edited.size + (rows ? 1 : 0)
  const dirtyRef = React.useRef(dirty)
  dirtyRef.current = dirty
  React.useEffect(() => {
    const listener = () => {
      if (!dirtyRef.current) void load()
    }
    window.addEventListener("ticket-runner:settings", listener)
    return () => window.removeEventListener("ticket-runner:settings", listener)
  }, [load])

  React.useEffect(() => {
    // A problem stays until it is read; a confirmation has been read by then.
    if (!note || note.bad) return
    const timer = window.setTimeout(() => setNote(null), 8000)
    return () => window.clearTimeout(timer)
  }, [note])

  const remember = React.useCallback(
    (name: string, value: SettingValue, initial: SettingValue) => {
      setEdited((current) => {
        const next = new Map(current)
        if (same(value, initial)) next.delete(name)
        else next.set(name, value)
        return next
      })
    },
    []
  )

  const save = async () => {
    if (!drawn) return
    setSaving(true)
    try {
      const payload: {
        settings: Record<string, SettingValue>
        projects?: ProjectPath[]
      } = { settings: Object.fromEntries(edited) }
      if (rows) payload.projects = rows
      const result = await api.saveSettings(payload)
      await load()
      await reloadState()
      // A 200 is the server saying it wrote; what it wrote is a courtesy, and a
      // save is not going to be reported as a failure over a missing list.
      const written = result.saved ?? []
      const after = result.after ?? []
      setNote({
        bad: false,
        text: written.length
          ? `Saved ${written.length === 1 ? "one setting" : `${written.length} settings`}: ` +
            `${written.join(", ")}.` +
            (after.length ? ` Takes effect once ${after.join("; ")}.` : "")
          : "Nothing to save — the file already said that.",
      })
    } catch (error) {
      // On the settings tab, not in the transcript: on a phone the console is a
      // tab away, and a save you have to go looking for is a save you doubt.
      setNote({ bad: true, text: `Not saved: ${why(error)}` })
    } finally {
      setSaving(false)
    }
  }

  if (!drawn)
    return <p className="text-muted-foreground p-3.5 text-sm">Reading the configuration…</p>

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-3.5">
        <div className="mb-4">
          <h2 className="text-base font-semibold">Settings</h2>
          <p className="text-muted-foreground mt-0.5 font-mono text-xs">{drawn.path}</p>
          <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
            A field left blank says nothing, and the runner&rsquo;s own default answers &mdash;
            shown greyed beside it. Your tokens stay on the machine: they are never sent to this
            page.
          </p>
        </div>

        {drawn.problem ? (
          <Alert variant="destructive" className="mb-3">
            <AlertDescription>{drawn.problem}</AlertDescription>
          </Alert>
        ) : null}

        {note ? (
          <Alert variant={note.bad ? "destructive" : "success"} className="mb-3">
            <AlertDescription>
              <Rich text={note.text} />
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="space-y-2.5">
          {drawn.sections.map((section) => {
            const check = CHECKS[section.key]
            return (
              <Collapsible
                key={section.key}
                defaultOpen={OPEN.has(section.key)}
                className="bg-card rounded-xl border"
              >
                <div className="flex items-center gap-2 px-3 py-2.5">
                  <CollapsibleTrigger className="group flex flex-1 cursor-pointer items-center gap-2 text-left">
                    <ChevronRight className="text-muted-foreground size-4 transition-transform group-data-[state=open]:rotate-90" />
                    <span className="text-sm font-semibold">{section.title}</span>
                  </CollapsibleTrigger>
                  {check ? (
                    <Button
                      variant="outline"
                      size="xs"
                      title={check[1]}
                      onClick={() => onCheck(check[0])}
                    >
                      &gt; {check[0]}
                    </Button>
                  ) : null}
                </div>
                <CollapsibleContent className="space-y-3 px-3 pb-3.5">
                  <p className="text-muted-foreground text-xs leading-relaxed">
                    <Rich text={section.blurb} />
                  </p>
                  {section.pairs === "projects" ? (
                    <ProjectRows
                      rows={rows ?? drawn.projects.map((item) => ({ ...item }))}
                      setRows={setRows}
                    />
                  ) : (
                    <div className="grid gap-3.5 [grid-template-columns:repeat(auto-fill,minmax(17rem,1fr))]">
                      {section.fields.map((field) => (
                        <Field
                          key={field.name}
                          field={field}
                          edited={edited}
                          remember={remember}
                        />
                      ))}
                    </div>
                  )}
                </CollapsibleContent>
              </Collapsible>
            )
          })}
        </div>
      </div>

      {dirty ? (
        <div className="bg-card flex items-center gap-2 border-t px-3.5 py-2.5">
          <span className="text-muted-foreground text-xs">
            {dirty === 1 ? "one change, unsaved" : `${dirty} changes, unsaved`}
          </span>
          <span className="flex-1" />
          <Button variant="outline" onClick={load} disabled={saving}>
            revert
          </Button>
          <Button onClick={save} disabled={saving}>
            {saving ? "saving…" : "Save"}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
