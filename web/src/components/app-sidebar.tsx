import {
  ClapperboardIcon,
  CogIcon,
  FilmIcon,
  ListOrderedIcon,
  PlayCircleIcon,
  ScrollTextIcon,
  SparklesIcon,
  UserCircleIcon,
  UsersIcon,
  VideoIcon,
  type LucideIcon,
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
  useSidebar,
} from "@/components/ui/sidebar"
import { useAppData } from "@/hooks/app-data"
import { navigate, useRoute, type Page } from "@/hooks/use-route"

type Item = { page: Page; label: string; icon: LucideIcon; badge?: number }

export function AppSidebar() {
  const { page } = useRoute()
  const { counts, processes } = useAppData()
  const { isMobile, setOpenMobile } = useSidebar()

  const groups: { label: string; items: Item[] }[] = [
    { label: "Tạo", items: [{ page: "create", label: "Tạo video", icon: SparklesIcon }] },
    {
      label: "Quản lý",
      items: [
        { page: "queue", label: "Hàng đợi", icon: ListOrderedIcon, badge: counts.queued },
        { page: "running", label: "Đang chạy", icon: PlayCircleIcon, badge: processes?.jobs.length },
        { page: "gallery", label: "Thư viện video", icon: FilmIcon },
      ],
    },
    {
      label: "Cấu hình",
      items: [
        { page: "prompts", label: "Thư viện Prompt", icon: ScrollTextIcon },
        { page: "models", label: "Thư viện Model", icon: UserCircleIcon },
        { page: "accounts", label: "Tài khoản", icon: UsersIcon },
        { page: "settings", label: "Cài đặt", icon: CogIcon },
        { page: "tiktok", label: "TikTok manager", icon: VideoIcon },
      ],
    },
  ]

  const ready = processes?.accounts.filter((a) => a.status === "ready" && !a.blocked).length ?? 0
  const total = processes?.accounts.length ?? 0

  function go(p: Page) {
    navigate(p)
    if (isMobile) setOpenMobile(false)
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" onClick={() => go("create")} tooltip="Ad Studio">
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                <ClapperboardIcon className="size-4" />
              </div>
              <div className="grid flex-1 text-left leading-tight">
                <span className="truncate font-semibold">Ad Studio</span>
                <span className="truncate text-xs text-muted-foreground">Video quảng cáo bằng Gemini</span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {groups.map((g) => (
          <SidebarGroup key={g.label}>
            <SidebarGroupLabel>{g.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {g.items.map((it) => (
                  <SidebarMenuItem key={it.page}>
                    <SidebarMenuButton isActive={page === it.page} tooltip={it.label} onClick={() => go(it.page)}>
                      <it.icon />
                      <span>{it.label}</span>
                    </SidebarMenuButton>
                    {!!it.badge && <SidebarMenuBadge>{it.badge}</SidebarMenuBadge>}
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton tooltip="Tài khoản sẵn sàng" onClick={() => go("accounts")}>
              <UsersIcon />
              <span className="text-xs text-muted-foreground">
                {ready}/{total} tài khoản sẵn sàng
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
