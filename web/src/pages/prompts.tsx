import { useEffect, useRef, useState } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import {
  BracesIcon,
  CopyIcon,
  ImageIcon,
  MoreHorizontalIcon,
  PencilIcon,
  PlusIcon,
  ScrollTextIcon,
  ShieldCheckIcon,
  ShoppingBagIcon,
  SparklesIcon,
  Trash2Icon,
  UserIcon,
  VideoIcon,
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { useAppData } from "@/hooks/app-data"
import { navigate } from "@/hooks/use-route"
import { api, type Category, type Prompt, type PromptPayload } from "@/lib/api"
import { CATEGORIES, PRODUCT_VAR, categoryOf } from "@/lib/format"

const INPUT_META = [
  { key: "model_image", label: "Ảnh người mẫu", icon: UserIcon },
  { key: "product_image", label: "Ảnh sản phẩm", icon: ShoppingBagIcon },
  { key: "ref_video", label: "Video mẫu", icon: VideoIcon },
] as const

export function PromptsPage() {
  const { prompts, refreshPrompts } = useAppData()
  const [filter, setFilter] = useState<"all" | Category>("all")
  const [editing, setEditing] = useState<Prompt | "new" | null>(null)
  const [deleting, setDeleting] = useState<Prompt | null>(null)

  async function duplicate(p: Prompt) {
    try {
      await api(`/api/prompts/${p.id}/duplicate`, { method: "POST" })
      await refreshPrompts()
      toast.success("Đã nhân bản")
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  async function remove(p: Prompt) {
    try {
      await api(`/api/prompts/${p.id}`, { method: "DELETE" })
      await refreshPrompts()
      toast.success(`Đã xoá "${p.name}"`)
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const used = CATEGORIES.filter((c) => prompts?.some((p) => p.category === c.value))
  const list = (prompts ?? []).filter((p) => filter === "all" || p.category === filter)

  return (
    <div className="space-y-6">
      <PageHeader
        icon={ScrollTextIcon}
        title="Thư viện Prompt"
        description="Mẫu prompt cho từng loại sản phẩm — Gemini dùng chúng để viết lời quảng cáo nhất quán."
      >
        <Button className="sm:ml-auto" onClick={() => setEditing("new")}>
          <PlusIcon /> Thêm prompt
        </Button>
      </PageHeader>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Tabs value={filter} onValueChange={(v) => setFilter(v as typeof filter)} className="min-w-0 overflow-x-auto">
          <TabsList>
            <TabsTrigger value="all">Tất cả</TabsTrigger>
            {used.map((c) => (
              <TabsTrigger key={c.value} value={c.value}>
                <c.icon /> {c.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {!prompts ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-56 rounded-xl" />
          ))}
        </div>
      ) : !list.length ? (
        <EmptyState
          icon={ScrollTextIcon}
          title="Chưa có prompt"
          description="Mỗi prompt là một kịch bản quảng cáo cho một loại sản phẩm."
          action={
            <Button onClick={() => setEditing("new")}>
              <PlusIcon /> Thêm prompt
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((p) => {
            const c = categoryOf(p.category)
            return (
              <Card key={p.id} className="card-interactive flex flex-col">
                <CardHeader>
                  <CardTitle className="font-heading leading-snug tracking-tight">{p.name}</CardTitle>
                  <CardDescription>
                    <Badge variant="secondary">
                      <c.icon /> {c.label}
                    </Badge>
                  </CardDescription>
                  <CardAction>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label={`Thao tác cho ${p.name}`}>
                          <MoreHorizontalIcon />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => setEditing(p)}>
                          <PencilIcon /> Sửa
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => duplicate(p)}>
                          <CopyIcon /> Nhân bản
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive" onSelect={() => setDeleting(p)}>
                          <Trash2Icon /> Xoá
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </CardAction>
                </CardHeader>
                <CardContent className="flex-1 space-y-3">
                  <div className="flex flex-wrap gap-1.5">
                    {INPUT_META.filter((m) => p.inputs[m.key]).map((m) => (
                      <Badge key={m.key} variant="outline">
                        <m.icon /> {m.label}
                      </Badge>
                    ))}
                    {p.use_rules && (
                      <Badge variant="outline">
                        <ShieldCheckIcon /> Quy tắc chung
                      </Badge>
                    )}
                    {p.needs_product_name && (
                      <Badge variant="outline">
                        <BracesIcon /> Tên sản phẩm
                      </Badge>
                    )}
                  </div>
                  <p className="line-clamp-4 text-xs leading-relaxed text-muted-foreground">{p.content}</p>
                </CardContent>
                <CardFooter className="gap-2">
                  <Button size="sm" onClick={() => navigate("create", { prompt: p.id })}>
                    <SparklesIcon /> Dùng prompt này
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>
                    <PencilIcon /> Sửa
                  </Button>
                </CardFooter>
              </Card>
            )
          })}
        </div>
      )}

      <PromptEditor
        prompt={editing}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          setEditing(null)
          await refreshPrompts()
        }}
      />

      <AlertDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Xoá prompt "{deleting?.name}"?</AlertDialogTitle>
            <AlertDialogDescription>
              Các video đang chờ đã lưu sẵn nội dung prompt nên vẫn chạy bình thường.
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

const promptSchema = z
  .object({
    name: z.string().trim().min(1, "Nhập tên prompt").max(120, "Tối đa 120 ký tự"),
    category: z.enum(["clothes", "cosmetics", "bag", "shoes", "dance", "food", "other"]),
    content: z.string().trim().min(20, "Prompt quá ngắn").max(8000, "Tối đa 8000 ký tự"),
    inputs: z.object({ model_image: z.boolean(), product_image: z.boolean(), ref_video: z.boolean() }),
    use_rules: z.boolean(),
  })
  .refine((v) => v.inputs.model_image || v.inputs.product_image, {
    path: ["inputs", "product_image"],
    message: "Cần ít nhất một ảnh (người mẫu hoặc sản phẩm)",
  })

const NEW_PROMPT: PromptPayload = {
  name: "",
  category: "clothes",
  content: `Create an advertisement video for "${PRODUCT_VAR}".\n`,
  inputs: { model_image: false, product_image: true, ref_video: false },
  use_rules: true,
}

function PromptEditor({
  prompt,
  onClose,
  onSaved,
}: {
  prompt: Prompt | "new" | null
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const form = useForm<PromptPayload>({ resolver: zodResolver(promptSchema), defaultValues: NEW_PROMPT })
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const isNew = prompt === "new"

  useEffect(() => {
    if (prompt) {
      form.reset(
        prompt === "new"
          ? NEW_PROMPT
          : {
              name: prompt.name,
              category: prompt.category,
              content: prompt.content,
              inputs: { ...prompt.inputs },
              use_rules: prompt.use_rules,
            },
      )
    }
  }, [prompt, form])

  function insertVar() {
    const el = textareaRef.current
    const cur = form.getValues("content")
    const at = el ? el.selectionStart : cur.length
    const end = el ? el.selectionEnd : cur.length
    form.setValue("content", cur.slice(0, at) + PRODUCT_VAR + cur.slice(end), { shouldDirty: true })
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(at + PRODUCT_VAR.length, at + PRODUCT_VAR.length)
    })
  }

  async function save(v: PromptPayload) {
    try {
      if (isNew) await api("/api/prompts", { method: "POST", json: v })
      else if (prompt) await api(`/api/prompts/${prompt.id}`, { method: "PUT", json: v })
      toast.success(isNew ? "Đã thêm prompt" : "Đã lưu")
      await onSaved()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <Sheet open={!!prompt} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-2xl">
        <SheetHeader className="border-b">
          <SheetTitle>{isNew ? "Thêm prompt" : "Sửa prompt"}</SheetTitle>
          <SheetDescription>
            Viết kịch bản cho một loại quảng cáo. Dùng {PRODUCT_VAR} ở chỗ cần tên sản phẩm — người dùng chỉ phải nhập
            tên đó khi tạo video.
          </SheetDescription>
        </SheetHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(save)} className="flex min-h-0 flex-1 flex-col">
            <div className="flex-1 space-y-5 overflow-y-auto p-4">
              <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tên prompt</FormLabel>
                      <FormControl>
                        <Input placeholder="VD: Mỹ phẩm – cận cảnh sản phẩm" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="category"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Loại</FormLabel>
                      <Select value={field.value} onValueChange={field.onChange}>
                        <FormControl>
                          <SelectTrigger className="w-full">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent position="popper">
                          {CATEGORIES.map((c) => (
                            <SelectItem key={c.value} value={c.value}>
                              <c.icon /> {c.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <div className="space-y-2">
                <p className="text-sm font-medium">File cần upload</p>
                <div className="grid gap-2 sm:grid-cols-3">
                  {INPUT_META.map((m) => (
                    <FormField
                      key={m.key}
                      control={form.control}
                      name={`inputs.${m.key}`}
                      render={({ field }) => (
                        <FormItem className="flex flex-row items-center justify-between gap-2 rounded-lg border p-3">
                          <FormLabel className="font-normal">
                            <m.icon className="size-4 text-muted-foreground" /> {m.label}
                          </FormLabel>
                          <FormControl>
                            <Switch checked={field.value} onCheckedChange={field.onChange} />
                          </FormControl>
                        </FormItem>
                      )}
                    />
                  ))}
                </div>
                <FormField
                  control={form.control}
                  name="inputs.product_image"
                  render={() => (
                    <FormItem>
                      <FormDescription>
                        <ImageIcon className="mr-1 inline size-3.5" />
                        Thứ tự dán vào Gemini: người mẫu → sản phẩm → video. Trong prompt gọi là "FIRST image" /
                        "SECOND image" khi có 2 ảnh.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="use_rules"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center justify-between gap-4 rounded-lg border p-3">
                    <div className="space-y-1">
                      <FormLabel>
                        <ShieldCheckIcon className="size-4 text-muted-foreground" /> Áp dụng Quy tắc chung
                      </FormLabel>
                      <FormDescription>
                        Gắn thêm luật chống lỗi (sản phẩm biến mất, méo khi xoay, thừa tay chân…) vào cuối prompt.{" "}
                        <Button type="button" variant="link" className="h-auto p-0 text-xs" onClick={() => navigate("settings")}>
                          Sửa quy tắc
                        </Button>
                      </FormDescription>
                    </div>
                    <FormControl>
                      <Switch checked={field.value} onCheckedChange={field.onChange} />
                    </FormControl>
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="content"
                render={({ field }) => (
                  <FormItem>
                    <div className="flex items-center justify-between">
                      <FormLabel>Nội dung prompt</FormLabel>
                      <Button type="button" variant="outline" size="xs" onClick={insertVar}>
                        <BracesIcon /> Chèn {PRODUCT_VAR}
                      </Button>
                    </div>
                    <FormControl>
                      <Textarea
                        rows={18}
                        className="min-h-96 font-mono text-xs"
                        {...field}
                        ref={(el) => {
                          field.ref(el)
                          textareaRef.current = el
                        }}
                      />
                    </FormControl>
                    <FormDescription>
                      {field.value.includes(PRODUCT_VAR)
                        ? "Có ô Tên sản phẩm khi tạo video."
                        : `Không có ${PRODUCT_VAR}: khi tạo video sẽ không hỏi tên sản phẩm.`}{" "}
                      {field.value.length}/8000 ký tự.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
            <SheetFooter className="flex-row justify-end border-t">
              <SheetClose asChild>
                <Button type="button" variant="ghost">
                  Huỷ
                </Button>
              </SheetClose>
              <Button type="submit" disabled={form.formState.isSubmitting}>
                {isNew ? "Thêm prompt" : "Lưu"}
              </Button>
            </SheetFooter>
          </form>
        </Form>
      </SheetContent>
    </Sheet>
  )
}
