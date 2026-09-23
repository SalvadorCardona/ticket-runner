import * as React from "react"
import type { InputControllerComponentInterface } from "react-data-form"

import { cn } from "@/lib/utils"

/* Where the console writes Markdown: the context, a project's brief, a new
 * ticket, a schedule's page. All four used to be a text area — the asterisks
 * typed by hand, and a heading only a heading once Notion drew it.
 *
 * The editor itself is Milkdown (see `crepe-editor.tsx`), and it is fetched the
 * first time one of these fields is drawn rather than with the console: it is
 * heavier than the rest of the console put together, and a board you only look
 * at never needs it.
 */

export interface MarkdownEditorProps {
  value: string
  onChange: (markdown: string) => void
  placeholder?: string
  readOnly?: boolean
  className?: string
}

const CrepeEditor = React.lazy(() => import("./crepe-editor"))

export function MarkdownEditor({ className, ...props }: MarkdownEditorProps) {
  const box = cn("min-h-40", className)
  return (
    // The box is drawn before the editor arrives, at the size it will have, so
    // the form does not jump when it does.
    <React.Suspense fallback={<div data-slot="markdown-editor" className={box} />}>
      <CrepeEditor {...props} className={box} />
    </React.Suspense>
  )
}

/** The same editor, as a field of a react-data-form form. */
export const MarkdownInputController: InputControllerComponentInterface = ({
  formInput,
  onChange,
}) => (
  <MarkdownEditor
    value={String(formInput.value ?? "")}
    onChange={(value) => onChange({ ...formInput, value })}
    placeholder={formInput.placeholder}
    readOnly={formInput.readonly}
  />
)
