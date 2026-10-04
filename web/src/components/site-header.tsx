import { useState } from "react"
import { LoaderCircleIcon, MonitorIcon, MoonIcon, PlayIcon, SunIcon } from "lucide-react"
import { useTheme } from "next-themes"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { useAppData } from "@/hooks/app-data"

export function SiteHeader({ title }: { title: string }) {
  const { counts, processes, runAll } = useAppData()
  const { theme, setTheme } = useTheme()
  const [confirm, setConfirm] = useState(false)
  const running = processes?.jobs.length ?? 0
  const dispatching = processes?.dispatcher.active ?? false

  async function onRunAll() {
    try {
      await runAll()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mr-2 data-[orientation=vertical]:h-4" />
      <h1 className="truncate text-base font-medium">{title}</h1>
      <div className="ml-auto flex items-center gap-2">
        <div className="hidden items-center gap-1.5 sm:flex">
          {running > 0 && (
            <Badge variant="secondary">
              <LoaderCircleIcon className="animate-spin" />
              {running} đang chạy
            </Badge>
          )}
          <Badge variant="outline">{counts.queued} chờ</Badge>
        </div>
        <Button size="sm" onClick={() => setConfirm(true)} disabled={counts.queued === 0 && !dispatching}>
          <PlayIcon />
          {dispatching ? "Đang Run All" : "Run All"}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Đổi giao diện sáng/tối">
              <SunIcon className="dark:hidden" />
              <MoonIcon className="hidden dark:block" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuRadioGroup value={theme} onValueChange={setTheme}>
              <DropdownMenuRadioItem value="light">
                <SunIcon /> Sáng
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="dark">
                <MoonIcon /> Tối
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="system">
                <MonitorIcon /> Theo hệ thống
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Chạy {counts.queued} video đang chờ?</AlertDialogTitle>
            <AlertDialogDescription>
              Video được chia cho các tài khoản đã đăng nhập; mỗi lúc chạy vài video, số còn lại chờ. Tài khoản hết
              quota hoặc cần xác minh sẽ bị bỏ qua.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Huỷ</AlertDialogCancel>
            <AlertDialogAction onClick={onRunAll}>Chạy tất cả</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </header>
  )
}
