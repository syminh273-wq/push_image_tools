import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { useRoute, type Page } from "@/hooks/use-route"
import { AccountsPage } from "@/pages/accounts"
import { CreateVideoPage } from "@/pages/create-video"
import { GalleryPage } from "@/pages/gallery"
import { ModelsPage } from "@/pages/models"
import { PromptsPage } from "@/pages/prompts"
import { QueuePage } from "@/pages/queue"
import { RunningPage } from "@/pages/running"
import { SettingsPage } from "@/pages/settings"
import { TikTokPage } from "@/pages/tiktok"

const PAGES: Record<Page, { title: string; render: () => React.ReactNode }> = {
  create: { title: "Tạo video quảng cáo", render: () => <CreateVideoPage /> },
  queue: { title: "Hàng đợi", render: () => <QueuePage /> },
  running: { title: "Đang chạy", render: () => <RunningPage /> },
  gallery: { title: "Thư viện video", render: () => <GalleryPage /> },
  prompts: { title: "Thư viện Prompt", render: () => <PromptsPage /> },
  models: { title: "Thư viện Model", render: () => <ModelsPage /> },
  accounts: { title: "Tài khoản", render: () => <AccountsPage /> },
  settings: { title: "Cài đặt", render: () => <SettingsPage /> },
  tiktok: { title: "TikTok manager", render: () => <TikTokPage /> },
}

export default function App() {
  const { page } = useRoute()
  const current = PAGES[page]
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <SiteHeader title={current.title} />
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8 md:py-8">{current.render()}</main>
      </SidebarInset>
    </SidebarProvider>
  )
}
