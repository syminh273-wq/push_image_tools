import { useEffect, useMemo, useState } from "react"
import { ImageIcon, PlusIcon, SearchIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
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
import { Skeleton } from "@/components/ui/skeleton"
import { useAppData } from "@/hooks/app-data"
import { navigate } from "@/hooks/use-route"
import type { ModelImage } from "@/lib/api"
import { basename, uploadUrl } from "@/lib/format"
import { cn } from "@/lib/utils"

import { FileUpload } from "./file-upload"

/** Two ways to set the model image: pick from the library, or upload a new file. */
export function ModelImagePicker({
  value,
  onChange,
  invalid,
}: {
  value: string | undefined
  onChange: (path: string | undefined) => void
  invalid?: boolean
}) {
  const { models, refreshModels } = useAppData()
  const [open, setOpen] = useState(false)
  const [showUpload, setShowUpload] = useState(!value)

  // Drop the "upload new" preview when a saved model was just picked.
  useEffect(() => {
    if (value) setShowUpload(false)
  }, [value])

  function clear() {
    onChange(undefined)
    setShowUpload(true)
  }

  return (
    <div className="space-y-2">
      {value ? (
        <PreviewCard path={value} onClear={clear} onSwitch={() => setOpen(true)} />
      ) : showUpload ? (
        <FileUpload kind="image" value={undefined} onChange={(p) => p && onChange(p)} invalid={invalid} />
      ) : null}

      {!value && !showUpload && (
        <Button type="button" variant="ghost" size="sm" onClick={() => setShowUpload(true)}>
          <PlusIcon /> Upload ảnh mới
        </Button>
      )}

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant={value ? "outline" : "secondary"}
          size="sm"
          className="w-full"
          onClick={() => setOpen(true)}
        >
          <SearchIcon /> {value ? "Đổi model khác" : "Chọn từ thư viện"}
        </Button>
      </div>

      <ModelPickerDialog
        open={open}
        onOpenChange={setOpen}
        models={models}
        onRefresh={refreshModels}
        onPick={(m) => {
          onChange(m.image)
          setOpen(false)
        }}
      />
    </div>
  )
}

function PreviewCard({ path, onClear, onSwitch }: { path: string; onClear: () => void; onSwitch: () => void }) {
  return (
    <div className="relative overflow-hidden rounded-lg border bg-muted/40">
      <img src={uploadUrl(path)} alt="" className="h-44 w-full object-contain" />
      <div className="flex items-center gap-2 border-t bg-background px-3 py-1.5">
        <ImageIcon className="size-3.5 text-muted-foreground" />
        <span className="truncate text-xs text-muted-foreground">{basename(path)}</span>
        <Button type="button" variant="ghost" size="xs" className="ml-auto" onClick={onSwitch}>
          Đổi
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label="Bỏ model"
          onClick={onClear}
        >
          <XIcon />
        </Button>
      </div>
    </div>
  )
}

function ModelPickerDialog({
  open,
  onOpenChange,
  models,
  onRefresh,
  onPick,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  models: ModelImage[] | null
  onRefresh: () => Promise<void>
  onPick: (m: ModelImage) => void
}) {
  const [search, setSearch] = useState("")

  useEffect(() => {
    if (open) onRefresh().catch(() => {})
  }, [open, onRefresh])

  const list = useMemo(() => {
    if (!models) return null
    const q = search.trim().toLowerCase()
    if (!q) return models
    return models.filter(
      (m) =>
        m.name.toLowerCase().includes(q) || m.tags.some((t) => t.toLowerCase().includes(q)),
    )
  }, [models, search])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="data-[size=md]:w-full sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Chọn model từ thư viện</DialogTitle>
          <DialogDescription>
            Ảnh người mẫu đã lưu. Không có file phù hợp?{" "}
            <button
              type="button"
              className="font-medium text-foreground underline-offset-2 hover:underline"
              onClick={() => {
                onOpenChange(false)
                navigate("models")
              }}
            >
              Mở Thư viện Model
            </button>{" "}
            để upload ảnh mới.
          </DialogDescription>
        </DialogHeader>

        <div className="relative">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm theo tên hoặc tag…"
            className="pl-9"
          />
        </div>

        <div className="max-h-[60vh] overflow-y-auto">
          {!list ? (
            <div className="grid gap-3 sm:grid-cols-3">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-40 rounded-lg" />
              ))}
            </div>
          ) : !list.length ? (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <p className="text-sm text-muted-foreground">
                {search ? `Không có model nào khớp "${search}".` : "Thư viện Model trống."}
              </p>
              <Button
                type="button"
                variant="link"
                className="mt-2"
                onClick={() => {
                  onOpenChange(false)
                  navigate("models")
                }}
              >
                Mở Thư viện Model để thêm
              </Button>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-3">
              {list.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className={cn(
                    "group flex flex-col overflow-hidden rounded-lg border bg-card text-left transition-colors hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                    m.missing && "opacity-60",
                  )}
                  disabled={m.missing}
                  onClick={() => onPick(m)}
                >
                  <div className="aspect-square bg-muted">
                    {m.missing ? (
                      <div className="flex h-full w-full items-center justify-center text-xs text-muted-foreground">
                        missing
                      </div>
                    ) : (
                      <img
                        src={uploadUrl(m.image)}
                        alt={m.name}
                        className="h-full w-full object-cover transition-transform group-hover:scale-105"
                        loading="lazy"
                      />
                    )}
                  </div>
                  <div className="space-y-0.5 p-2">
                    <p className="line-clamp-1 text-sm font-medium">{m.name}</p>
                    <p className="line-clamp-1 text-[10px] text-muted-foreground">{basename(m.image)}</p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="ghost">
              Huỷ
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}