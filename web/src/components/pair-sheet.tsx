import { useEffect, useRef, useState } from "react"
import { DownloadIcon, PlayIcon, RotateCcwIcon, Trash2Icon } from "lucide-react"
import { toast } from "sonner"

import { StatusBadge } from "@/components/status-badge"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useAppData } from "@/hooks/app-data"
import { api, type Pair } from "@/lib/api"
import { fmtTime, outputUrl, uploadUrl } from "@/lib/format"

function useLog(pairId: string | null) {
  const [lines, setLines] = useState<string[]>([])
  useEffect(() => {
    setLines([])
    if (!pairId) return
    const es = new EventSource(`/api/stream/${pairId}`)
    es.addEventListener("log", (e) => setLines((l) => [...l.slice(-999), JSON.parse((e as MessageEvent).data)]))
    es.addEventListener("end", () => es.close())
    return () => es.close()
  }, [pairId])
  return lines
}

export function PairSheet({
  pairId,
  onOpenChange,
  defaultTab = "detail",
}: {
  pairId: string | null
  onOpenChange: (open: boolean) => void
  defaultTab?: "detail" | "log" | "output"
}) {
  const { pairs, runPair, refreshPairs } = useAppData()
  const pair = pairs?.find((p) => p.id === pairId) ?? null
  const [tab, setTab] = useState(defaultTab)
  const lines = useLog(pairId && pair?.status !== "queued" ? pairId : null)
  const logEnd = useRef<HTMLDivElement>(null)

  useEffect(() => setTab(defaultTab), [pairId, defaultTab])
  useEffect(() => logEnd.current?.scrollIntoView({ block: "end" }), [lines.length, tab])

  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn()
      toast.success(ok)
      await refreshPairs()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <Sheet open={!!pairId} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl">
        {pair && (
          <>
            <SheetHeader className="border-b">
              <div className="flex items-center gap-2">
                <StatusBadge status={pair.status} />
                <Badge variant="outline">{pair.prompt_name ?? "—"}</Badge>
              </div>
              <SheetTitle>{pair.product_name || pair.prompt_name || pair.id}</SheetTitle>
              <SheetDescription>
                Tạo lúc {fmtTime(pair.created_at)} · tài khoản{" "}
                {pair.assigned_account ?? (pair.account && pair.account !== "auto" ? pair.account : "tự chọn")}
              </SheetDescription>
            </SheetHeader>

            <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)} className="min-h-0 flex-1 p-4">
              <TabsList>
                <TabsTrigger value="detail">Chi tiết</TabsTrigger>
                <TabsTrigger value="log">Log</TabsTrigger>
                <TabsTrigger value="output" disabled={!pair.output}>
                  Kết quả
                </TabsTrigger>
              </TabsList>

              <TabsContent value="detail" className="min-h-0">
                <ScrollArea className="h-full pr-3">
                  <PairDetail pair={pair} />
                </ScrollArea>
              </TabsContent>

              <TabsContent value="log" className="min-h-0">
                <ScrollArea className="h-full rounded-lg border bg-muted/40">
                  <pre className="p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                    {lines.length ? lines.join("\n") : "Chưa có log — job chưa chạy."}
                  </pre>
                  <div ref={logEnd} />
                </ScrollArea>
              </TabsContent>

              <TabsContent value="output">
                {pair.output && (
                  <div className="space-y-3">
                    <video src={outputUrl(pair.output)} controls className="w-full rounded-lg border bg-muted" />
                    <Button asChild variant="outline">
                      <a href={outputUrl(pair.output)} download>
                        <DownloadIcon /> Tải video
                      </a>
                    </Button>
                  </div>
                )}
              </TabsContent>
            </Tabs>

            <SheetFooter className="flex-row justify-end border-t">
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button variant="ghost" className="mr-auto text-destructive" disabled={pair.status === "running"}>
                    <Trash2Icon /> Xoá
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Xoá job này?</AlertDialogTitle>
                    <AlertDialogDescription>Job và log bị xoá; video đã tạo (nếu có) vẫn giữ trong thư viện.</AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Huỷ</AlertDialogCancel>
                    <AlertDialogAction
                      variant="destructive"
                      onClick={() =>
                        act(() => api(`/api/pairs/${pair.id}`, { method: "DELETE" }), "Đã xoá").then(() =>
                          onOpenChange(false),
                        )
                      }
                    >
                      Xoá
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
              {(pair.status === "failed" || pair.status === "done") && (
                <Button variant="outline" onClick={() => act(() => runPair(pair.id), "Đã chạy lại")}>
                  <RotateCcwIcon /> Chạy lại
                </Button>
              )}
              {pair.status === "queued" && (
                <Button
                  onClick={() =>
                    act(() => runPair(pair.id), "Đã bắt đầu chạy").then(() => setTab("log"))
                  }
                >
                  <PlayIcon /> Chạy ngay
                </Button>
              )}
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

function PairDetail({ pair }: { pair: Pair }) {
  const media = [
    pair.model_image && { label: "Người mẫu", src: uploadUrl(pair.model_image), video: false },
    pair.product_image && { label: "Sản phẩm", src: uploadUrl(pair.product_image), video: false },
    pair.video && { label: "Video mẫu", src: uploadUrl(pair.video), video: true },
  ].filter(Boolean) as { label: string; src: string; video: boolean }[]

  return (
    <div className="space-y-4 py-2">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {media.map((m) => (
          <figure key={m.label} className="space-y-1">
            {m.video ? (
              <video src={m.src} controls muted className="aspect-square w-full rounded-lg border bg-muted object-cover" />
            ) : (
              <img src={m.src} alt={m.label} className="aspect-square w-full rounded-lg border bg-muted object-cover" />
            )}
            <figcaption className="text-xs text-muted-foreground">{m.label}</figcaption>
          </figure>
        ))}
      </div>
      <div className="space-y-1.5">
        <p className="text-sm font-medium">Prompt gửi cho Gemini</p>
        <p className="rounded-lg border bg-muted/40 p-3 text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">
          {pair.prompt}
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Bắt đầu</dt>
        <dd>{fmtTime(pair.started_at)}</dd>
        <dt className="text-muted-foreground">Kết thúc</dt>
        <dd>{fmtTime(pair.finished_at)}</dd>
        <dt className="text-muted-foreground">Số lần thử</dt>
        <dd>{pair.retry_count ?? 0}</dd>
        <dt className="text-muted-foreground">Timeout</dt>
        <dd>{pair.timeout}s</dd>
      </dl>
    </div>
  )
}
