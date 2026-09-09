import * as React from "react"

import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller"
import { cn } from "@/lib/utils"

/* A scrolling conversation, kept at its end while it grows.
 *
 * shadcn's message scroller does what `useStickToBottom` used to: it follows
 * new lines only while you are already at the bottom, and offers a button
 * back down when you are not. Both transcripts of the console — the
 * workspace's and a ticket's — are drawn through this.
 */
export function Transcript({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <MessageScrollerProvider autoScroll defaultScrollPosition="end">
      <MessageScroller className={cn("min-h-0 flex-1", className)}>
        <MessageScrollerViewport className="scroll-thin p-3.5">
          <MessageScrollerContent className="gap-2">{children}</MessageScrollerContent>
        </MessageScrollerViewport>
        <MessageScrollerButton />
      </MessageScroller>
    </MessageScrollerProvider>
  )
}

/** One line of a transcript. `anchor` marks the lines a reader scrolls back to — the ones you wrote. */
export function Line({
  id,
  anchor = false,
  children,
}: {
  id: string
  anchor?: boolean
  children: React.ReactNode
}) {
  return (
    <MessageScrollerItem messageId={id} scrollAnchor={anchor} className="[contain-intrinsic-size:auto_3rem]">
      {children}
    </MessageScrollerItem>
  )
}
