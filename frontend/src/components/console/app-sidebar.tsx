import {
  Activity,
  ArrowUp,
  BookOpen,
  CalendarClock,
  FolderGit2,
  LayoutGrid,
  Moon,
  RefreshCw,
  Settings2,
  Sun,
} from "lucide-react"
import { Link } from "react-resource-view"

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
import { useT } from "@/lib/i18n"
import { visible, type PaneMenuItem } from "@/lib/menu"
import { pageHref, type Route } from "@/lib/router"
import { cn } from "@/lib/utils"
import { PROJECTS, projectsHref } from "@/resources/projects"
import { SCHEDULES, schedulesHref } from "@/resources/schedules"
import { SETTINGS, settingsHref } from "@/resources/settings"
import { TICKETS, boardHref } from "@/resources/tickets"

/* The left menu.
 *
 * Six addresses, a name each, and a number where something is waiting there:
 * how many tickets are on the board, how many sessions are writing right now.
 * It used to say a sentence under every name as well — how many were ready,
 * whether the timer was on — and seven entries of two lines is a page to read
 * rather than a menu to use. What is worth knowing at a glance is a count, and
 * a count fits beside a name.
 *
 * The seventh was the console's own, for the widths where it had no column of
 * its own; it is a drawer now, opened by the bubble in the bottom corner, and a
 * menu has no entry for a thing that is already on the screen.
 *
 * Collapsed it is a rail of icons — ⌘B, or the strip down its right edge — and
 * every entry keeps its name in a tooltip.
 */
export function AppSidebar({ route }: { route: Route }) {
  const { board, sessions, connection, refresh, runner } = useConsole()
  const { theme, toggle } = useTheme()
  const { state, isMobile, setOpenMobile } = useSidebar()
  const t = useT()

  const items: PaneMenuItem[] = [
    {
      name: t("Board"),
      href: boardHref(),
      resource: TICKETS,
      icon: LayoutGrid,
      priority: 50,
      badge: board.tickets.length || undefined,
    },
    {
      name: t("Live"),
      href: pageHref("live"),
      page: "live",
      icon: Activity,
      priority: 20,
      badge: sessions.length || undefined,
    },
    {
      name: t("Projects"),
      href: projectsHref(),
      resource: PROJECTS,
      icon: FolderGit2,
      priority: 18,
    },
    {
      // No count, here as under Projects: the only way to know is to ask the
      // board, and this menu is redrawn every time the board moves.
      name: t("Schedules"),
      href: schedulesHref(),
      resource: SCHEDULES,
      icon: CalendarClock,
      priority: 15,
    },
    {
      name: t("Context"),
      href: pageHref("context"),
      page: "context",
      icon: BookOpen,
      priority: 12,
    },
    {
      name: t("Settings"),
      href: settingsHref(),
      resource: SETTINGS,
      icon: Settings2,
      priority: 10,
    },
  ]

  // Every address of a resource — a ticket, a section of the settings — is the
  // entry that resource opens on. An address that names none is the board.
  const active = (item: PaneMenuItem) =>
    item.page
      ? route.kind === "page" && route.page === item.page
      : route.kind === "resource" && (route.params.resourceId ?? TICKETS) === item.resource

  const collapsed = state === "collapsed" && !isMobile

  return (
    <Sidebar collapsible="icon">
      {/* A mark and a name, and nothing else. The version used to sit under the
          name in small type, which made the corner a block to read rather than
          a sign to recognise — and the header already says it, louder, on the
          only day it matters: the one where an update is waiting. */}
      <SidebarHeader>
        <div className={cn("flex h-8 items-center gap-2 px-2", collapsed && "justify-center px-0")}>
          <svg
            aria-hidden
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="size-4 shrink-0 text-primary"
          >
            <rect x="3" y="6" width="18" height="12" rx="2.5" />
            <path d="M10 6v2M10 11v2M10 16v2" />
            <path d="M13 9l3 3-3 3" />
          </svg>
          {!collapsed ? (
            <span className="truncate text-sm font-semibold">ticket-runner</span>
          ) : null}
        </div>
      </SidebarHeader>

      <SidebarSeparator />

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="font-mono text-[0.65rem] font-semibold tracking-[0.14em] uppercase">
            {t("workspace")}
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {visible(items).map((item) => {
                const Icon = item.icon
                return (
                  <SidebarMenuItem key={item.name}>
                    <SidebarMenuButton
                      asChild
                      isActive={active(item)}
                      tooltip={item.name}
                      className="group-data-[collapsible=icon]:justify-center"
                    >
                      <Link
                        to={item.href}
                        onClick={() => {
                          // On a phone the menu is a drawer over the pane it just opened.
                          if (isMobile) setOpenMobile(false)
                        }}
                      >
                        {Icon ? <Icon /> : null}
                        {/* Hidden rather than left to the button's own rule,
                            which truncates the last span — and a rail eight
                            units wide would show the first letter of the name
                            instead of nothing. */}
                        <span className="truncate group-data-[collapsible=icon]:hidden">
                          {item.name}
                        </span>
                      </Link>
                    </SidebarMenuButton>
                    {item.badge !== undefined ? (
                      <SidebarMenuBadge className="font-mono text-[0.7rem] tabular-nums">
                        {item.badge}
                      </SidebarMenuBadge>
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
              tooltip={t("reread the board now")}
              className="group-data-[collapsible=icon]:justify-center"
            >
              <RefreshCw />
              <span>{t("Refresh")}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton
              onClick={toggle}
              tooltip={theme === "dark" ? t("go light") : t("go dark")}
              className="group-data-[collapsible=icon]:justify-center"
            >
              {theme === "dark" ? <Sun /> : <Moon />}
              <span>{theme === "dark" ? t("Light") : t("Dark")}</span>
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
                    ? t("live")
                    : connection === "connecting"
                      ? t("connecting…")
                      : t("reconnecting…")}
                </span>
              ) : null}
            </div>
          </TooltipTrigger>
          <TooltipContent side="right">{t("event stream")}</TooltipContent>
        </Tooltip>

        {/* The number this console is running, and — the one day it matters —
            that a newer one is waiting. It used to be a pill in the bar, on
            every page, beside four others nobody was reading; here it is where
            the rest of the machine's own state already sits, and a rail too
            narrow for a version still shows the arrow that says update. */}
        {runner && (!collapsed || runner.update) ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <div
                className={cn(
                  "flex items-center gap-2 px-2 py-1 font-mono text-[0.7rem]",
                  collapsed && "justify-center px-0",
                  runner.update ? "text-tr-amber" : "text-muted-foreground"
                )}
              >
                {runner.update ? <ArrowUp className="size-3 shrink-0" /> : null}
                {!collapsed ? <span className="truncate">v{runner.version}</span> : null}
              </div>
            </TooltipTrigger>
            <TooltipContent side="right">
              {runner.update
                ? t("v{{version}} — {{waiting}} is waiting, run: ticket-runner update", {
                    version: runner.version,
                    waiting: runner.update,
                  })
                : t("the version this console runs")}
            </TooltipContent>
          </Tooltip>
        ) : null}
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  )
}
