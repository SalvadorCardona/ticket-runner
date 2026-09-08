import * as React from "react"

import { cn } from "@/lib/utils"

/* The shapes every pane of the console is built from.
 *
 * Four of them, and they are the whole design language: a mono label too small
 * to read as prose, which is how the console says what a thing *is*; a heading
 * block, which is how a pane opens; a grid of facts, which is how a ticket
 * states its metadata; and a panel, which is a card that announces itself.
 *
 * They live together in one file because they are one decision — change the
 * tracking on `Eyebrow` and the board, the sessions, the settings and a ticket
 * all change with it, which is the point of having them at all.
 */

/** The mono label over a heading, a panel or a fact. Small enough that it reads as a tag, not a sentence. */
export function Eyebrow({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <span
      className={cn(
        "text-muted-foreground font-mono text-[0.65rem] font-semibold tracking-[0.14em] uppercase",
        className
      )}
    >
      {children}
    </span>
  )
}

/** Where you are, said the way a path is said. */
export function Crumbs({ parts }: { parts: string[] }) {
  return (
    <Eyebrow>
      {parts.map((part, index) => (
        <React.Fragment key={part}>
          {index ? <span className="text-border mx-1.5">/</span> : null}
          {part}
        </React.Fragment>
      ))}
    </Eyebrow>
  )
}

/* How a pane opens: where you are, what this page is for in one line you can
 * read from across the room, what it is for in the line under that, and — at
 * the right edge — the one gesture the page exists to offer. */
export function PageHead({
  crumbs,
  title,
  blurb,
  action,
  children,
  className,
}: {
  crumbs: string[]
  title: string
  blurb?: string
  /** The page's own gesture, against the right edge on anything wider than a phone. */
  action?: React.ReactNode
  /** Under the blurb: a switch, a filter, whatever the page is steered with. */
  children?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("mb-6", className)}>
      <Crumbs parts={crumbs} />
      <div className="mt-2.5 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h2 className="text-2xl leading-tight font-bold tracking-[-0.03em] text-balance sm:text-[1.75rem]">
            {title}
          </h2>
          {blurb ? (
            <p className="text-muted-foreground mt-1.5 max-w-prose text-sm leading-relaxed">
              {blurb}
            </p>
          ) : null}
        </div>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </div>
      {children ? <div className="mt-4 flex flex-wrap items-center gap-2">{children}</div> : null}
    </div>
  )
}

/** A card that says what it is before it says anything else. */
export function Panel({
  eyebrow,
  title,
  action,
  children,
  className,
  bodyClassName,
}: {
  eyebrow: string
  title?: React.ReactNode
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={cn("bg-card rounded-xl border", className)}>
      <header className="flex items-start justify-between gap-3 px-4 pt-3.5 pb-3">
        <div className="min-w-0">
          <Eyebrow>{eyebrow}</Eyebrow>
          {title ? (
            <h3 className="mt-1 text-base leading-tight font-semibold tracking-[-0.01em]">
              {title}
            </h3>
          ) : null}
        </div>
        {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
      </header>
      <div className={cn("px-4 pb-4", bodyClassName)}>{children}</div>
    </section>
  )
}

/* A ticket's metadata, as a ruled grid rather than a list of pills: two
 * columns of cells sharing their edges, each cell a label and the answer under
 * it. Read down the labels and you know what is written about a ticket without
 * reading a single value. */
export function Facts({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        // The rule between two cells is drawn by the second of them — the top
        // edge of everything past the first row, the left edge of everything in
        // the second column — so the grid never doubles a line against its own
        // border, whether it holds an even number of facts or an odd one.
        "grid grid-cols-2 rounded-xl border",
        "[&>*:nth-child(n+3)]:border-t [&>*:nth-child(even)]:border-l",
        className
      )}
    >
      {children}
    </div>
  )
}

/** One cell of {@link Facts}: what it is, and what it says. */
export function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 px-3.5 py-3">
      <Eyebrow>{label}</Eyebrow>
      <div className="mt-1 truncate text-sm font-semibold">{children}</div>
    </div>
  )
}
