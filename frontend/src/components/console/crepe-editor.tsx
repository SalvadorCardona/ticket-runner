import * as React from "react"
import { CrepeBuilder } from "@milkdown/crepe/builder"
import { blockEdit } from "@milkdown/crepe/feature/block-edit"
import { cursor } from "@milkdown/crepe/feature/cursor"
import { linkTooltip } from "@milkdown/crepe/feature/link-tooltip"
import { listItem } from "@milkdown/crepe/feature/list-item"
import { placeholder as placeholderFeature } from "@milkdown/crepe/feature/placeholder"
import { table } from "@milkdown/crepe/feature/table"
import { toolbar } from "@milkdown/crepe/feature/toolbar"
import { replaceAll } from "@milkdown/kit/utils"

import { t } from "@/lib/i18n"
import { cn } from "@/lib/utils"

import type { MarkdownEditorProps } from "./markdown-editor"

/* Milkdown's Crepe, put together feature by feature rather than taken whole.
 *
 * Whole, it brings CodeMirror and its forty languages, KaTeX, an image uploader
 * and a bar of AI buttons. None of those survives the trip: a page body here is
 * written to Notion or to a Markdown file, and what an agent reads is the text.
 * An image pasted into it would be a data URL nobody can host, and a formula
 * would reach the prompt as its source. What is kept is what makes it feel like
 * Notion — `/` for a block, a handle to drag one, a bar over a selection — and
 * what a brief is actually written in: headings, lists, quotes, links, tables.
 *
 * Markdown is the editor's own model, not an export of it: what comes out is
 * what went in, re-spelled at most (`*` for `-`), which is why this one was
 * picked over the block editors that store JSON and translate on the way out.
 */

export default function CrepeEditor({
  value,
  onChange,
  placeholder,
  readOnly,
  className,
}: MarkdownEditorProps) {
  const root = React.useRef<HTMLDivElement>(null)
  const crepe = React.useRef<CrepeBuilder | null>(null)
  // What the editor holds, in the editor's own spelling. A value handed back
  // that says the same is not a change, and must not reset the caret.
  const held = React.useRef(value)
  const wanted = React.useRef(value)
  const change = React.useRef(onChange)
  change.current = onChange

  React.useEffect(() => {
    const place = root.current
    if (!place) return
    // A host of its own per mount: under StrictMode the first editor is still
    // being built when the second one starts, and two editors in one element
    // is one editor drawn twice.
    const host = document.createElement("div")
    place.appendChild(host)
    const builder = new CrepeBuilder({ root: host, defaultValue: wanted.current })
      .addFeature(cursor)
      .addFeature(listItem)
      .addFeature(linkTooltip, { inputPlaceholder: t("Paste a link…") })
      .addFeature(placeholderFeature, { text: placeholder ?? "", mode: "doc" })
      .addFeature(table)
      .addFeature(toolbar, {
        boldLabel: t("Bold"),
        italicLabel: t("Italic"),
        strikethroughLabel: t("Strikethrough"),
        codeLabel: t("Inline code"),
        linkLabel: t("Link"),
      })
      .addFeature(blockEdit, {
        textGroup: {
          label: t("Text"),
          text: { label: t("Text") },
          h1: { label: t("Heading 1") },
          h2: { label: t("Heading 2") },
          h3: { label: t("Heading 3") },
          // Three levels, as Notion offers: a brief deeper than that is a
          // document that wants cutting up.
          h4: null,
          h5: null,
          h6: null,
          quote: { label: t("Quote") },
          divider: { label: t("Divider") },
        },
        listGroup: {
          label: t("List"),
          bulletList: { label: t("Bullet list") },
          orderedList: { label: t("Numbered list") },
          taskList: { label: t("To-do list") },
        },
        advancedGroup: {
          label: t("Advanced"),
          image: null,
          math: null,
          codeBlock: { label: t("Code") },
          table: { label: t("Table") },
        },
      })
    builder.on((listen) =>
      listen.markdownUpdated((_, markdown) => {
        if (markdown === held.current) return
        held.current = markdown
        change.current(markdown)
      })
    )

    let alive = true
    const made = builder.create().then(() => {
      if (!alive) return
      crepe.current = builder
      builder.setReadonly(Boolean(readOnly))
      // A value that arrived while the editor was being built.
      if (wanted.current !== held.current) builder.editor.action(replaceAll(wanted.current))
      held.current = builder.getMarkdown()
    })
    return () => {
      alive = false
      crepe.current = null
      void made.then(() => builder.destroy()).finally(() => host.remove())
    }
    // Built once: the placeholder and the labels are read as it is built, and
    // rebuilding it for a new one would drop the caret and the history.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  React.useEffect(() => {
    wanted.current = value
    const builder = crepe.current
    if (!builder || value === held.current) return
    // Replaced from outside — a reread, a form reset: the text somebody was
    // typing is not in `value`, so this never fires under their fingers.
    builder.editor.action(replaceAll(value))
    held.current = builder.getMarkdown()
  }, [value])

  React.useEffect(() => {
    crepe.current?.setReadonly(Boolean(readOnly))
  }, [readOnly])

  return <div ref={root} data-slot="markdown-editor" className={cn(className)} />
}
