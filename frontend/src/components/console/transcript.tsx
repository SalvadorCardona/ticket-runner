import * as React from "react"
import { ArrowDownIcon } from "lucide-react"

import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller"
import { useT } from "@/lib/i18n"
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
  const t = useT()
  return (
    <MessageScrollerProvider autoScroll defaultScrollPosition="end">
      <MessageScroller className={cn("min-h-0 flex-1", className)}>
        <MessageScrollerViewport className="scroll-thin p-3.5">
          <MessageScrollerContent className="gap-2">{children}</MessageScrollerContent>
        </MessageScrollerViewport>
        {/* The label said here rather than in `message-scroller.tsx`: that file
            is the component as shadcn writes it, and what it says by default is
            English a screen reader would read out in a French console. */}
        <MessageScrollerButton>
          <ArrowDownIcon />
          <span className="sr-only">{t("Scroll to the last message")}</span>
        </MessageScrollerButton>
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
