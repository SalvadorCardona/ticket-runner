import * as React from "react"
import {
  FormElement,
  MultiSelectInputController,
  SelectInputController,
  useForm,
  useFormContext,
  type FormInputInterface,
  type FormInterface,
  type InputControllerInterface,
} from "react-data-form"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useConsole } from "@/hooks/use-console"
import { api, why } from "@/lib/api"
import { t as translate, useT } from "@/lib/i18n"
import {
  draftOf,
  forgetDraft,
  publishSettings,
  rememberDraft,
  sectionOf,
} from "@/lib/settings-store"
import type { SettingField, SettingSection, SettingValue } from "@/lib/types"

import { openTalk } from "./talk-drawer"
import { Rich } from "./text"

/* One section of `config.toml`, as a form.
 *
 * The page used to draw its own boxes: an `<Input>` here, a `<Select>` there,
 * a `Map` of what you had touched held above all of them. That made the
 * settings the one corner of the console whose fields were not the ones every
 * other form is made of — a declaration handed to react-data-form, which holds
 * the state and draws the controls. This is that declaration, built from what
 * the server says the file holds.
 *
 * The three states a setting carries survive the move, because they are the
 * whole grammar of the page: what the file says, what the runner falls back on
 * when it says nothing, and what you have just typed. So the form's data is
 * compared against the description it was built from and only what actually
 * moved is sent — a field left alone is a line the file keeps, comment and
 * all, and a token you did not retype is a token that never left the machine.
 * See `written`.
 */

/** Radix has no empty-string value, and "the file says nothing" needs one. */
const UNSET = "default:unset"

/** A token you asked to forget. An empty box already means "I did not retype it". */
const FORGOTTEN = "secret:forgotten"

/* A setting is named by its path into the file — `notion.status.ready` — and
 * react-data-form reads a dot in an input's name as a step into a nested
 * object: it would file the input under `inputs.notion.status` and lose the
 * flat entry the form was built with. So the dots become dashes on the way in,
 * and the field's own name comes back from the description rather than from
 * the input. */
const inputName = (name: string) => name.replaceAll(".", "-")

// The command each section is checked with. The CLI already knows how to say
// whether a token works; the settings page does not need a second opinion.
const CHECKS: Record<string, [string, string]> = {
  notion: ["doctor", "does that token reach your board?"],
  notify: ["notify", "send yourself a test message"],
  runner: ["enable", "apply the interval to the timer"],
}

function same(left: unknown, right: unknown): boolean {
  if (Array.isArray(left) && Array.isArray(right))
    return left.length === right.length && left.every((item, index) => item === right[index])
  return left === right
}

/* -- a field, both ways ---------------------------------------------------- */

/** What a field is worth to the form, before anybody types. */
function held(field: SettingField): SettingValue {
  if (field.kind === "secret") return ""
  if (field.kind === "bool")
    return field.value === null || field.value === undefined ? UNSET : String(field.value)
  if (field.kind === "choice") return (field.value as string) || UNSET
  if (field.kind === "events") {
    // Nothing stated means the three the runner would send anyway, shown
    // ticked: a list of moments has no greyed placeholder to fall back on.
    const fallback = Array.isArray(field.fallback) ? (field.fallback as string[]) : []
    return (field.value as string[] | null) ?? fallback
  }
  if (field.kind === "int") return field.value === null ? "" : (field.value as number)
  return field.value === null ? "" : String(field.value)
}

/** The same, as the file may hold it — or `null`, which removes the line. */
function told(field: SettingField, value: unknown): SettingValue {
  if (field.kind === "bool") return value === UNSET ? null : value === "true"
  if (field.kind === "choice") return value === UNSET || !value ? null : String(value)
  if (field.kind === "events") {
    // In the order the server lists them, so that ticking a box off and back
    // on is not a change of its own.
    const chosen = new Set(Array.isArray(value) ? value.map(String) : [])
    return field.choices.filter((choice) => chosen.has(choice))
  }
  if (field.kind === "secret") return value === FORGOTTEN ? null : String(value ?? "").trim()
  if (field.kind === "int") {
    const text = String(value ?? "").trim()
    return text === "" ? null : Number(text)
  }
  return String(value ?? "").trim()
}

/** The greyed answer beside a box: what happens if you say nothing. */
function placeholder(field: SettingField): string {
  if (field.kind === "secret")
    return field.preview
      ? translate("set · ends {{preview}}", { preview: field.preview })
      : translate("not set")
  if (field.fallback === "" || field.fallback === null) return translate("nothing")
  return translate("default · {{value}}", { value: String(field.fallback) })
}

/* The sentence under a box. Handed to the package as a node rather than as a
 * string, because it is two: what the setting does, and — where a change does
 * not simply take on the next run — what has to happen for it to count. */
