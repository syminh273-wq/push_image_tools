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

const PAGES: Record<Page, { title: string; render: () => React.ReactNode }> = {
  create: { title: "Tạo video quảng cáo", render: () => <CreateVideoPage /> },
  queue: { title: "Hàng đợi", render: () => <QueuePage /> },
  running: { title: "Đang chạy", render: () => <RunningPage /> },
  gallery: { title: "Thư viện video", render: () => <GalleryPage /> },
  prompts: { title: "Thư viện Prompt", render: () => <PromptsPage /> },
  models: { title: "Thư viện Model", render: () => <ModelsPage /> },
  accounts: { title: "Tài khoản", render: () => <AccountsPage /> },
  settings: { title: "Cài đặt", render: () => <SettingsPage /> },
}

export default function App() {
  const { page } = useRoute()
  const current = PAGES[page]
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <SiteHeader title={current.title} />
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-6">{current.render()}</main>
      </SidebarInset>
    </SidebarProvider>
  )
}
