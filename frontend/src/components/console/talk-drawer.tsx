import * as React from "react"
import { MessageCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useConsole } from "@/hooks/use-console"
import { useT } from "@/lib/i18n"

import { ConsolePane } from "./console-pane"
import { TicketTalk } from "./ticket-talk"

/* The discussion, behind a bubble.
 *
 * It used to be a column: half the screen given to a conversation whether or
 * not there was one, an entry in the menu to reach it on a phone, and a switch
 * in the bar to fold it away — three places to learn for one thing to open. A
 * bubble in the bottom corner is the gesture everybody already knows, and the
 * page keeps its full width until you ask for the conversation.
 *
 * What it opens is what you are looking at: on a ticket, that ticket's
 * discussion; anywhere else, the workspace's own. Same rule as the column it
 * replaces, and the same two panes — only the way in changed.
 */

/* Opened from elsewhere: a section of the settings runs `> doctor` and the
 * answer arrives in the transcript, which is no use behind a closed drawer. An
 * event rather than a value in the console's context, for the same reason the
 * settings are reread on one: whoever asks does not have to be near whoever
 * answers. */
const OPENED = "ticket-runner:talk"

/** Open the drawer, from anywhere on the page. */
export const openTalk = () => window.dispatchEvent(new Event(OPENED))

export function TalkDrawer() {
  const { ticket } = useConsole()
  const t = useT()
  const [open, setOpen] = React.useState(false)

  React.useEffect(() => {
    const listener = () => setOpen(true)
    window.addEventListener(OPENED, listener)
    return () => window.removeEventListener(OPENED, listener)
  }, [])

  const label = ticket ? t("the discussion") : t("the console")

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <SheetTrigger asChild>
            {/* Hidden while the drawer is over it: the sheet's own close is
                where a reader looks for it, and a bubble under the overlay is
                a button that answers nothing. */}
            <Button
              size="icon-lg"
              aria-label={t("open {{pane}}", { pane: label })}
              className="fixed right-4 bottom-4 z-40 size-12 rounded-full shadow-lg data-[state=open]:hidden"
            >
              <MessageCircle className="size-5" />
            </Button>
          </SheetTrigger>
        </TooltipTrigger>
        <TooltipContent side="left">{t("open {{pane}}", { pane: label })}</TooltipContent>
      </Tooltip>

      <SheetContent side="right" className="w-full gap-0 sm:max-w-lg">
        {/* The pane under it opens with its own heading — which ticket, or
            which machine you are talking to — so the sheet's is for the
            readers who are told the page rather than shown it. */}
        <SheetHeader className="sr-only">
          <SheetTitle>{label}</SheetTitle>
          <SheetDescription>
            {ticket
              ? t("Everything said on the ticket, oldest first. What you type is a comment on it.")
              : t("A sentence talks to your workspace; a line that starts with > runs a command.")}
          </SheetDescription>
        </SheetHeader>
        {ticket ? <TicketTalk /> : <ConsolePane />}
      </SheetContent>
    </Sheet>
  )
}
