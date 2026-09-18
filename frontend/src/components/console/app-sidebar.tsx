import {
  Activity,
  BookOpen,
  CalendarClock,
  FolderGit2,
  LayoutGrid,
  Moon,
  RefreshCw,
  Settings2,
  Sun,
  Terminal,
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
 * Seven addresses, a name each, and a number where something is waiting there:
 * how many tickets are on the board, how many sessions are writing right now.
 * It used to say a sentence under every name as well — how many were ready,
 * whether the timer was on — and seven entries of two lines is a page to read
 * rather than a menu to use. What is worth knowing at a glance is a count, and
 * a count fits beside a name.
 *
 * Collapsed it is a rail of icons — ⌘B, or the strip down its right edge — and
 * every entry keeps its name in a tooltip.
 */
export function AppSidebar({ route }: { route: Route }) {
  const { board, runner, sessions, connection, refresh } = useConsole()
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
      name: t("Console"),
      href: pageHref("console"),
      page: "console",
      icon: Terminal,
      priority: 30,
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
      <SidebarHeader>
        <div
          className={cn(
            "flex items-center gap-2.5 px-2 py-1.5",
            collapsed && "justify-center px-0"
          )}
        >
          {/* The one place the accent is spent on something that is not a
              button: the mark, so the eye has somewhere to start. */}
          <span
            aria-hidden
            className="bg-primary flex size-7 shrink-0 items-center justify-center rounded-lg text-sm leading-none"
          >
            🎫
          </span>
          {!collapsed ? (
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold tracking-[-0.01em]">
                ticket<span className="text-muted-foreground">-runner</span>
              </div>
              {runner?.version ? (
                <div className="text-muted-foreground truncate font-mono text-[0.65rem]">
                  v{runner.version}
                  {runner.update ? ` · ${t("{{version}} waiting", { version: runner.update })}` : ""}
                </div>
              ) : null}
            </div>
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
                  <SidebarMenuItem
                    key={item.name}
                    // Above 861px the console has a column of its own, and an
                    // entry for it would be an entry for what is already there.
                    className={item.page === "console" ? "min-[861px]:hidden" : undefined}
                  >
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
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  )
}
