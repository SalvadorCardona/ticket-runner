import {
  Activity,
  CalendarClock,
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
import { boardHref } from "@/resources/tickets"

/* The left menu.
 *
 * Five addresses, and it says more than the addresses could: how many tickets
 * are on the board and how many are ready, how many sessions are writing right
 * now, whether the timer is on. A menu that only navigates is a menu you read
 * once.
 *
 * Collapsed it is a rail of icons — ⌘B, or the strip down its right edge — and
 * every entry keeps its name in a tooltip.
 */
export function AppSidebar({ route }: { route: Route }) {
  const { board, runner, sessions, connection, refresh } = useConsole()
  const { theme, toggle } = useTheme()
  const { state, isMobile, setOpenMobile } = useSidebar()
  const t = useT()

  const ready = board.tickets.filter((item) => item.column === "ready").length
  const running = board.tickets.filter((item) => item.column === "running").length
  const review = board.tickets.filter((item) => item.column === "review").length

  const items: PaneMenuItem[] = [
    {
      name: t("Board"),
      href: boardHref(),
      icon: LayoutGrid,
      priority: 50,
      badge: board.tickets.length || undefined,
      detail: [
        ready && t("{{count}} ready", { count: String(ready) }),
        review && t("{{count}} in review", { count: String(review) }),
      ]
        .filter(Boolean)
        .join(" · "),
    },
    {
      name: t("Console"),
      href: pageHref("console"),
      page: "console",
      icon: Terminal,
      priority: 30,
      detail: runner?.chat.session_id
        ? t("{{count}} turn(s)", { count: String(runner.chat.turns) })
        : t("no conversation yet"),
    },
    {
      name: t("Live"),
      href: pageHref("live"),
      page: "live",
      icon: Activity,
      priority: 20,
      badge: sessions.length || undefined,
      detail: running ? t("{{count}} running", { count: String(running) }) : "",
    },
    {
      name: t("Schedules"),
      href: pageHref("schedules"),
      page: "schedules",
      icon: CalendarClock,
      priority: 15,
      // No count and no badge: the only way to know is to ask Notion, and this
      // menu is redrawn every time the board moves.
      detail: t("what comes back on its own"),
    },
    {
      name: t("Settings"),
      href: pageHref("settings"),
      page: "settings",
      icon: Settings2,
      priority: 10,
      detail:
        runner?.timer === "enabled"
          ? t("timer on")
          : runner?.timer
            ? t("timer {{state}}", { state: runner.timer })
            : "",
    },
  ]

  // Every address of the board — a ticket included — is the Board entry.
  const active = (item: PaneMenuItem) =>
    item.page ? route.kind === "page" && route.page === item.page : route.kind === "resource"

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
                      tooltip={item.detail ? `${item.name} — ${item.detail}` : item.name}
                      size="lg"
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
                        {/* Two lines, so not the single span the collapsed rule
                            truncates — left to it, the rail shows the first letter
                            of each label instead of nothing. */}
                        <span className="flex min-w-0 flex-col group-data-[collapsible=icon]:hidden">
                          <span className="truncate">{item.name}</span>
                          {item.detail ? (
                            <span className="text-muted-foreground truncate font-mono text-[0.65rem] font-normal">
                              {item.detail}
                            </span>
                          ) : null}
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
