import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  ArrowDownIcon,
  CheckCircle2Icon,
  CircleDotIcon,
  ExternalLinkIcon,
  GlobeIcon,
  HashIcon,
  Loader2Icon,
  MessageSquareIcon,
  PowerIcon,
  PowerOffIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
  ShieldOffIcon,
  StopCircleIcon,
  VideoIcon,
  XCircleIcon,
} from "lucide-react"
import { toast } from "sonner"

import { EmptyState } from "@/components/empty-state"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { PageHeader } from "@/components/page-header"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { api, type TikTokChrome, type TikTokTab, type TikTokTabsResponse } from "@/lib/api"

// The desktop build is TikTok-only and ships with its own Chrome launcher; the web build
// expects the user to start Chrome with remote debugging themselves.
const IS_DESKTOP = import.meta.env.VITE_APP_MODE === "tiktok"

const DEFAULT_TEMPLATES = [
  "chắc k có ai để ý",
  "ai để ý tí đi",
  "cả nhà ai để ý tí đi",
]

function templateKey(t: TikTokTab) {
  return t.uid
}

/** Always-on SSE subscriber for a single tab. Renders nothing.
 *  Used so each running card can show live counters + a rolling mini-log
 *  without the user opening the Log dialog. The server replays the buffered
 *  lines on connect, so the local buffer is reset first to avoid duplicates. */
function LiveSse({
  uid,
  onState,
  onLog,
  onReset,
}: {
  uid: string
  onState: (uid: string, state: Record<string, unknown>) => void
  onLog: (uid: string, line: string) => void
  onReset: (uid: string) => void
}) {
  const ref = useRef<EventSource | null>(null)
  useEffect(() => {
    onReset(uid)
    const es = new EventSource(`/api/tiktok/stream/${uid}`)
    ref.current = es
    es.addEventListener("log", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as { line: string }
        onLog(uid, data.line)
      } catch {}
    })
    es.addEventListener("state", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as Record<string, unknown>
        onState(uid, data)
      } catch {}
    })
    return () => {
      es.close()
      ref.current = null
    }
  }, [uid, onState, onLog, onReset])
  return null
}

function statusTone(tab: TikTokTab): "default" | "outline" | "destructive" | "secondary" {
  if (!tab.logged_in) return "destructive"
  if (tab.state.is_running) return "default"
  if (tab.active) return "secondary"
  return "outline"
}

function statusLabel(tab: TikTokTab): string {
  if (!tab.logged_in) return "Chưa đăng nhập"
  if (tab.state.is_running) return "Đang chạy"
  if (tab.active) return "Đang mở"
  return "Nền"
}

