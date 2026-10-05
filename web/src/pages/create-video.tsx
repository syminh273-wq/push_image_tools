import { useEffect, useMemo, useState } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import { ChevronDownIcon, ListPlusIcon, PencilIcon, PlayIcon, ScrollTextIcon, ShieldCheckIcon } from "lucide-react"
import { useForm, useWatch } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { EmptyState } from "@/components/empty-state"
import { FileUpload } from "@/components/file-upload"
import { ModelImagePicker } from "@/components/model-picker"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useAppData } from "@/hooks/app-data"
import { navigate, useRoute } from "@/hooks/use-route"
import { api, type Pair, type Prompt } from "@/lib/api"
import { CATEGORIES, PRODUCT_VAR, categoryOf, renderPrompt, rulesFor } from "@/lib/format"

const schema = z.object({
  prompt_id: z.string().min(1, "Chọn một prompt"),
  product_name: z.string().trim().max(200, "Tối đa 200 ký tự"),
  model_image: z.string().optional(),
  product_image: z.string().optional(),
  video: z.string().optional(),
  video_start: z.coerce.number().min(0, "Không âm"),
  account: z.string(),
  prompt_override: z.string(),
})
type FormValues = z.input<typeof schema>

/** Required fields depend on the chosen prompt, so they are checked against it here. */
function makeResolver(prompts: Prompt[]) {
  const refined = schema.superRefine((v, ctx) => {
    const p = prompts.find((x) => x.id === v.prompt_id)
    if (!p) return
    const need = (ok: unknown, path: string, message: string) => {
      if (!ok) ctx.addIssue({ code: "custom", path: [path], message })
    }
    if (!v.prompt_override.trim()) need(!p.needs_product_name || v.product_name, "product_name", "Nhập tên sản phẩm")
    if (p.inputs.model_image) need(v.model_image, "model_image", "Cần ảnh người mẫu")
    if (p.inputs.product_image) need(v.product_image, "product_image", "Cần ảnh sản phẩm")
    if (p.inputs.ref_video) need(v.video, "video", "Cần video mẫu")
  })
  return zodResolver(refined)
}

const EMPTY: FormValues = {
  prompt_id: "",
  product_name: "",
  model_image: undefined,
  product_image: undefined,
  video: undefined,
  video_start: 0,
  account: "auto",
  prompt_override: "",
}

