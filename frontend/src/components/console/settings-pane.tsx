import * as React from "react"
import { ChevronRight, X } from "lucide-react"

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
import { t as translate, useT } from "@/lib/i18n"
import type { ProjectPath, SettingField, Settings, SettingValue } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Eyebrow, PageHead } from "./frame"
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
 *
 * Down the left is the list of sections, which is how a page of seventy fields
 * stops being a file: it says what is in here, which parts are open, and how
 * many of your unsaved changes are hiding in a part you have folded away.
 *
 * What a field is called and the sentence under it are the server's — one entry
 * per key in `web/settings.py` — and they go through the dictionary on their
 * way to the page, like everything else the console says. A description nobody
 * has translated is drawn as it was written, which is the file's own words and
 * no worse than what was there before.
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
  const t = useT()
  const [forgotten, setForgotten] = React.useState(false)
  const touched = edited.has(field.name)
  const id = `setting-${field.name}`

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
          <SelectTrigger id={id} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNSET}>
              {t("default · {{value}}", { value: field.fallback ? t("yes") : t("no") })}
            </SelectItem>
            <SelectItem value="true">{t("yes")}</SelectItem>
            <SelectItem value="false">{t("no")}</SelectItem>
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
          <SelectTrigger id={id} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={UNSET}>
              {/* A default nobody wrote is still a line in the list, and an
                  empty `{{value}}` would be read as a key rather than as
                  nothing at all. */}
              {t("default · {{value}}", { value: String(field.fallback) || "—" })}
            </SelectItem>
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
        <div className="flex flex-wrap gap-2">
          {field.choices.map((choice) => (
            // A checkbox in a box of its own, because a row of bare checkboxes
            // is a row where the thing you can click is the word and the word
            // does not look clickable.
            <Label
              key={choice}
              className={cn(
                "cursor-pointer rounded-lg border px-2.5 py-1.5 text-xs font-normal transition-colors",
                chosen.has(choice)
                  ? "border-primary/40 bg-primary/10 text-foreground"
                  : "bg-field text-muted-foreground hover:text-foreground"
              )}
            >
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
            id={id}
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={typeof shown === "string" ? shown : ""}
            placeholder={
              forgotten || !field.preview
                ? t("not set")
                : t("set · ends {{preview}}", { preview: field.preview })
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
              {t("forget")}
            </Button>
          ) : null}
        </div>
      )
    }

    const initial = field.value === null ? "" : String(field.value)
    const held = touched ? edited.get(field.name) : field.value
    return (
      <Input
        id={id}
        type={field.kind === "int" ? "number" : "text"}
        autoComplete="off"
        spellCheck={false}
        value={held === null || held === undefined ? "" : String(held)}
        placeholder={
          field.fallback === "" || field.fallback === null
            ? t("nothing")
            : t("default · {{value}}", { value: String(field.fallback) })
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
    <div className={cn("min-w-0", field.kind === "events" && "col-span-full")}>
      <div className="mb-1.5 flex items-center gap-1.5">
        <Label htmlFor={id} className="text-sm font-medium">
          {t(field.label)}
        </Label>
        {/* Where you changed something, said where you changed it: on a page
            this long, a diff you have to hunt for is a diff you distrust. */}
        {touched ? (
          <span className="bg-primary/15 text-primary rounded px-1.5 py-0.5 font-mono text-[0.6rem] font-semibold tracking-wide uppercase">
            {t("edited")}
          </span>
        ) : null}
      </div>
      {control()}
      {field.help ? (
        <p className="text-muted-foreground mt-1.5 text-xs leading-relaxed">
          <Rich text={t(field.help)} />
        </p>
      ) : null}
      {field.after ? (
        <p className="text-muted-foreground mt-1 text-xs">
          {t("takes effect once")} <Rich text={t(field.after)} />
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
  const t = useT()
  const change = (index: number, patch: Partial<ProjectPath>) =>
    setRows(rows.map((row, at) => (at === index ? { ...row, ...patch } : row)))

  return (
    <div className="space-y-2">
      {rows.length ? (
        <div className="text-muted-foreground hidden gap-2 px-1 sm:flex">
          <Eyebrow className="flex-1">{t("the project, as Notion names it")}</Eyebrow>
          <Eyebrow className="flex-1">{t("where it is on this machine")}</Eyebrow>
          <span className="w-8" />
        </div>
      ) : null}
      {rows.map((row, index) => (
        <div key={index} className="flex flex-wrap items-center gap-2">
          <Input
            className="min-w-40 flex-1"
            value={row.name}
            placeholder={t("the project, as Notion names it")}
            onChange={(event) => change(index, { name: event.target.value })}
          />
          <Input
            className="min-w-40 flex-1 font-mono text-xs"
            value={row.path}
            placeholder="~/workspace/that-repository"
            onChange={(event) => change(index, { path: event.target.value })}
          />
          <Button
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-destructive shrink-0"
            aria-label={t("remove {{project}}", { project: row.name || t("this project") })}
            onClick={() => setRows(rows.filter((_, at) => at !== index))}
          >
            <X />
          </Button>
        </div>
      ))}
      {!rows.length ? (
        <p className="text-muted-foreground rounded-lg border border-dashed px-3 py-6 text-center text-sm">
          {t("No mapping here — the project pages carry it.")}
        </p>
      ) : null}
      <Button
        variant="outline"
        size="sm"
        onClick={() => setRows([...rows, { name: "", path: "" }])}
      >
        {t("add a project")}
      </Button>
    </div>
  )
}

export function SettingsPane({ onCheck }: { onCheck: (verb: string) => void }) {
  const { say, reloadState } = useConsole()
  const t = useT()
  const [drawn, setDrawn] = React.useState<Settings | null>(null)
  const [edited, setEdited] = React.useState<Map<string, SettingValue>>(new Map())
  const [rows, setRows] = React.useState<ProjectPath[] | null>(null)
  const [note, setNote] = React.useState<{ text: string; bad: boolean } | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [open, setOpen] = React.useState<Set<string>>(OPEN)

  const load = React.useCallback(async () => {
    try {
      const payload = await api.settings()
      setDrawn(payload)
      setEdited(new Map())
      setRows(null)
    } catch (error) {
      say("error", translate("could not read the configuration: {{why}}", { why: why(error) }))
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

  const toggle = (key: string, shown: boolean) =>
    setOpen((current) => {
      const next = new Set(current)
      if (shown) next.add(key)
      else next.delete(key)
      return next
    })

  // From the rail: a section you asked for is a section you want open and in
  // front of you, whether or not it was folded when you asked.
  const jump = (key: string) => {
    toggle(key, true)
    window.requestAnimationFrame(() =>
      document.getElementById(`section-${key}`)?.scrollIntoView({ block: "start" })
    )
  }

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
      // The server says what has to happen in the same words the fields do, so
      // the sentence is translated the same way they are.
      const after = (result.after ?? []).map((one) => translate(one))
      const how =
        written.length === 1
          ? translate("one setting")
          : translate("{{count}} settings", { count: String(written.length) })
      setNote({
        bad: false,
        text: written.length
          ? translate("Saved {{how}}: {{names}}.", { how, names: written.join(", ") }) +
            (after.length
              ? " " + translate("Takes effect once {{after}}.", { after: after.join("; ") })
              : "")
          : translate("Nothing to save — the file already said that."),
      })
    } catch (error) {
      // On the settings tab, not in the transcript: on a phone the console is a
      // tab away, and a save you have to go looking for is a save you doubt.
      setNote({ bad: true, text: translate("Not saved: {{why}}", { why: why(error) }) })
    } finally {
      setSaving(false)
    }
  }

  if (!drawn)
    return <p className="text-muted-foreground p-3.5 text-sm">{t("Reading the configuration…")}</p>

  /** How many of your unsaved changes are in this section. */
  const changed = (key: string) => {
    const section = drawn.sections.find((item) => item.key === key)
    if (!section) return 0
    if (section.pairs === "projects") return rows ? 1 : 0
    return section.fields.filter((field) => edited.has(field.name)).length
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-3.5 sm:p-5">
        <PageHead
          crumbs={[t("workspace"), t("settings")]}
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

        {note ? (
          <Alert variant={note.bad ? "destructive" : "success"} className="mb-3">
            <AlertDescription>
              <Rich text={note.text} />
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="grid items-start gap-5 lg:grid-cols-[13rem_minmax(0,1fr)]">
          {/* The rail: what this file holds, in one screen. Hidden where there
              is no column to spare for it — the sections themselves are the
              same list, only taller. */}
          <nav className="sticky top-0 hidden flex-col gap-0.5 lg:flex">
            <Eyebrow className="mb-2 px-2">{t("sections")}</Eyebrow>
            {drawn.sections.map((section) => {
              const count = changed(section.key)
              return (
                <button
                  key={section.key}
                  type="button"
                  onClick={() => jump(section.key)}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors",
                    open.has(section.key)
                      ? "bg-sidebar-accent text-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  <span className="min-w-0 flex-1 truncate">{t(section.title)}</span>
                  {count ? (
                    <span className="bg-primary/15 text-primary rounded px-1.5 font-mono text-[0.65rem] font-semibold tabular-nums">
                      {count}
                    </span>
                  ) : null}
                </button>
              )
            })}
          </nav>

          <div className="min-w-0 space-y-3">
            {drawn.sections.map((section) => {
              const check = CHECKS[section.key]
              const count = changed(section.key)
              return (
                <Collapsible
                  key={section.key}
                  id={`section-${section.key}`}
                  open={open.has(section.key)}
                  onOpenChange={(shown) => toggle(section.key, shown)}
                  className="bg-card scroll-mt-3 rounded-xl border"
                >
                  <div className="flex items-start gap-2 px-4 pt-3.5 pb-3">
                    <CollapsibleTrigger className="group flex min-w-0 flex-1 cursor-pointer items-start gap-2 text-left">
                      <ChevronRight className="text-muted-foreground mt-0.5 size-4 shrink-0 transition-transform group-data-[state=open]:rotate-90" />
                      <span className="min-w-0">
                        {/* The key over the title, unless the key *is* the
                            title said twice — "NOTION / Notion" is a heading
                            that has nothing to add. */}
                        {section.key.toLowerCase() !== section.title.toLowerCase() ? (
                          <Eyebrow className="mb-1 block">{section.key}</Eyebrow>
                        ) : null}
                        <span className="block text-base leading-tight font-semibold tracking-[-0.01em]">
                          {t(section.title)}
                        </span>
                      </span>
                    </CollapsibleTrigger>
                    {count ? (
                      <span className="bg-primary/15 text-primary mt-0.5 shrink-0 rounded px-1.5 py-0.5 font-mono text-[0.65rem] font-semibold tabular-nums">
                        {count}
                      </span>
                    ) : null}
                    {check ? (
                      <Button
                        variant="outline"
                        size="xs"
                        className="mt-0.5 shrink-0 font-mono"
                        title={t(check[1])}
                        onClick={() => onCheck(check[0])}
                      >
                        &gt; {check[0]}
                      </Button>
                    ) : null}
                  </div>
                  <CollapsibleContent className="space-y-4 px-4 pb-4">
                    <p className="text-muted-foreground max-w-prose text-xs leading-relaxed">
                      <Rich text={t(section.blurb)} />
                    </p>
                    {section.pairs === "projects" ? (
                      <ProjectRows
                        rows={rows ?? drawn.projects.map((item) => ({ ...item }))}
                        setRows={setRows}
                      />
                    ) : (
                      <div className="grid gap-x-4 gap-y-5 [grid-template-columns:repeat(auto-fill,minmax(17rem,1fr))]">
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
      </div>

      {dirty ? (
        <div className="bg-card flex items-center gap-2 border-t px-3.5 py-2.5 sm:px-5">
          <span className="text-muted-foreground text-xs">
            {dirty === 1
              ? t("one change, unsaved")
              : t("{{count}} changes, unsaved", { count: String(dirty) })}
          </span>
          <span className="flex-1" />
          <Button variant="outline" onClick={load} disabled={saving}>
            {t("revert")}
          </Button>
          <Button onClick={save} disabled={saving}>
            {saving ? t("saving…") : t("Save")}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