function RunDialog({
  open,
  onOpenChange,
  tab,
  onRun,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  tab: TikTokTab | null
  onRun: (cfg: { templates: string[]; videoUrl: string; dwell: number; max: number; scroll: boolean; headless: boolean }) => Promise<void>
}) {
  const [templates, setTemplates] = useState<string>("")
  const [videoUrl, setVideoUrl] = useState<string>("")
  const [dwell, setDwell] = useState<number>(3)
  const [max, setMax] = useState<number>(20)
  const [scroll, setScroll] = useState<boolean>(true)
  const [headless, setHeadless] = useState<boolean>(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) {
      setTemplates(DEFAULT_TEMPLATES.join("\n"))
      setVideoUrl("")
      setDwell(3)
      setMax(20)
      setScroll(true)
      setHeadless(false)
    }
  }, [open, tab?.uid])

  const submit = async () => {
    const list = templates
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean)
    if (!list.length) {
      toast.error("Cần ít nhất 1 mẫu comment")
      return
    }
    setBusy(true)
    try {
      await onRun({ templates: list, videoUrl: videoUrl.trim(), dwell, max, scroll, headless })
      onOpenChange(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Chạy auto-comment</DialogTitle>
          <DialogDescription>
            Tab <span className="font-medium">{tab?.title || tab?.url}</span>. Mỗi video: đợi dwell → comment → cuộn sang video kế.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="tiktok-templates">Mẫu comment (xoay vòng)</Label>
            <Textarea
              id="tiktok-templates"
              value={templates}
              onChange={(e) => setTemplates(e.target.value)}
              rows={5}
              placeholder="Mỗi dòng 1 mẫu"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="tiktok-video">Video URL (tùy chọn)</Label>
            <Input
              id="tiktok-video"
              value={videoUrl}
              onChange={(e) => setVideoUrl(e.target.value)}
              placeholder="https://www.tiktok.com/@user/video/... — bỏ trống để chạy feed For You"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-2">
              <Label htmlFor="tiktok-dwell">Dwell (giây)</Label>
              <Input
                id="tiktok-dwell"
                type="number"
                min={1}
                max={60}
                value={dwell}
                onChange={(e) => setDwell(Number(e.target.value) || 4)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="tiktok-max">Số comment tối đa</Label>
              <Input
                id="tiktok-max"
                type="number"
                min={1}
                max={500}
                value={max}
                onChange={(e) => setMax(Number(e.target.value) || 1)}
              />
            </div>
          </div>
          <div className="flex items-center justify-between rounded-md border px-3 py-2">
            <div className="grid gap-0.5">
              <Label htmlFor="tiktok-scroll">Cuộn feed sau mỗi comment</Label>
              <span className="text-xs text-muted-foreground">Tắt nếu bạn chỉ muốn comment 1 video.</span>
            </div>
            <Switch id="tiktok-scroll" checked={scroll} onCheckedChange={setScroll} />
          </div>
          <div className="flex items-center justify-between rounded-md border px-3 py-2">
            <div className="grid gap-0.5">
              <Label htmlFor="tiktok-headless">Chạy ngầm (invisible Chrome)</Label>
              <span className="text-xs text-muted-foreground">
                Dùng Chrome riêng, không hiện lên UI. Cần đăng nhập TikTok 1 lần qua nút "Đăng nhập ngầm".
              </span>
            </div>
            <Switch id="tiktok-headless" checked={headless} onCheckedChange={setHeadless} />
          </div>
        </div>
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline" disabled={busy}>
              Huỷ
            </Button>
          </DialogClose>
          <Button onClick={submit} disabled={busy}>
            {busy ? <Loader2Icon className="animate-spin" data-icon="inline-start" /> : <PowerIcon data-icon="inline-start" />}
            Bắt đầu chạy
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function TabCard({
  tab,
  lines,
  onRun,
  onStop,
}: {
  tab: TikTokTab
  lines?: { line: string; ts: number }[]
  onRun: (uid: string) => void
  onStop: (uid: string) => void
}) {
  const tone = statusTone(tab)
  const disabled = !tab.logged_in || tab.state.is_running
  const failed = tab.state.comments_failed
  const recentLines = (lines ?? []).slice(-4)
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex flex-wrap items-center gap-1.5">
          {tab.source === "chrome" ? (
            <Badge variant="outline" className="gap-1">
              <GlobeIcon className="size-3" aria-hidden /> debug web {tab.chrome_label}
              {tab.debug_port ? <span className="font-mono text-[10px] text-muted-foreground">:{tab.debug_port}</span> : null}
            </Badge>
          ) : (
            <Badge variant="outline" className="gap-1">
              <VideoIcon className="size-3" aria-hidden /> profile
            </Badge>
          )}
        </div>
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 flex-col gap-1">
            <CardDescription className="flex items-center gap-1.5">
              <HashIcon className="size-3.5" aria-hidden />
              <span className="truncate font-mono text-xs">{tab.uid}</span>
            </CardDescription>
            <CardTitle className="line-clamp-1 text-base">{tab.title || "TikTok"}</CardTitle>
          </div>
          <div className="flex flex-col items-end gap-1">
            <Badge variant={tone}>{statusLabel(tab)}</Badge>
            {tab.active ? <Badge variant="outline">active</Badge> : null}
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        <a
          href={tab.url}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1 truncate text-xs text-muted-foreground hover:text-foreground hover:underline"
        >
          <ExternalLinkIcon className="size-3.5 shrink-0" aria-hidden />
          <span className="truncate">{tab.url}</span>
        </a>
        <div className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
          <span className="flex items-center gap-1.5">
            {tab.logged_in ? (
              <ShieldCheckIcon className="size-4 text-emerald-500" aria-hidden />
            ) : (
              <ShieldOffIcon className="size-4 text-destructive" aria-hidden />
            )}
            {tab.logged_in ? "Đã đăng nhập" : "Chưa đăng nhập"}
          </span>
          <span className="text-xs text-muted-foreground">{tab.active ? "tab đang xem" : "tab nền"}</span>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="rounded-md border px-2 py-2">
            <div className="text-lg font-semibold tabular-nums">{tab.state.comments_sent}</div>
            <div className="text-[11px] text-muted-foreground">đã gửi</div>
          </div>
          <div className="rounded-md border px-2 py-2">
            <div className="text-lg font-semibold tabular-nums text-destructive">{failed}</div>
            <div className="text-[11px] text-muted-foreground">lỗi</div>
          </div>
          <div className="rounded-md border px-2 py-2">
            <div className="truncate text-xs">
              {tab.state.last_comment ? new Date(tab.state.last_comment).toLocaleTimeString() : "—"}
            </div>
            <div className="text-[11px] text-muted-foreground">lần cuối</div>
          </div>
        </div>
        {recentLines.length > 0 ? (
          <div className="rounded-md border bg-muted/40 px-3 py-2 font-mono text-[11px] leading-snug">
            <div className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">log gần đây</div>
            <div className="flex flex-col gap-0.5">
              {recentLines.map((l, i) => (
                <div key={l.ts + i} className="line-clamp-1 text-foreground/80" title={l.line}>
                  {l.line}
                </div>
              ))}
            </div>
          </div>
        ) : null}
        {tab.state.last_error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {tab.state.last_error}
          </div>
        ) : null}
        {tab.state.current_video && tab.state.current_video !== tab.url ? (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <ArrowDownIcon className="size-3.5" aria-hidden /> đang xem: <span className="truncate">{tab.state.current_video}</span>
          </div>
        ) : null}
      </CardContent>
      <div className="flex gap-2 p-4 pt-0">
        {tab.state.is_running ? (
          <Button variant="outline" className="flex-1" onClick={() => onStop(tab.uid)}>
            <StopCircleIcon data-icon="inline-start" /> Dừng
          </Button>
        ) : (
          <Button className="flex-1" onClick={() => onRun(tab.uid)} disabled={disabled}>
            <PowerIcon data-icon="inline-start" /> Chạy bot
          </Button>
        )}
      </div>
    </Card>
  )
}

function LogPanel({
  uid,
  open,
  onClose,
  onLiveState,
}: {
  uid: string | null
  open: boolean
  onClose: () => void
  onLiveState?: (uid: string, state: Record<string, unknown>) => void
}) {
  const [lines, setLines] = useState<{ line: string; ts: number }[]>([])
  const [state, setState] = useState<{ comments_sent?: number; comments_failed?: number; last_error?: string | null; is_running?: boolean } | null>(null)
  const ref = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!uid || !open) return
    setLines([])
    setState(null)
    const es = new EventSource(`/api/tiktok/stream/${uid}`)
    ref.current = es
    es.addEventListener("log", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as { line: string }
        setLines((prev) => [...prev.slice(-199), { line: data.line, ts: Date.now() }])
      } catch {}
    })
    es.addEventListener("state", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as Record<string, unknown>
        setState(data as { comments_sent?: number; comments_failed?: number; last_error?: string | null; is_running?: boolean })
        onLiveState?.(uid, data)
      } catch {}
    })
    return () => {
      es.close()
      ref.current = null
    }
  }, [uid, open, onLiveState])

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <MessageSquareIcon className="size-4" /> Log tab <span className="font-mono text-xs">{uid}</span>
          </DialogTitle>
          <DialogDescription>
            {state?.is_running ? (
              <span className="flex items-center gap-2 text-emerald-600">
                <CircleDotIcon className="size-3 animate-pulse" /> đang chạy — {state.comments_sent ?? 0} gửi / {state.comments_failed ?? 0} lỗi
              </span>
            ) : (
              <span className="flex items-center gap-2 text-muted-foreground">
                <CheckCircle2Icon className="size-3" /> đã dừng
              </span>
            )}
          </DialogDescription>
        </DialogHeader>
        <ScrollArea className="h-80 rounded-md border bg-muted/40 p-3 font-mono text-xs">
          {lines.length ? (
            lines.map((l, i) => (
              <div key={i} className="whitespace-pre-wrap break-all">
                {l.line}
              </div>
            ))
          ) : (
            <div className="text-muted-foreground">Chưa có log…</div>
          )}
        </ScrollArea>
        {state?.last_error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            <XCircleIcon className="mr-1 inline size-3" />
            {state.last_error}
          </div>
        ) : null}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Đóng</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function TikTokPage() {
  const [tabs, setTabs] = useState<TikTokTab[] | null>(null)
  const [chromes, setChromes] = useState<TikTokChrome[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogTab, setDialogTab] = useState<TikTokTab | null>(null)
  const [logUid, setLogUid] = useState<string | null>(null)
  // Live log lines per uid — collected from SSE so each card can show the last
  // few lines without the user opening the Log dialog.
  const [linesByUid, setLinesByUid] = useState<Record<string, { line: string; ts: number }[]>>({})

  const refresh = useCallback(async () => {
    try {
      const data = await api<TikTokTabsResponse>("/api/tiktok/tabs")
      setTabs(data.tabs)
      setChromes(data.chromes ?? [])
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  // Scan only on first mount and on explicit user action — no auto polling.
  // Live counters/logs come from the SSE stream below, so we don't need to
  // hammer /api/tiktok/tabs in the background.
  useEffect(() => {
    refresh()
  }, [refresh])

  // Append a single log line to the matching tab's mini-log buffer.
  const handleLiveLog = useCallback((uid: string, line: string) => {
    setLinesByUid((prev) => {
      const cur = prev[uid] || []
      const next = [...cur.slice(-49), { line, ts: Date.now() }]
      return { ...prev, [uid]: next }
    })
  }, [])

  // Start a bot's log buffer from empty when its stream (re)connects. Logs are kept after a
  // run stops, so the user can still read both bots' output; only the Xóa button removes them.
  const resetLog = useCallback((uid: string) => {
    setLinesByUid((prev) => ({ ...prev, [uid]: [] }))
  }, [])

  // Merge a live SSE state snapshot into the matching tab so the cards show
  // counters that match the latest log lines.
  const handleLiveState = useCallback((uid: string, state: Record<string, unknown>) => {
    setTabs((prev) => {
      if (!prev) return prev
      let changed = false
      const next = prev.map((t) => {
        if (t.uid !== uid) return t
        const merged = { ...t.state, ...state }
        // Skip the update if nothing actually changed (cheap shallow compare).
        let same = true
        for (const k of Object.keys(state) as (keyof typeof merged)[]) {
          if (merged[k] !== (t.state as Record<string, unknown>)[k as string]) {
            same = false
            break
          }
        }
        if (same) return t
        changed = true
        return { ...t, state: merged }
      })
      return changed ? next : prev
    })
  }, [])

  const handleRun = useCallback(
    async (cfg: { templates: string[]; videoUrl: string; dwell: number; max: number; scroll: boolean; headless: boolean }) => {
      if (!dialogTab) return
      try {
        await api(`/api/tiktok/tabs/${dialogTab.uid}/run`, {
          method: "POST",
          json: {
            templates: cfg.templates,
            video_url: cfg.videoUrl,
            dwell_seconds: cfg.dwell,
            max_comments: cfg.max,
            scroll_after_each: cfg.scroll,
            headless: cfg.headless,
          },
        })
        toast.success(cfg.headless ? "Bot đã bắt đầu (chạy ngầm) — xem log để theo dõi" : "Bot đã bắt đầu — xem log để theo dõi")
        setLogUid(dialogTab.uid)
        await refresh()
      } catch (e) {
        toast.error((e as Error).message)
      }
    },
    [dialogTab, refresh],
  )

  const handleStop = useCallback(
    async (uid: string) => {
      try {
        await api(`/api/tiktok/tabs/${uid}/stop`, { method: "POST" })
        toast.success("Đã dừng bot")
        await refresh()
      } catch (e) {
        toast.error((e as Error).message)
      }
    },
    [refresh],
  )

  const logTabs = useMemo(
    () => (tabs ?? []).filter((t) => (linesByUid[t.uid] ?? []).length > 0 || t.state.is_running),
    [tabs, linesByUid],
  )

  const summary = useMemo(() => {
    const all = tabs ?? []
    return {
      total: all.length,
      loggedIn: all.filter((t) => t.logged_in).length,
      running: all.filter((t) => t.state.is_running).length,
      active: all.filter((t) => t.active).length,
      comments: all.reduce((s, t) => s + t.state.comments_sent, 0),
    }
  }, [tabs])

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon={VideoIcon}
        title="TikTok manager"
        description="Quét Chrome qua CDP, liệt kê các tab TikTok đang mở và chạy auto-comment trên tab đã đăng nhập."
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="gap-1.5">
            <VideoIcon className="size-3" /> {summary.total} tab
          </Badge>
          <Badge variant="outline" className="gap-1.5">
            <ShieldCheckIcon className="size-3" /> {summary.loggedIn} login
          </Badge>
          <Badge variant="outline" className="gap-1.5">
            <CircleDotIcon className="size-3" /> {summary.active} active
          </Badge>
          <Badge variant="outline" className="gap-1.5">
            <PowerIcon className="size-3" /> {summary.running} đang chạy
          </Badge>
          {chromes.map((c) => (
            <Badge key={c.port} variant={c.alive ? "secondary" : "outline"} className="gap-1.5">
              <GlobeIcon className="size-3" /> debug web {c.label}
              <span className="font-mono text-[10px] text-muted-foreground">:{c.port}</span>
              {c.alive ? `· ${c.tabs} tab` : "· đã tắt"}
            </Badge>
          ))}
          <Button
            variant="destructive"
            size="sm"
            disabled={summary.running === 0}
            onClick={async () => {
              try {
                const r = await api<{ ok: boolean; stopped: string[] }>("/api/tiktok/stop-all", { method: "POST" })
                toast.success(r.stopped.length ? `Đã dừng ${r.stopped.length} bot` : "Không có bot nào đang chạy")
                await refresh()
              } catch (e) {
                toast.error((e as Error).message)
              }
            }}
          >
            <StopCircleIcon data-icon="inline-start" /> Dừng tất cả
          </Button>
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
            <RefreshCwIcon className={loading ? "animate-spin" : undefined} data-icon="inline-start" />
            Quét lại
          </Button>
          {IS_DESKTOP && (
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                try {
                  const r = await api<{ ok: boolean; chrome?: { label: string; port: number } }>(
                    "/api/tiktok/chrome/start",
                    { method: "POST" },
                  )
                  const where = r.chrome ? ` ${r.chrome.label} (cổng ${r.chrome.port})` : ""
                  toast.success(
                    `Đã mở debug web${where}. Đăng nhập TikTok trong cửa sổ đó rồi bấm Quét lại.`,
                  )
                  await refresh()
                } catch (e) {
                  toast.error((e as Error).message)
                }
              }}
            >
              <ExternalLinkIcon data-icon="inline-start" /> Mở Chrome debug
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={async () => {
              try {
                await api("/api/tiktok/scan", { method: "POST" })
                await refresh()
              } catch (e) {
                toast.error((e as Error).message)
              }
            }}
          >
            <PowerOffIcon data-icon="inline-start" /> Force reconnect CDP
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={async () => {
              try {
                const r = await api<{ ok: boolean; message: string }>(
                  "/api/tiktok/headless-login",
                  { method: "POST" },
                )
                if (r.ok) {
                  toast.success(r.message, { duration: 10000 })
                }
              } catch (e) {
                toast.error((e as Error).message)
              }
            }}
          >
            <ShieldCheckIcon data-icon="inline-start" /> Đăng nhập ngầm
          </Button>
        </div>
      </PageHeader>

      {loading && !tabs ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-64 rounded-xl" />
          ))}
        </div>
      ) : !tabs || tabs.length === 0 ? (
        <EmptyState
          icon={VideoIcon}
          title="Chưa có tab TikTok nào"
          description={
            IS_DESKTOP
              ? "Bấm “Mở Chrome debug”, mở tiktok.com/…/video/… trong cửa sổ Chrome đó và đăng nhập, rồi bấm Quét lại."
              : "Mở tiktok.com/…/video/… trong Chrome đang bật remote debugging (cổng 9222), rồi bấm Quét lại."
          }
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {tabs.map((t) => (
            <div key={templateKey(t)} className="flex flex-col gap-2">
              <TabCard tab={t} lines={linesByUid[t.uid]} onRun={(uid) => setDialogTab(tabs.find((x) => x.uid === uid) || null)} onStop={handleStop} />
              <Button variant="ghost" size="sm" onClick={() => setLogUid(t.uid)}>
                <MessageSquareIcon data-icon="inline-start" /> Mở log đầy đủ
              </Button>
            </div>
          ))}
        </div>
      )}

      {logTabs.length > 0 ? (
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium">Log các bot</h2>
            <Button variant="ghost" size="sm" onClick={() => setLinesByUid({})}>
              <XCircleIcon data-icon="inline-start" /> Xóa log
            </Button>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {logTabs.map((t) => (
              <Card key={t.uid}>
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center gap-2 text-sm">
                    <span className="line-clamp-1 min-w-0">{t.title || t.uid}</span>
                    {t.chrome_label ? <Badge variant="outline">{t.chrome_label}</Badge> : null}
                    {t.state.is_running ? <Badge variant="default">đang chạy</Badge> : null}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <ScrollArea className="h-56 rounded-md border bg-muted/40 p-3 font-mono text-xs">
                    {(linesByUid[t.uid] ?? []).map((l, i) => (
                      <div key={l.ts + "-" + i} className="whitespace-pre-wrap break-all">
                        {l.line}
                      </div>
                    ))}
                  </ScrollArea>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      ) : null}

      <RunDialog open={!!dialogTab} onOpenChange={(v) => !v && setDialogTab(null)} tab={dialogTab} onRun={handleRun} />
      <LogPanel uid={logUid} open={!!logUid} onClose={() => setLogUid(null)} onLiveState={handleLiveState} />

      {/* Hidden per-tab SSE subscribers so the cards always show live counters + logs. */}
      {(tabs ?? []).filter((t) => t.state.is_running).map((t) => (
        <LiveSse
          key={t.uid}
          uid={t.uid}
          onState={handleLiveState}
          onLog={handleLiveLog}
          onReset={resetLog}
        />
      ))}
    </div>
  )
}