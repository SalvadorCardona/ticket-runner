import {
  Activity,
  LayoutGrid,
  Moon,
  RefreshCw,
  Settings2,
  Sun,
  Terminal,
  Ticket,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarSeparator,
  useSidebar,
} from "@/components/ui/sidebar"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useConsole } from "@/hooks/use-console"
import { useTheme } from "@/hooks/use-theme"
import { visible, type Pane, type PaneMenuItem } from "@/lib/menu"
import { cn } from "@/lib/utils"

/* The left menu.
 *
 * It replaces the row of tabs, and it says more than the tabs could: how many
 * tickets are ready, which one the Ticket pane is holding, how many sessions are
 * writing right now. A menu that only navigates is a menu you read once.
 *
 * Collapsed it is a rail of icons — ⌘B, or the strip down its right edge — and
 * every entry keeps its name in a tooltip.
 */
export function AppSidebar({
  pane,
  setPane,
}: {
  pane: Pane
  setPane: (pane: Pane) => void
}) {
  const { board, runner, sessions, ticket, connection, refresh } = useConsole()
  const { theme, toggle } = useTheme()
  const { state, isMobile, setOpenMobile } = useSidebar()

  const ready = board.tickets.filter((item) => item.column === "ready").length
  const running = board.tickets.filter((item) => item.column === "running").length
  const review = board.tickets.filter((item) => item.column === "review").length

  const items: PaneMenuItem[] = [
    {
      pane: "board",
      name: "Board",
      icon: LayoutGrid,
      priority: 50,
      badge: board.tickets.length || undefined,
      detail: [ready && `${ready} ready`, review && `${review} in review`]
        .filter(Boolean)
        .join(" · "),
    },
    {
      pane: "ticket",
      name: "Ticket",
      icon: Ticket,
      priority: 40,
      // Nothing to say until a card has been clicked, and saying "#—" would be
      // saying something.
      detail: ticket ? `#${ticket.short}` : "click a card",
    },
    {
      pane: "console",
      name: "Console",
      icon: Terminal,
      priority: 30,
      detail: runner?.chat.session_id ? `${runner.chat.turns} turn(s)` : "no conversation yet",
    },
    {
      pane: "live",
      name: "Live",
      icon: Activity,
      priority: 20,
      badge: sessions.length || undefined,
      detail: running ? `${running} running` : "",
    },
    {
      pane: "settings",
      name: "Settings",
      icon: Settings2,
      priority: 10,
      detail: runner?.timer === "enabled" ? "timer on" : `timer ${runner?.timer ?? ""}`.trim(),
    },
  ]

  const choose = (chosen: Pane) => {
    setPane(chosen)
    // On a phone the menu is a drawer over the pane it just opened.
    if (isMobile) setOpenMobile(false)
  }

  const collapsed = state === "collapsed" && !isMobile

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div
          className={cn(
            "flex items-center gap-2 px-2 py-1.5",
            collapsed && "justify-center px-0"
          )}
        >
          <span aria-hidden className="text-base leading-none">
            🎫
          </span>
          {!collapsed ? (
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">
                ticket<span className="text-muted-foreground">-runner</span>
              </div>
              {runner?.version ? (
                <div className="text-muted-foreground truncate font-mono text-[0.7rem]">
                  v{runner.version}
                  {runner.update ? ` · ${runner.update} waiting` : ""}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </SidebarHeader>

      <SidebarSeparator />

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>The workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {visible(items).map((item) => {
                const Icon = item.icon
                return (
                  <SidebarMenuItem key={item.pane}>
                    <SidebarMenuButton
                      isActive={pane === item.pane}
                      onClick={() => choose(item.pane)}
                      tooltip={item.detail ? `${item.name} — ${item.detail}` : item.name}
                      size="lg"
                      className="group-data-[collapsible=icon]:justify-center"
                    >
                      {Icon ? <Icon /> : null}
                      {/* Two lines, so not the single span the collapsed rule
                          truncates — left to it, the rail shows the first letter
                          of each label instead of nothing. */}
                      <span className="flex min-w-0 flex-col group-data-[collapsible=icon]:hidden">
                        <span className="truncate">{item.name}</span>
                        {item.detail ? (
                          <span className="text-muted-foreground truncate text-[0.7rem] font-normal">
                            {item.detail}
                          </span>
                        ) : null}
                      </span>
                    </SidebarMenuButton>
                    {item.badge !== undefined ? (
                      <SidebarMenuBadge>{item.badge}</SidebarMenuBadge>
                    ) : null}
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={refresh}
              tooltip="reread the board now"
              className="group-data-[collapsible=icon]:justify-center"
            >
              <RefreshCw />
              <span>Refresh</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={toggle}
              tooltip={theme === "dark" ? "go light" : "go dark"}
              className="group-data-[collapsible=icon]:justify-center"
            >
              {theme === "dark" ? <Sun /> : <Moon />}
              <span>{theme === "dark" ? "Light" : "Dark"}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>

        <Tooltip>
          <TooltipTrigger asChild>
            <div
              className={cn(
                "flex items-center gap-2 px-2 py-1 font-mono text-[0.7rem]",
                collapsed && "justify-center px-0",
                connection === "live" ? "text-tr-green" : "text-muted-foreground"
              )}
            >
              <span
                className={cn(
                  "size-1.5 shrink-0 rounded-full",
                  connection === "live" ? "bg-tr-green" : "bg-tr-amber animate-pulse"
                )}
              />
              {!collapsed ? (
                <span className="truncate">
                  {connection === "live"
                    ? "live"
                    : connection === "connecting"
                      ? "connecting…"
                      : "reconnecting…"}
                </span>
              ) : null}
            </div>
          </TooltipTrigger>
          <TooltipContent side="right">event stream</TooltipContent>
        </Tooltip>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  )
}