export function CreateVideoPage() {
  const { prompts, rules, processes, refreshPairs, runPair } = useAppData()
  const { params } = useRoute()
  const preset = params.get("prompt")

  const resolver = useMemo(() => makeResolver(prompts ?? []), [prompts])
  const form = useForm<FormValues>({ resolver, defaultValues: { ...EMPTY, prompt_id: preset ?? "" } })
  const values = useWatch({ control: form.control })
  const [submitting, setSubmitting] = useState<"queue" | "run" | null>(null)
  const [editOpen, setEditOpen] = useState(false)

  useEffect(() => {
    if (preset) form.setValue("prompt_id", preset)
  }, [preset, form])

  const prompt = prompts?.find((p) => p.id === values.prompt_id)
  const rendered = prompt ? renderPrompt(prompt, values.product_name ?? "", rules) : ""
  const hasRules = !!prompt && !!rulesFor(prompt, rules)
  const readyAccounts = (processes?.accounts ?? []).filter((a) => a.status === "ready")

  // Switching prompt: drop the edited copy of the previous one.
  useEffect(() => {
    form.setValue("prompt_override", "")
    setEditOpen(false)
    form.clearErrors()
  }, [values.prompt_id, form])

  async function submit(v: FormValues, mode: "queue" | "run") {
    setSubmitting(mode)
    try {
      const { pair } = await api<{ pair: Pair }>("/api/pairs", { method: "POST", json: v })
      if (mode === "run") {
        try {
          await runPair(pair.id)
          toast.success("Đã bắt đầu tạo video")
        } catch (e) {
          // The job exists already; it just could not start (e.g. no free account).
          toast.warning(`Đã thêm vào hàng đợi nhưng chưa chạy được: ${(e as Error).message}`)
          await refreshPairs()
        }
        navigate("queue", { pair: pair.id })
      } else {
        toast.success("Đã thêm vào hàng đợi", {
          action: { label: "Xem", onClick: () => navigate("queue", { pair: pair.id }) },
        })
        await refreshPairs()
        // Keep the prompt and model so the next product is quick to add.
        form.reset({ ...EMPTY, prompt_id: v.prompt_id, model_image: v.model_image, video: v.video, account: v.account })
      }
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSubmitting(null)
    }
  }

  if (!prompts) {
    return (
      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <Skeleton className="h-[480px] rounded-xl" />
        <Skeleton className="h-[320px] rounded-xl" />
      </div>
    )
  }
  if (!prompts.length) {
    return (
      <EmptyState
        icon={ScrollTextIcon}
        title="Chưa có prompt nào"
        description="Thêm một prompt cho loại quảng cáo bạn cần trước."
        action={<Button onClick={() => navigate("prompts")}>Mở Thư viện Prompt</Button>}
      />
    )
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit((v) => submit(v, "queue"))}
        className="grid items-start gap-6 lg:grid-cols-[1fr_400px]"
      >
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="font-heading tracking-tight">1. Chọn loại quảng cáo</CardTitle>
              <CardDescription>Mỗi prompt đã viết sẵn cho một loại sản phẩm.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <FormField
                control={form.control}
                name="prompt_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Prompt</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="Chọn prompt…" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent position="popper">
                        {CATEGORIES.map((c) => {
                          const items = prompts.filter((p) => p.category === c.value)
                          if (!items.length) return null
                          return (
                            <SelectGroup key={c.value}>
                              <SelectLabel>{c.label}</SelectLabel>
                              {items.map((p) => (
                                <SelectItem key={p.id} value={p.id}>
                                  <c.icon /> {p.name}
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          )
                        })}
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {prompt?.needs_product_name && (
                <FormField
                  control={form.control}
                  name="product_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tên sản phẩm</FormLabel>
                      <FormControl>
                        <Input placeholder="VD: Son kem lì Maybelline Superstay" {...field} />
                      </FormControl>
                      <FormDescription>Được chèn vào prompt ở chỗ {PRODUCT_VAR}.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
            </CardContent>
          </Card>

          {prompt && (
            <Card>
              <CardHeader>
                <CardTitle className="font-heading tracking-tight">2. Tải ảnh / video</CardTitle>
                <CardDescription>Tối đa 100 MB, video sẽ được cắt còn 10 giây.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                {prompt.inputs.model_image && (
                  <FormField
                    control={form.control}
                    name="model_image"
                    render={({ field, fieldState }) => (
                      <FormItem>
                        <FormLabel>Ảnh người mẫu</FormLabel>
                        <FormControl>
                          <ModelImagePicker
                            value={field.value}
                            onChange={field.onChange}
                            invalid={!!fieldState.error}
                          />
                        </FormControl>
                        <FormDescription>
                          Upload mới hoặc chọn lại từ thư viện Model đã lưu.
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}
                {prompt.inputs.product_image && (
                  <UploadField form={form} name="product_image" kind="image" label="Ảnh sản phẩm" />
                )}
                {prompt.inputs.ref_video && (
                  <>
                    <UploadField form={form} name="video" kind="video" label="Video mẫu (động tác)" />
                    <FormField
                      control={form.control}
                      name="video_start"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Bắt đầu từ giây</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              min={0}
                              step={0.5}
                              {...field}
                              value={String(field.value ?? 0)}
                            />
                          </FormControl>
                          <FormDescription>Gemini chỉ dùng 10 giây; video dài hơn sẽ được cắt từ mốc này.</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-6 lg:sticky lg:top-20">
          <Card>
            <CardHeader>
              <CardTitle className="font-heading tracking-tight">3. Xem trước</CardTitle>
              {prompt && (
                <CardDescription className="flex items-center gap-2">
                  <Badge variant="secondary">
                    {(() => {
                      const c = categoryOf(prompt.category)
                      return (
                        <>
                          <c.icon /> {c.label}
                        </>
                      )
                    })()}
                  </Badge>
                  {prompt.name}
                  {hasRules && (
                    <Badge variant="outline">
                      <ShieldCheckIcon /> Quy tắc chung
                    </Badge>
                  )}
                </CardDescription>
              )}
            </CardHeader>
            <CardContent className="space-y-4">
              {!prompt ? (
                <p className="text-sm text-muted-foreground">Chọn prompt để xem nội dung sẽ gửi cho Gemini.</p>
              ) : (
                <Collapsible open={editOpen} onOpenChange={setEditOpen}>
                  {!editOpen && (
                    <p className="max-h-72 overflow-y-auto rounded-lg border bg-muted/40 p-3 text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">
                      {rendered}
                    </p>
                  )}
                  <CollapsibleTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="mt-2"
                      onClick={() => form.setValue("prompt_override", editOpen ? "" : rendered)}
                    >
                      <PencilIcon />
                      {editOpen ? "Dùng lại prompt gốc" : "Sửa riêng cho lần này"}
                      <ChevronDownIcon className={editOpen ? "rotate-180" : undefined} />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <FormField
                      control={form.control}
                      name="prompt_override"
                      render={({ field }) => (
                        <FormItem className="mt-2">
                          <FormControl>
                            <Textarea rows={14} className="max-h-96 min-h-72 text-xs" {...field} />
                          </FormControl>
                          <FormDescription>Chỉ áp dụng cho video này; prompt trong thư viện không đổi.</FormDescription>
                        </FormItem>
                      )}
                    />
                  </CollapsibleContent>
                </Collapsible>
              )}

              <FormField
                control={form.control}
                name="account"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Tài khoản Gemini</FormLabel>
                    <Select value={field.value} onValueChange={field.onChange}>
                      <FormControl>
                        <SelectTrigger className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent position="popper">
                        <SelectItem value="auto">Tự chọn tài khoản rảnh</SelectItem>
                        {readyAccounts.map((a) => (
                          <SelectItem key={a.name} value={a.name}>
                            {a.name}
                            {a.email ? ` · ${a.email}` : ""}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {!readyAccounts.length && (
                      <FormDescription>
                        Chưa có tài khoản sẵn sàng —{" "}
                        <Button type="button" variant="link" className="h-auto p-0" onClick={() => navigate("accounts")}>
                          thêm tài khoản
                        </Button>
                        .
                      </FormDescription>
                    )}
                  </FormItem>
                )}
              />

              <div className="flex flex-col gap-2 sm:flex-row lg:flex-col xl:flex-row">
                <Button type="submit" className="flex-1" disabled={!prompt || !!submitting}>
                  <ListPlusIcon />
                  {submitting === "queue" ? "Đang thêm…" : "Thêm vào hàng đợi"}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  className="flex-1"
                  disabled={!prompt || !!submitting}
                  onClick={form.handleSubmit((v) => submit(v, "run"))}
                >
                  <PlayIcon />
                  {submitting === "run" ? "Đang chạy…" : "Chạy ngay"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </form>
    </Form>
  )
}

function UploadField({
  form,
  name,
  kind,
  label,
}: {
  form: ReturnType<typeof useForm<FormValues>>
  name: "model_image" | "product_image" | "video"
  kind: "image" | "video"
  label: string
}) {
  return (
    <FormField
      control={form.control}
      name={name}
      render={({ field, fieldState }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <div>
              <FileUpload kind={kind} value={field.value} onChange={field.onChange} invalid={!!fieldState.error} />
            </div>
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  )
}