function saying(field: SettingField): React.ReactNode {
  if (!field.help && !field.after) return undefined
  return (
    <>
      {field.help ? <Rich text={translate(field.help)} /> : null}
      {field.after ? (
        <span className="mt-1 block">
          {translate("takes effect once")} <Rich text={translate(field.after)} />
        </span>
      ) : null}
    </>
  )
}

/* -- the two controls the package has no answer for ------------------------ */

interface SecretFormInputInterface extends FormInputInterface {
  /** Enough of the token to recognise it by. The token itself never comes here. */
  preview?: string
}

/* A secret is not a password field with a value: it is a field whose value is
 * deliberately absent. Typing sets it, leaving it alone leaves it alone, and
 * forgetting one has to be a gesture of its own — which is why the package's
 * own password control, an input and an eye, cannot stand in for it. */
const SecretInputController = ({
  formInput,
  onChange,
}: InputControllerInterface<SecretFormInputInterface>) => {
  const t = useT()
  const forgotten = formInput.value === FORGOTTEN
  return (
    <div className="flex items-center gap-2">
      <Input
        id={formInput.id}
        name={formInput.name}
        type="password"
        autoComplete="off"
        spellCheck={false}
        value={forgotten ? "" : String(formInput.value ?? "")}
        placeholder={forgotten ? t("not set") : formInput.placeholder}
        onChange={(event) => onChange({ ...formInput, value: event.target.value })}
      />
      {formInput.preview && !forgotten ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onChange({ ...formInput, value: FORGOTTEN })}
        >
          {t("forget")}
        </Button>
      ) : null}
    </div>
  )
}

/* A number, and the one thing the package's number control cannot say: nothing
 * at all. It reads an emptied box as `Number("")`, which is zero — and zero is
 * an interval the runner would refuse. Here an empty box stays empty, which is
 * how the default comes back. */
const CountInputController = ({ formInput, onChange }: InputControllerInterface) => (
  <Input
    id={formInput.id}
    name={formInput.name}
    type="number"
    inputMode="numeric"
    autoComplete="off"
    defaultValue={typeof formInput.value === "number" ? String(formInput.value) : ""}
    placeholder={formInput.placeholder}
    onChange={(event) => {
      const text = event.target.value.trim()
      onChange({ ...formInput, value: text === "" ? "" : Number(text) })
    }}
  />
)

/* -- the section, as a declaration ----------------------------------------- */

function input(field: SettingField): FormInputInterface {
  const shared: FormInputInterface = {
    name: inputName(field.name),
    // Drawn by the package, which translates it as it draws: the label is the
    // server's own word, and the dictionary is keyed by those very words.
    label: field.label,
    description: saying(field),
    placeholder: placeholder(field),
    className: "min-w-0",
  }

  if (field.kind === "bool")
    return {
      ...shared,
      controller: SelectInputController,
      // Three answers, because the file has three: yes, no, and nothing —
      // which is the runner's own default and says which one it is.
      valueOptions: [
        {
          value: UNSET,
          label: translate("default · {{value}}", {
            value: field.fallback ? translate("yes") : translate("no"),
          }),
        },
        { value: "true", label: translate("yes") },
        { value: "false", label: translate("no") },
      ],
    }

  if (field.kind === "choice")
    return {
      ...shared,
      controller: SelectInputController,
      valueOptions: [
        {
          // A default nobody wrote is still a line in the list, and an empty
          // `{{value}}` would be read as a key rather than as nothing at all.
          value: UNSET,
          label: translate("default · {{value}}", { value: String(field.fallback) || "—" }),
        },
        ...field.choices.map((choice) => ({ value: choice, label: choice })),
      ],
    }

  if (field.kind === "events")
    return {
      ...shared,
      controller: MultiSelectInputController,
      // A row of moments is a row, not a column: it takes the width the grid
      // gives a field and needs all of it.
      className: "col-span-full min-w-0",
      valueOptions: field.choices.map((choice) => ({ value: choice, label: choice })),
    }

  if (field.kind === "secret") {
    const secret: SecretFormInputInterface = {
      ...shared,
      controller: SecretInputController,
      preview: field.preview,
    }
    return secret
  }

  if (field.kind === "int") return { ...shared, controller: CountInputController }

  return shared
}

/** Every field of one section, keyed the way the form has to key it. */
export function sectionData(section: SettingSection): Record<string, SettingValue> {
  return Object.fromEntries(section.fields.map((field) => [inputName(field.name), held(field)]))
}

/** What the file would gain from this form: only the lines that actually moved. */
export function written(
  section: SettingSection,
  data: Record<string, SettingValue>
): Record<string, SettingValue> {
  const changes: Record<string, SettingValue> = {}
  for (const field of section.fields) {
    const now = told(field, data[inputName(field.name)])
    if (same(now, told(field, held(field)))) continue
    changes[field.name] = now
  }
  return changes
}

/* -- what a section is saved with ------------------------------------------ */

/* The bar every section ends on: what is waiting to be saved, the command that
 * says whether this part of the file actually works, and the two gestures.
 *
 * It is the form's own submit action rather than a footer drawn beside it, so
 * the count it shows is read off the form the package is holding rather than
 * off a second copy kept in a parent. */
