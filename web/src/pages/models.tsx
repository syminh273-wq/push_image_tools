import { useEffect, useId, useMemo, useState } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import {
  AlertTriangleIcon,
  ImageIcon,
  MoreHorizontalIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
  SparklesIcon,
  Trash2Icon,
  UploadIcon,
  UserCircleIcon,
  XIcon,
} from "lucide-react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
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
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useAppData } from "@/hooks/app-data"
import { api, type ModelImage, uploadFile } from "@/lib/api"
import { basename, uploadUrl } from "@/lib/format"
import { cn } from "@/lib/utils"

const ACCEPT = ".png,.jpg,.jpeg,.webp"

type FormValues = {
  name: string
  image: string
  tags: string[]
  note: string
}

const schema = z.object({
  name: z.string().trim().min(1, "Nhập tên").max(120, "Tối đa 120 ký tự"),
  image: z.string().min(1, "Cần ảnh"),
  tags: z.array(z.string().trim().min(1)).max(20),
  note: z.string().max(1000),
})

const EMPTY: FormValues = { name: "", image: "", tags: [], note: "" }

export function ModelsPage() {
  const { models, refreshModels } = useAppData()
  const [search, setSearch] = useState("")
  const [editing, setEditing] = useState<ModelImage | "new" | null>(null)
  const [deleting, setDeleting] = useState<ModelImage | null>(null)

  async function remove(m: ModelImage) {
    try {
      await api(`/api/models/${m.id}`, { method: "DELETE" })
      await refreshModels()
      toast.success(`Đã xoá "${m.name}"`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const list = useMemo(() => {
    if (!models) return null
    const q = search.trim().toLowerCase()
    if (!q) return models
    return models.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        m.tags.some((t) => t.toLowerCase().includes(q)),
    )
  }, [models, search])

  return (
    <div className="space-y-6">
      <PageHeader
        icon={UserCircleIcon}
        title="Thư viện Model"
        description="Ảnh người mẫu đã lưu — chọn nhanh khi tạo video, hoặc upload thêm để dùng cho prompt mới."
      >
        <Button onClick={() => setEditing("new")}>
          <PlusIcon /> Thêm model
        </Button>
      </PageHeader>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1 sm:max-w-xs">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Tìm theo tên hoặc tag…"
            className="pl-9"
          />
        </div>
      </div>

      {!list ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-72 rounded-xl" />
          ))}
        </div>
      ) : !list.length ? (
        <EmptyState
          icon={UserCircleIcon}
          title={search ? "Không tìm thấy model" : "Chưa có model nào"}
          description={
            search
              ? `Không có model nào khớp "${search}".`
              : "Lưu ảnh người mẫu để dùng lại cho nhiều video, không phải upload lại."
          }
          action={
            !search ? (
              <Button onClick={() => setEditing("new")}>
                <PlusIcon /> Thêm model đầu tiên
              </Button>
            ) : null
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {list.map((m) => (
            <ModelCard key={m.id} model={m} onEdit={() => setEditing(m)} onDelete={() => setDeleting(m)} />
          ))}
        </div>
      )}

      <ModelEditor
        model={editing}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          setEditing(null)
          await refreshModels()
        }}
      />

      <AlertDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xoá model "{deleting?.name}"?</AlertDialogTitle>
            <AlertDialogDescription>
              Chỉ xoá khỏi thư viện — file ảnh gốc trong <code className="rounded bg-muted px-1 py-0.5 text-xs">data/uploads/</code> được giữ nguyên.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Huỷ</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => deleting && remove(deleting)}>
              Xoá
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function ModelCard({
  model,
  onEdit,
  onDelete,
}: {
  model: ModelImage
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <Card className="card-interactive flex flex-col overflow-hidden">
      <div className="relative aspect-square bg-muted">
        {model.missing ? (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-muted-foreground">
            <AlertTriangleIcon className="size-8" />
            <span className="text-xs">File không còn</span>
          </div>
        ) : (
          <img
            src={uploadUrl(model.image)}
            alt={model.name}
            className="h-full w-full object-cover"
            loading="lazy"
          />
        )}
        {model.missing && (
          <Badge variant="destructive" className="absolute right-2 top-2">
            missing
          </Badge>
        )}
      </div>
      <CardHeader>
        <CardTitle className="line-clamp-1 text-sm leading-snug">{model.name}</CardTitle>
        {model.note && <CardDescription className="line-clamp-2 text-xs">{model.note}</CardDescription>}
        <CardAction>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={`Thao tác cho ${model.name}`}>
                <MoreHorizontalIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={onEdit}>
                <PencilIcon /> Sửa
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                <Trash2Icon /> Xoá
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </CardAction>
      </CardHeader>
      <CardContent className="flex-1 space-y-2">
        {model.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {model.tags.map((t) => (
              <Badge key={t} variant="secondary" className="text-[10px]">
                {t}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
      <CardFooter className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="truncate" title={basename(model.image)}>
          {basename(model.image)}
        </span>
        <Badge variant="outline" className="shrink-0">
          <SparklesIcon /> {model.use_count} lượt
        </Badge>
      </CardFooter>
    </Card>
  )
}

function ModelEditor({
  model,
  onClose,
  onSaved,
}: {
  model: ModelImage | "new" | null
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const isNew = model === "new"
  const form = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: EMPTY })
  const [tagInput, setTagInput] = useState("")
  const [uploading, setUploading] = useState(false)

  useEffect(() => {
    if (model) {
      form.reset(
        model === "new"
          ? EMPTY
          : { name: model.name, image: model.image, tags: [...model.tags], note: model.note },
      )
    }
  }, [model, form])

  async function pickFile(file: File | undefined) {
    if (!file) return
    setUploading(true)
    try {
      const path = await uploadFile(file, "image")
      form.setValue("image", path, { shouldDirty: true, shouldValidate: true })
    } catch (e) {
      toast.error(`Upload lỗi: ${(e as Error).message}`)
    } finally {
      setUploading(false)
    }
  }

  function addTag() {
    const t = tagInput.trim().slice(0, 40)
    if (!t) return
    const current = form.getValues("tags")
    if (current.length >= 20) {
      toast.warning("Tối đa 20 tag")
      return
    }
    if (current.includes(t)) {
      setTagInput("")
      return
    }
    form.setValue("tags", [...current, t], { shouldDirty: true })
    setTagInput("")
  }

  async function save(v: FormValues) {
    try {
      const payload = { name: v.name, image: v.image, tags: v.tags, note: v.note }
      if (isNew) await api("/api/models", { method: "POST", json: payload })
      else if (model) await api(`/api/models/${model.id}`, { method: "PUT", json: payload })
      toast.success(isNew ? "Đã thêm model" : "Đã lưu")
      await onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const image = form.watch("image")
  const tags = form.watch("tags") || []

  return (
    <Dialog open={!!model} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="data-[size=md]:w-full sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{isNew ? "Thêm model" : "Sửa model"}</DialogTitle>
          <DialogDescription>
            Ảnh người mẫu để dùng lại cho nhiều video. File gốc không bị xoá khi xoá khỏi thư viện.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(save)} className="space-y-5">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tên</FormLabel>
                  <FormControl>
                    <Input placeholder="VD: Người mẫu nữ 01" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="image"
              render={() => (
                <FormItem>
                  <FormLabel>Ảnh</FormLabel>
                  <FormControl>
                    <ImagePicker
                      value={image}
                      uploading={uploading}
                      onPick={pickFile}
                      onClear={() => form.setValue("image", "", { shouldDirty: true, shouldValidate: true })}
                    />
                  </FormControl>
                  <FormDescription>PNG, JPG, WEBP. Tối đa 500 MB.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="tags"
              render={() => (
                <FormItem>
                  <FormLabel>Tag</FormLabel>
                  <div className="flex gap-2">
                      <Input
                        value={tagInput}
                        onChange={(e) => setTagInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === ",") {
                            e.preventDefault()
                            addTag()
                          }
                        }}
                        placeholder="Nhập tag rồi Enter…"
                      />
                      <Button type="button" variant="secondary" onClick={addTag}>
                        Thêm
                      </Button>
                    </div>
                    {tags.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {tags.map((t) => (
                          <Badge key={t} variant="secondary" className="gap-1 pr-1">
                            {t}
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              onClick={() =>
                                form.setValue(
                                  "tags",
                                  tags.filter((x) => x !== t),
                                  { shouldDirty: true },
                                )
                              }
                              className="ml-1 size-4 rounded-sm hover:bg-muted-foreground/20"
                              aria-label={`Bỏ tag ${t}`}
                            >
                              <XIcon className="size-3" />
                            </Button>
                          </Badge>
                        ))}
                      </div>
                    )}
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="note"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Ghi chú</FormLabel>
                  <FormControl>
                    <Textarea rows={3} placeholder="Tùy chọn…" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <DialogFooter className="gap-2">
              <DialogClose asChild>
                <Button type="button" variant="ghost">
                  Huỷ
                </Button>
              </DialogClose>
              <Button type="submit" disabled={form.formState.isSubmitting}>
                {isNew ? "Thêm" : "Lưu"}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}

function ImagePicker({
  value,
  uploading,
  onPick,
  onClear,
}: {
  value: string
  uploading: boolean
  onPick: (f: File | undefined) => void
  onClear: () => void
}) {
  const id = useId()
  if (value) {
    return (
      <div className="relative overflow-hidden rounded-lg border bg-muted/40">
        <img src={uploadUrl(value)} alt="" className="h-48 w-full object-contain" />
        <div className="flex items-center gap-2 border-t bg-background px-3 py-1.5">
          <ImageIcon className="size-3.5 text-muted-foreground" />
          <span className="truncate text-xs text-muted-foreground">{basename(value)}</span>
          <Button type="button" variant="ghost" size="icon-xs" className="ml-auto" aria-label="Bỏ ảnh" onClick={onClear}>
            <XIcon />
          </Button>
        </div>
      </div>
    )
  }
  return (
    <Label
      htmlFor={id}
      className={cn(
        "flex h-48 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-center transition-colors hover:bg-muted/50 focus-within:ring-3 focus-within:ring-ring/50",
        uploading && "pointer-events-none opacity-60",
      )}
    >
      <UploadIcon className="size-6 text-muted-foreground" />
      <span className="text-sm font-medium">Kéo thả hoặc bấm để chọn</span>
      <span className="text-xs text-muted-foreground">PNG, JPG, WEBP</span>
      <Input
        id={id}
        type="file"
        accept={ACCEPT}
        className="sr-only"
        onChange={(e) => {
          onPick(e.target.files?.[0])
          e.target.value = ""
        }}
      />
    </Label>
  )
}