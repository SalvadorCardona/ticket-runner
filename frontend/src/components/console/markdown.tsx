import * as React from "react"

import { Flow } from "./text"

/* A ticket's page, as the runner reads it.
 *
 * `/api/tickets/<id>` flattens the Notion blocks into the plain markdown the
 * runner is handed before a run — headings, lists, check boxes, quotes, fenced
 * code — and this draws that back into something a person reads. It is not a
 * markdown engine: it knows the eight shapes `notion.blocks_text` writes and
 * nothing else, and every line lands as text, never as markup.
 */

// Notion names a language with spaces in it ("plain text"), so everything
// after the fence is the language.
const FENCE = /^```(.*)$/

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "item"; text: string; ordered: boolean; done?: boolean }
  | { kind: "quote"; text: string }
  | { kind: "code"; language: string; lines: string[] }
  | { kind: "rule" }
  | { kind: "paragraph"; text: string }

function blocks(text: string): Block[] {
  const out: Block[] = []
  const lines = text.replace(/\r\n/g, "\n").split("\n")
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    const fence = FENCE.exec(line.trim())
    if (fence) {
      const body: string[] = []
      index += 1
      while (index < lines.length && !FENCE.test(lines[index].trim())) body.push(lines[index++])
      index += 1
      out.push({ kind: "code", language: fence[1].trim(), lines: body })
      continue
    }
    const trimmed = line.trim()
    index += 1
    if (!trimmed) continue
    const heading = /^(#{1,3})\s+(.*)$/.exec(trimmed)
    if (heading) {
      out.push({ kind: "heading", level: heading[1].length, text: heading[2] })
      continue
    }
    if (trimmed === "---") {
      out.push({ kind: "rule" })
      continue
    }
    const todo = /^-\s+\[( |x)\]\s*(.*)$/.exec(trimmed)
    if (todo) {
      out.push({ kind: "item", ordered: false, done: todo[1] === "x", text: todo[2] })
      continue
    }
    if (/^-\s+/.test(trimmed)) {
      out.push({ kind: "item", ordered: false, text: trimmed.replace(/^-\s+/, "") })
      continue
    }
    if (/^\d+\.\s+/.test(trimmed)) {
      out.push({ kind: "item", ordered: true, text: trimmed.replace(/^\d+\.\s+/, "") })
      continue
    }
    if (trimmed.startsWith(">")) {
      out.push({ kind: "quote", text: trimmed.replace(/^>\s?/, "") })
      continue
    }
    out.push({ kind: "paragraph", text: line })
  }
  return out
}

/** `code` and **bold** inside a line; addresses become links. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g)
  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("`") && part.endsWith("`") && part.length > 1)
          return (
            <code key={index} className="bg-muted rounded px-1 py-0.5 font-mono text-[0.88em]">
              {part.slice(1, -1)}
            </code>
          )
        if (part.startsWith("**") && part.endsWith("**") && part.length > 3)
          return (
            <strong key={index} className="font-semibold">
              {part.slice(2, -2)}
            </strong>
          )
        return (
          <React.Fragment key={index}>
            <Flow text={part} />
          </React.Fragment>
        )
      })}
    </>
  )
}

export function Markdown({ text }: { text: string }) {
  const drawn = React.useMemo(() => blocks(text), [text])
  if (!drawn.length) return null
  return (
    <div className="flex flex-col gap-2 text-sm leading-relaxed">
      {drawn.map((block, index) => {
        switch (block.kind) {
          case "heading": {
            const Tag = block.level === 1 ? "h3" : block.level === 2 ? "h4" : "h5"
            return (
              <Tag
                key={index}
                className={
                  block.level === 1
                    ? "mt-4 text-base font-semibold"
                    : "mt-3 text-sm font-semibold"
                }
              >
                <Inline text={block.text} />
              </Tag>
            )
          }
          case "item":
            return (
              <div key={index} className="flex gap-2 pl-1">
                <span className="text-muted-foreground w-4 shrink-0 text-center">
                  {block.done === undefined ? (block.ordered ? "·" : "–") : block.done ? "☑" : "☐"}
                </span>
                <span className={block.done ? "text-muted-foreground line-through" : ""}>
                  <Inline text={block.text} />
                </span>
              </div>
            )
          case "quote":
            return (
              <blockquote
                key={index}
                className="border-tr-violet/50 text-muted-foreground border-l-2 pl-3"
              >
                <Inline text={block.text} />
              </blockquote>
            )
          case "code":
            return (
              <pre
                key={index}
                className="scroll-thin bg-muted/60 overflow-x-auto rounded-lg border px-3 py-2 font-mono text-xs leading-relaxed"
              >
                {block.lines.join("\n")}
              </pre>
            )
          case "rule":
            return <hr key={index} className="my-3" />
          default:
            return (
              <p key={index} className="whitespace-pre-wrap">
                <Inline text={block.text} />
              </p>
            )
        }
      })}
    </div>
  )
}
