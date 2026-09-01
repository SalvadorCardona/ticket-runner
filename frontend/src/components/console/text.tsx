import * as React from "react"

/* An address in a line of text becomes a link, and nothing else does.
 *
 * Answers, command output and the steps of a session all carry them — a pull
 * request, a Notion page, a preview — and reading one out loud into another tab
 * is not a gesture anybody should have to make.
 *
 * React escapes text for us, so the old rule ("nothing is ever built from a
 * string of HTML") is now the framework's job rather than this file's. What is
 * left is the parsing: an address is found, and the address becomes an anchor's
 * child — never its markup.
 */

const ADDRESS = /https?:\/\/[^\s<>"'`]+/g

/** A URL without the punctuation that ended the sentence it was written in. */
function trimmed(address: string): string {
  let end = address.length
  while (end > 0) {
    const last = address[end - 1]
    if (".,;:!?".includes(last)) end -= 1
    // A closing bracket is part of the address only where the address opened
    // one: an encyclopaedia writes them, a sentence in parentheses does not.
    else if (
      (last === ")" && !address.slice(0, end).includes("(")) ||
      (last === "]" && !address.slice(0, end).includes("["))
    )
      end -= 1
    else break
  }
  return address.slice(0, end)
}

export function Flow({ text }: { text: string }) {
  const line = String(text ?? "")
  const parts: React.ReactNode[] = []
  let last = 0
  let key = 0
  for (const found of line.matchAll(ADDRESS)) {
    const address = trimmed(found[0])
    const index = found.index ?? 0
    if (index > last) parts.push(line.slice(last, index))
    parts.push(
      <a
        key={key++}
        href={address}
        target="_blank"
        rel="noreferrer noopener"
        className="text-tr-blue underline underline-offset-2 break-all hover:opacity-80"
      >
        {address}
      </a>
    )
    last = index + address.length
  }
  parts.push(line.slice(last))
  return <>{parts}</>
}

/** Backticked words become <code>, and nothing else becomes markup. */
export function Rich({ text }: { text: string }) {
  return (
    <>
      {String(text ?? "")
        .split("`")
        .map((part, index) =>
          index % 2 ? (
            <code
              key={index}
              className="bg-muted rounded px-1 py-0.5 font-mono text-[0.88em]"
            >
              {part}
            </code>
          ) : (
            <React.Fragment key={index}>{part}</React.Fragment>
          )
        )}
    </>
  )
}