function SaveBar({ sectionKey }: { sectionKey: string }) {
  const { form, onSubmit, updateData, isLoading } = useFormContext()
  const { runCommand } = useConsole()
  const t = useT()
  const section = sectionOf(sectionKey)
  if (!section) return null

  const changed = Object.keys(written(section, form.data as Record<string, SettingValue>)).length
  const check = CHECKS[sectionKey]

  return (
    <div className="bg-card sticky bottom-0 col-span-full mt-5 flex flex-wrap items-center gap-2 border-t py-2.5">
      <span className="text-muted-foreground text-xs">
        {changed === 0
          ? t("nothing typed here")
          : changed === 1
            ? t("one change, unsaved")
            : t("{{count}} changes, unsaved", { count: String(changed) })}
      </span>
      <span className="flex-1" />
      {check ? (
        <Button
          type="button"
          variant="outline"
          size="xs"
          className="font-mono"
          title={t(check[1])}
          onClick={() => {
            // The answer lands in the console's transcript, which is behind the
            // bubble: a check you cannot read is a check nobody ran.
            openTalk()
            void runCommand(check[0])
          }}
        >
          &gt; {check[0]}
        </Button>
      ) : null}
      <Button
        type="button"
        variant="outline"
        disabled={!changed || isLoading.value}
        onClick={() => updateData(sectionData(section), false)}
      >
        {t("revert")}
      </Button>
      <Button type="button" disabled={!changed || isLoading.value} onClick={() => void onSubmit()}>
        {isLoading.value ? t("saving…") : t("Save")}
      </Button>
    </div>
  )
}

/* One component per section rather than one built as the form is declared: a
 * component born in a render is a component React remounts on the next one,
 * and a field being retyped does not survive that. */
const BARS = new Map<string, React.FC>()

function barFor(sectionKey: string): React.FC {
  const known = BARS.get(sectionKey)
  if (known) return known
  const bar = () => <SaveBar sectionKey={sectionKey} />
  BARS.set(sectionKey, bar)
  return bar
}

export function sectionForm(section: SettingSection): FormInterface {
  return {
    label: { submit: "Save" },
    // The fields flow into as many columns as the tab is wide, which is what
    // keeps a section of twenty keys from being a page you scroll.
    className: "grid items-start gap-x-4 [grid-template-columns:repeat(auto-fill,minmax(17rem,1fr))]",
    components: { formSubmitAction: barFor(section.key) },
    inputs: Object.fromEntries(section.fields.map((field) => [inputName(field.name), input(field)])),
  }
}

/** What a save came back with, said in the words the fields are said in. */
export interface SaveNote {
  text: string
  bad: boolean
}

export function SectionForm({
  section,
  onSaved,
}: {
  section: SettingSection
  onSaved: (note: SaveNote) => void
}) {
  const { reloadState } = useConsole()
  const form = React.useMemo(() => sectionForm(section), [section])
  const data = React.useMemo(
    () => draftOf(section.key) ?? sectionData(section),
    [section]
  )

  const context = useForm({
    form,
    data,
    // Only one tab is drawn at a time, so a section leaving the screen would
    // otherwise take what you typed in it with it.
    onChange: (typed) => {
      const current = typed as Record<string, SettingValue>
      rememberDraft(section.key, current, Object.keys(written(section, current)).length > 0)
    },
    onSubmit: async (typed) => {
      const changes = written(section, typed as Record<string, SettingValue>)
      if (!Object.keys(changes).length) {
        onSaved({ bad: false, text: translate("Nothing to save — the file already said that.") })
        return
      }
      try {
        const result = await api.saveSettings({ settings: changes })
        forgetDraft(section.key)
        // The description is read again rather than patched: a token that has
        // just been set comes back as a preview, and a line that has just been
        // removed comes back as the default it fell through to.
        publishSettings(await api.settings())
        await reloadState()
        // A 200 is the server saying it wrote; what it wrote is a courtesy, and
        // a save is not going to be reported as a failure over a missing list.
        const saved = result.saved ?? []
        // The server says what has to happen in the same words the fields do,
        // so the sentence is translated the same way they are.
        const after = (result.after ?? []).map((one) => translate(one))
        const how =
          saved.length === 1
            ? translate("one setting")
            : translate("{{count}} settings", { count: String(saved.length) })
        onSaved({
          bad: false,
          text:
            translate("Saved {{how}}: {{names}}.", { how, names: saved.join(", ") }) +
            (after.length
              ? " " + translate("Takes effect once {{after}}.", { after: after.join("; ") })
              : ""),
        })
      } catch (error) {
        // On the section itself, not in the transcript: on a phone the console
        // is a tab away, and a save you have to go looking for is one you
        // doubt.
        onSaved({ bad: true, text: translate("Not saved: {{why}}", { why: why(error) }) })
      }
    },
  })

  return <FormElement {...context} />
}
