import { useEffect, useState } from "react"
import { ActivityIcon, ClockIcon, PlayCircleIcon, ScrollTextIcon, SquareIcon, UsersIcon } from "lucide-react"
import { toast } from "sonner"

import { EmptyState } from "@/components/empty-state"
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
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { useAppData } from "@/hooks/app-data"
import { navigate } from "@/hooks/use-route"
import { api, type RunningJob } from "@/lib/api"
import { fmtElapsed, stepNumber, uploadUrl } from "@/lib/format"

export function RunningPage() {
  const { processes, pairs, refreshProcesses, refreshPairs } = useAppData()
  const [stopping, setStopping] = useState<RunningJob | null>(null)

  useEffect(() => {
    refreshProcesses().catch(() => {})
    refreshPairs().catch(() => {})
  }, [refreshProcesses, refreshPairs])

  async function stop(job: RunningJob) {
    try {
      await api(`/api/pairs/${job.pair_id}/stop`, { method: "POST" })
      toast.success("Đã dừng")
      await Promise.all([refreshProcesses(), refreshPairs()])
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (!processes) {
    return (
      <div className="grid gap-4 md:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
    )
  }

  const d = processes.dispatcher
  const ready = processes.accounts.filter((a) => a.status === "ready" && !a.blocked).length
  const stats = [
    {
      label: "Run All",
      value: processes.scanning && d.active ? "Đang quét tài khoản" : d.active ? "Đang chạy" : "Nghỉ",
      icon: ActivityIcon,
    },
    {
      label: "Đang chạy / tối đa",
      value: `${processes.jobs.length} / ${d.active ? d.max_parallel || "∞" : processes.settings.max_parallel}`,
      icon: PlayCircleIcon,
    },
    { label: "Đang chờ", value: String(processes.queued), icon: ClockIcon },
    { label: "Tài khoản sẵn sàng", value: `${ready} / ${processes.accounts.length}`, icon: UsersIcon },
  ]

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label} className="gap-1 transition-colors hover:border-primary/40">
            <CardHeader>
              <CardDescription>{s.label}</CardDescription>
              <CardAction>
                <s.icon className="size-4 text-muted-foreground" />
              </CardAction>
            </CardHeader>
            <CardContent>
              <p className="font-heading text-2xl font-semibold tracking-tight tabular-nums">{s.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {!processes.jobs.length ? (
        <EmptyState
          icon={PlayCircleIcon}
          title="Không có video nào đang chạy"
          description={processes.queued ? `${processes.queued} video đang chờ — bấm Run All để chạy.` : undefined}
          action={<Button onClick={() => navigate("queue")}>Mở hàng đợi</Button>}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {processes.jobs.map((j) => {
            const pair = pairs?.find((p) => p.id === j.pair_id)
            const n = stepNumber(j.step)
            return (
              <Card key={j.pair_id}>
                <CardHeader>
                  <div className="flex items-center gap-3">
                    <img
                      src={uploadUrl(pair?.product_image ?? pair?.image)}
                      alt=""
                      className="size-11 rounded-md border bg-muted object-cover"
                    />
                    <div className="min-w-0">
                      <CardTitle className="truncate">{pair?.product_name || j.image}</CardTitle>
                      <CardDescription className="truncate">{pair?.prompt_name}</CardDescription>
                    </div>
                  </div>
                  <CardAction>
                    <Badge variant="outline" className="tabular-nums">
                      {fmtElapsed(j.elapsed_s)}
                    </Badge>
                  </CardAction>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-xs">
                      <span className="truncate">{j.step ?? "Đang khởi động…"}</span>
                      <span className="text-muted-foreground tabular-nums">{n}/7</span>
                    </div>
                    <Progress value={(n / 7) * 100} aria-label="Tiến độ" />
                  </div>
                  <p className="truncate font-mono text-xs text-muted-foreground" title={j.last_log ?? ""}>
                    {j.last_log}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {j.account}
                    {j.email ? ` · ${j.email}` : ""}
                    {j.headless ? " · ẩn trình duyệt" : ""}
                  </p>
                </CardContent>
                <CardFooter className="gap-2">
                  <Button size="sm" variant="outline" onClick={() => navigate("queue", { pair: j.pair_id, tab: "log" })}>
                    <ScrollTextIcon /> Log
                  </Button>
                  <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setStopping(j)}>
                    <SquareIcon /> Dừng
                  </Button>
                </CardFooter>
              </Card>
            )
          })}
        </div>
      )}

      <AlertDialog open={!!stopping} onOpenChange={(o) => !o && setStopping(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Dừng video này?</AlertDialogTitle>
            <AlertDialogDescription>Trình duyệt của job bị đóng và job được đánh dấu lỗi.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Huỷ</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => stopping && stop(stopping)}>
              Dừng
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
