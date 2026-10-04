import { useEffect, useState } from "react"
import { DownloadIcon, FilmIcon, SparklesIcon } from "lucide-react"

import { EmptyState } from "@/components/empty-state"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useAppData } from "@/hooks/app-data"
import { navigate } from "@/hooks/use-route"
import type { Category, OutputFile } from "@/lib/api"
import { CATEGORIES, categoryOf, fmtSize, fmtTime } from "@/lib/format"

export function GalleryPage() {
  const { outputs, refreshOutputs } = useAppData()
  const [filter, setFilter] = useState<"all" | Category>("all")
  const [open, setOpen] = useState<OutputFile | null>(null)

  useEffect(() => {
    refreshOutputs().catch(() => {})
  }, [refreshOutputs])

  if (!outputs) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="aspect-video rounded-xl" />
        ))}
      </div>
    )
  }
  if (!outputs.length) {
    return (
      <EmptyState
        icon={FilmIcon}
        title="Chưa có video nào"
        description="Video tạo xong sẽ hiện ở đây."
        action={
          <Button onClick={() => navigate("create")}>
            <SparklesIcon /> Tạo video
          </Button>
        }
      />
    )
  }

  const used = CATEGORIES.filter((c) => outputs.some((o) => o.category === c.value))
  const list = outputs.filter((o) => filter === "all" || o.category === filter)

  return (
    <div className="space-y-4">
      {used.length > 0 && (
        <Tabs value={filter} onValueChange={(v) => setFilter(v as typeof filter)} className="overflow-x-auto">
          <TabsList>
            <TabsTrigger value="all">Tất cả ({outputs.length})</TabsTrigger>
            {used.map((c) => (
              <TabsTrigger key={c.value} value={c.value}>
                <c.icon /> {c.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {list.map((f) => {
          const c = f.category ? categoryOf(f.category) : null
          return (
            <Card key={f.name} className="overflow-hidden pt-0">
              <Button
                variant="ghost"
                className="block aspect-video h-auto w-full rounded-none bg-muted p-0"
                onClick={() => setOpen(f)}
                aria-label={`Xem ${f.product_name || f.name}`}
              >
                <video src={f.url} preload="metadata" muted className="pointer-events-none size-full object-cover" />
              </Button>
              <CardHeader>
                <CardTitle className="truncate">{f.product_name || f.name}</CardTitle>
                <CardDescription className="truncate">{f.prompt_name || f.name}</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                {c && (
                  <Badge variant="secondary">
                    <c.icon /> {c.label}
                  </Badge>
                )}
                {fmtTime(f.mtime)} · {fmtSize(f.size)}
              </CardContent>
              <CardFooter>
                <Button asChild size="sm" variant="outline">
                  <a href={f.url} download>
                    <DownloadIcon /> Tải về
                  </a>
                </Button>
              </CardFooter>
            </Card>
          )
        })}
      </div>

      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{open?.product_name || open?.name}</DialogTitle>
            <DialogDescription>{open?.prompt_name || open?.name}</DialogDescription>
          </DialogHeader>
          {open && <video src={open.url} controls autoPlay className="w-full rounded-lg bg-muted" />}
          {open && (
            <Button asChild variant="outline" className="justify-self-end">
              <a href={open.url} download>
                <DownloadIcon /> Tải về
              </a>
            </Button>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
