import { useId, useState } from "react"
import { ImageIcon, LoaderCircleIcon, UploadIcon, VideoIcon, XIcon } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { uploadFile } from "@/lib/api"
import { basename, uploadUrl } from "@/lib/format"
import { cn } from "@/lib/utils"

const ACCEPT = { image: ".png,.jpg,.jpeg,.webp", video: ".mp4,.mov,.webm" }

/** Drop zone that uploads right away and reports the server path through onChange. */
export function FileUpload({
  kind,
  value,
  onChange,
  invalid,
}: {
  kind: "image" | "video"
  value: string | undefined
  onChange: (path: string | undefined) => void
  invalid?: boolean
}) {
  const id = useId()
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const Icon = kind === "image" ? ImageIcon : VideoIcon

  async function handle(file: File | undefined) {
    if (!file) return
    setBusy(true)
    try {
      onChange(await uploadFile(file, kind))
    } catch (e) {
      toast.error(`Upload lỗi: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }

  if (value) {
    return (
      <div className="relative overflow-hidden rounded-lg border bg-muted/40">
        {kind === "image" ? (
          <img src={uploadUrl(value)} alt="" className="h-44 w-full object-contain" />
        ) : (
          <video src={uploadUrl(value)} className="h-44 w-full object-contain" controls muted />
        )}
        <div className="flex items-center gap-2 border-t bg-background px-3 py-1.5">
          <Icon className="size-3.5 text-muted-foreground" />
          <span className="truncate text-xs text-muted-foreground">{basename(value)}</span>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            className="ml-auto"
            aria-label="Bỏ file"
            onClick={() => onChange(undefined)}
          >
            <XIcon />
          </Button>
        </div>
      </div>
    )
  }

  return (
    <Label
      htmlFor={id}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        handle(e.dataTransfer.files[0])
      }}
      className={cn(
        "flex h-44 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-center transition-colors hover:bg-muted/50 focus-within:ring-3 focus-within:ring-ring/50",
        dragging && "border-primary bg-muted/50",
        invalid && "border-destructive",
      )}
    >
      {busy ? (
        <LoaderCircleIcon className="size-6 animate-spin text-muted-foreground" />
      ) : (
        <UploadIcon className="size-6 text-muted-foreground" />
      )}
      <span className="text-sm font-medium">{busy ? "Đang tải lên…" : "Kéo thả hoặc bấm để chọn"}</span>
      <span className="text-xs text-muted-foreground">
        {kind === "image" ? "PNG, JPG, WEBP" : "MP4, MOV, WEBM · tối đa 100 MB, cắt còn 10 giây"}
      </span>
      <Input
        id={id}
        type="file"
        accept={ACCEPT[kind]}
        className="sr-only"
        disabled={busy}
        onChange={(e) => {
          handle(e.target.files?.[0])
          e.target.value = ""
        }}
      />
    </Label>
  )
}
