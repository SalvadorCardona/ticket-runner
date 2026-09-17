import * as React from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { Schedule } from "@/lib/types"

/* Writing a schedule, rather than opening Notion to write it.
 *
 * Six fields and no more, and the three that are missing are the point: `Next`,
 * `Last` and `Last ticket` are what a *pass* writes back — they are how the
 * runner knows an occurrence has been taken. A console that let you edit them
 * would let you make an occurrence happen twice, or never.
 *
 * `Active` is here and is the only switch that matters: unticking it stops
 * everything without deleting a single row, which is the gesture this whole
 * feature is designed around. A new schedule is created unticked whatever this
 * form says — you look at it, then you turn it on.
 */

/** What a cadence may say. The same four `schedules.py` knows, and no free text. */
const CADENCES = ["Hourly", "Daily", "Weekly", "Monthly"]
const MODELS = ["opus", "sonnet", "haiku"]
const PRIORITIES = ["Urgent", "High", "Normal", "Low"]

/** react's `Select` has no empty value, so "nobody picked one" needs a word. */
const UNSET = "—"

export interface Draft {
  name: string
  cadence: string
  at: string
  day: string
  active: boolean
  model: string
  priority: string
}

export function draftOf(schedule: Schedule | null): Draft {
  return {
    name: schedule?.name ?? "",
    cadence: schedule?.cadence ?? "",
    at: schedule?.at ?? "",
    day: schedule?.day ?? "",
    active: schedule?.active ?? false,
    model: schedule?.model ?? "",
    priority: schedule?.priority ?? "",
  }
}

function Picker({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
}) {
  const t = useT()
  return (
    <div className="min-w-0">
      <Label className="text-muted-foreground mb-1.5 text-xs">{label}</Label>
      <Select
        value={value || UNSET}
        onValueChange={(picked) => onChange(picked === UNSET ? "" : picked)}
      >
        <SelectTrigger className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={UNSET}>{t("nothing said")}</SelectItem>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

export function ScheduleForm({
  schedule,
  onSaved,
  onCancel,
}: {
  /** The row being changed, or null for one being written. */
  schedule: Schedule | null
  onSaved: () => void
  onCancel: () => void
}) {
  const t = useT()
  const [draft, setDraft] = React.useState<Draft>(() => draftOf(schedule))
  const [saving, setSaving] = React.useState(false)
  const set = (part: Partial<Draft>) => setDraft((known) => ({ ...known, ...part }))

  const save = async () => {
    if (!draft.name.trim()) {
      toast.error(t("A schedule needs a name"))
      return
    }
    setSaving(true)
    try {
      if (schedule) await api.saveSchedule(schedule.id, { ...draft })
      else await api.createSchedule({ ...draft })
      toast.success(schedule ? t("Schedule saved") : t("Schedule created, left unticked"))
      onSaved()
    } catch (error) {
      toast.error(t("The schedule was not saved"), { description: why(error) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <div>
        <Label className="text-muted-foreground mb-1.5 text-xs">{t("name")}</Label>
        <Input
          value={draft.name}
          onChange={(event) => set({ name: event.target.value })}
          placeholder={t("Weekly dependency review")}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Picker
          label={t("cadence")}
          value={draft.cadence}
          options={CADENCES}
          onChange={(cadence) => set({ cadence })}
        />
        <div className="min-w-0">
          <Label className="text-muted-foreground mb-1.5 text-xs">{t("at")}</Label>
          <Input
            value={draft.at}
            onChange={(event) => set({ at: event.target.value })}
            placeholder="09:00"
            className="font-mono"
          />
        </div>
        <div className="min-w-0">
          <Label className="text-muted-foreground mb-1.5 text-xs">{t("day")}</Label>
          <Input
            value={draft.day}
            onChange={(event) => set({ day: event.target.value })}
            placeholder={t("Monday, or 1 to 31")}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Picker
          label={t("model")}
          value={draft.model}
          options={MODELS}
          onChange={(model) => set({ model })}
        />
        <Picker
          label={t("priority")}
          value={draft.priority}
          options={PRIORITIES}
          onChange={(priority) => set({ priority })}
        />
      </div>

      {/* Only on a row that exists: a new schedule is created unticked
          whatever a form says, so offering the switch here would be offering a
          choice that is not taken. */}
      {schedule ? (
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={draft.active}
            onCheckedChange={(checked) => set({ active: checked === true })}
          />
          {t("on — a ticket is born at the hour above")}
        </label>
      ) : (
        <p className="text-muted-foreground text-xs">
          {t("Created unticked: nothing is born until you turn it on.")}
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => void save()} disabled={saving}>
          {saving ? t("Saving…") : schedule ? t("Save") : t("Create")}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving}>
          {t("Cancel")}
        </Button>
      </div>
    </div>
  )
}
