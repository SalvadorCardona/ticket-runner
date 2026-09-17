import * as React from "react"

import { cn } from "@/lib/utils"

import { Flow } from "./text"

/* Markdown, drawn rather than shown.
 *
 * Two things in the console are written in markdown: a ticket's page, which
 * `/api/tickets/<id>` flattens out of the Notion blocks the runner is handed
 * before a run, and what a session says afterwards — in a comment on the
 * ticket, or in an answer in the workspace's transcript. Left alone both arrive
 * as their own source, and a reader ends up reading the asterisks.
 *
 * It is not a markdown engine: it knows the shapes `notion.blocks_text` writes
 * and the few more a session reaches for — a nested list, a word behind a
 * link, an emphasis — and nothing else. Every line lands as text, never as
 * markup: React escapes what it is given, and an address is only ever an
 * anchor's child.
 */

// Notion names a language with spaces in it ("plain text"), so everything
// after the fence is the language.
const FENCE = /^```(.*)$/

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "item"; text: string; marker: string; depth: number; done?: boolean }
  | { kind: "quote"; text: string }
  | { kind: "code"; language: string; lines: string[] }
  | { kind: "rule" }
  | { kind: "paragraph"; text: string }

/** How deep a list item sits: two spaces is a level, a tab is a level. */
function depth(line: string): number {
  const indent = /^[\t ]*/.exec(line)?.[0] ?? ""
  return Math.min(3, indent.replace(/\t/g, "  ").length >> 1)
}

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
    const level = depth(line)
    index += 1
    if (!trimmed) continue
    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed)
    if (heading) {
      out.push({ kind: "heading", level: heading[1].length, text: heading[2] })
      continue
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      out.push({ kind: "rule" })
      continue
    }
    const todo = /^[-*+]\s+\[( |x)\]\s*(.*)$/.exec(trimmed)
    if (todo) {
      out.push({
        kind: "item",
        marker: todo[1] === "x" ? "☑" : "☐",
        depth: level,
        done: todo[1] === "x",
        text: todo[2],
      })
      continue
    }
    if (/^[-*+]\s+/.test(trimmed)) {
      out.push({
        kind: "item",
        marker: "–",
        depth: level,
        text: trimmed.replace(/^[-*+]\s+/, ""),
      })
      continue
    }
    const ordered = /^(\d+)[.)]\s+(.*)$/.exec(trimmed)
    if (ordered) {
      // The number a list was written with, rather than one this file counted:
      // a session that starts at 3 meant to start at 3.
      out.push({ kind: "item", marker: `${ordered[1]}.`, depth: level, text: ordered[2] })
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

const LINK = /^\[([^\]]*)\]\(([^)\s]+)\)$/

/** An address a browser may be sent to, and nothing else — never `javascript:`. */
const reachable = (address: string) => /^(https?:\/\/|\/|mailto:)/i.test(address)

/** How deep an item is pushed in. Written out, because Tailwind reads the source. */
const INDENT = ["pl-1", "pl-6", "pl-11", "pl-16"]

/** `code`, **bold**, *emphasis* and [a word](behind a link), inside a line. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\]]*\]\([^)\s]+\))/g)
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
        if (part.startsWith("*") && part.endsWith("*") && part.length > 2)
          return <em key={index}>{part.slice(1, -1)}</em>
        const link = LINK.exec(part)
        if (link)
          return reachable(link[2]) ? (
            <a
              key={index}
              href={link[2]}
              target="_blank"
              rel="noreferrer noopener"
              className="text-tr-blue underline underline-offset-2 hover:opacity-80"
            >
              {link[1]}
            </a>
          ) : (
            <React.Fragment key={index}>{link[1]}</React.Fragment>
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
                className={cn(
                  // A heading opening a bubble is not pushed off its own top.
                  "first:mt-0",
                  block.level === 1
                    ? "mt-4 text-base font-semibold"
                    : "mt-3 text-sm font-semibold"
                )}
              >
                <Inline text={block.text} />
              </Tag>
            )
          }
          case "item":
            return (
              <div key={index} className={cn("flex gap-2", INDENT[block.depth])}>
                <span className="text-muted-foreground min-w-4 shrink-0 text-center tabular-nums">
                  {block.marker}
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
            // Tailwind's reset leaves every border at zero width, so a bare
            // `<hr>` is a blank line rather than a rule: the break has to be
            // asked for by name.
            return <hr key={index} className="border-border my-3 border-t" />
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
