import * as React from "react"
import { toast } from "sonner"
import { BookOpen, RefreshCw, Save } from "lucide-react"

import { Button } from "@/components/ui/button"
import { api, why } from "@/lib/api"
import { useT } from "@/lib/i18n"
import type { Context } from "@/lib/types"

import { EmptyState } from "./empty-state"
import { Eyebrow, PageHead } from "./frame"
import { MarkdownEditor } from "./markdown-editor"

/* The standing context, as something you can change.
 *
 * Whatever is written here reaches **every** ticket, before the project's brief
 * and before the ticket itself — which makes it the most expensive text in the
 * workspace and, until now, the one the console could not touch. Editing it
 * meant opening Notion; on a board made of files it meant knowing which file.
 *
 * Two things this pane does that no other one does.
 *
 * It **replaces** rather than appends. Every other write in this console adds:
 * a comment under a question, a report under a ticket. This is a value, not a
 * history — saving it twice has to leave one text, not two copies of it under
 * each other.
 *
 * And it edits what the *agent* reads, not what Notion draws: the page
 * flattened into the Markdown the prompt carries, drawn as it is typed. A
 * heading that looks different here from the way it looks in Notion is the
 * heading as an agent gets it.
 */

export function ContextPane() {
  const t = useT()
  const [drawn, setDrawn] = React.useState<Context | null>(null)
  const [text, setText] = React.useState("")
  const [problem, setProblem] = React.useState("")
  const [saving, setSaving] = React.useState(false)

  const load = React.useCallback(async () => {
    try {
      const fresh = await api.context()
      setDrawn(fresh)
      setText(fresh.text)
      setProblem("")
    } catch (error) {
      setProblem(why(error))
    }
  }, [])

  React.useEffect(() => {
    void load()
  }, [load])

  const save = async () => {
    setSaving(true)
    try {
      await api.saveContext(text)
      setDrawn((known) => (known ? { ...known, text: text.trim() } : known))
      toast.success(t("The context is saved"), {
        description: t("Every ticket from here on is told this."),
      })
    } catch (error) {
      toast.error(t("The context was not saved"), { description: why(error) })
    } finally {
      setSaving(false)
    }
  }

  // A text somebody is half-way through typing must not be lost to a reread,
  // and a save button that is live on an unchanged text says nothing.
  const changed = drawn !== null && text.trim() !== drawn.text.trim()

  return (
    <div className="flex min-h-0 flex-1 flex-col p-3.5 sm:p-5">
      <PageHead
        title={t("What every ticket is told first.")}
        blurb={t(
          "Before the project's brief and before the ticket itself. It is what makes an answer sound like you rather than like nobody — and you pay for it on every single ticket."
        )}
        action={
          <>
            <Button variant="outline" size="sm" onClick={() => void load()} disabled={saving}>
              <RefreshCw />
              {t("Reread")}
            </Button>
            <Button
              size="sm"
              onClick={() => void save()}
              disabled={!changed || saving || !drawn?.editable}
            >
              <Save />
              {saving ? t("Saving…") : t("Save")}
            </Button>
          </>
        }
      >
        <span className="text-muted-foreground inline-flex items-center gap-1.5 font-mono text-[0.7rem]">
          <BookOpen className="size-3.5" />
          {t("{{count}} characters in every prompt", { count: String(text.trim().length) })}
        </span>
      </PageHead>

      {problem ? (
        <p className="text-tr-amber border-tr-amber/30 bg-tr-amber/10 rounded-xl border px-4 py-3 text-sm">
          {problem}
        </p>
      ) : !drawn ? (
        <p className="text-muted-foreground text-sm">{t("Reading the context…")}</p>
      ) : !drawn.editable ? (
        <EmptyState icon={BookOpen}>
          {t("This workspace has no “{{page}}” page, so there is nowhere to write.", {
            page: drawn.where,
          })}
          <br />
          <code className="font-mono text-xs">ticket-runner init &lt;page-url&gt;</code>{" "}
          {t("builds it.")}
        </EmptyState>
      ) : (
        <>
          <MarkdownEditor
            value={text}
            onChange={setText}
            placeholder={t(
              "Who you are, what the team does, the stack, the conventions, the things never to do. Keep it to one screen."
            )}
            className="min-h-[24rem] flex-1"
          />
          <p className="text-muted-foreground mt-3 text-xs">
            <Eyebrow>{drawn.storage}</Eyebrow> —{" "}
            {t("saved to the “{{page}}” page, and read again on the next run.", {
              page: drawn.where,
            })}
          </p>
        </>
      )}
    </div>
  )
}
