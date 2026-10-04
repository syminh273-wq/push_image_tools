import { useEffect } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import { RotateCcwIcon, SaveIcon, ShieldCheckIcon, ShoppingBagIcon, SparklesIcon, UserIcon } from "lucide-react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useAppData } from "@/hooks/app-data"
import { api, type RuleKey } from "@/lib/api"

const ruleText = z.string().max(4000, "Tối đa 4000 ký tự")
const schema = z.object({ enabled: z.boolean(), general: ruleText, product: ruleText, person: ruleText })
type Values = z.infer<typeof schema>

const SECTIONS: { key: RuleKey; label: string; description: string; icon: typeof UserIcon }[] = [
  {
    key: "general",
    label: "Chung — mọi prompt",
    description: "Một cảnh liền, chuyển động chậm, không vật nào tự xuất hiện / biến mất.",
    icon: SparklesIcon,
  },
  {
    key: "product",
    label: "Sản phẩm — prompt có ảnh sản phẩm",
    description: "Sản phẩm luôn trong khung, không bị che, giữ nguyên hình dạng/logo khi xoay.",
    icon: ShoppingBagIcon,
  },
  {
    key: "person",
    label: "Người mẫu — prompt có ảnh người mẫu",
    description: "Giữ nguyên khuôn mặt, quần áo; đúng số tay chân.",
    icon: UserIcon,
  },
]

/** System rules appended to every prompt that has "Áp dụng Quy tắc chung" on. */
export function RulesCard() {
  const { rules, refreshRules } = useAppData()
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { enabled: true, general: "", product: "", person: "" },
  })

  useEffect(() => {
    if (rules) form.reset({ enabled: rules.enabled, general: rules.general, product: rules.product, person: rules.person })
  }, [rules, form])

  async function save(v: Values) {
    try {
      await api("/api/system-rules", { method: "PUT", json: v })
      await refreshRules()
      toast.success("Đã lưu quy tắc — áp dụng cho các video tạo từ giờ")
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  if (!rules) return <Skeleton className="h-96 rounded-xl" />

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(save)}>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheckIcon className="size-5" /> Quy tắc chung (system rules)
            </CardTitle>
            <CardDescription>
              Gắn vào cuối mọi prompt để giảm lỗi hay gặp của AI video: sản phẩm biến mất hoặc méo khi xoay, bị cắt
              cảnh, thừa/thiếu tay chân. Chỉ phần phù hợp được gắn (VD prompt không có người thì bỏ phần Người mẫu).
              Video đã ở hàng đợi giữ prompt cũ.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <FormField
              control={form.control}
              name="enabled"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between gap-4 rounded-lg border p-4">
                  <div className="space-y-1">
                    <FormLabel>Bật quy tắc chung</FormLabel>
                    <FormDescription>Tắt để gửi prompt gốc, không kèm quy tắc.</FormDescription>
                  </div>
                  <FormControl>
                    <Switch checked={field.value} onCheckedChange={field.onChange} />
                  </FormControl>
                </FormItem>
              )}
            />
            {SECTIONS.map((s) => (
              <FormField
                key={s.key}
                control={form.control}
                name={s.key}
                render={({ field }) => (
                  <FormItem>
                    <div className="flex items-center justify-between gap-2">
                      <FormLabel>
                        <s.icon className="size-4 text-muted-foreground" /> {s.label}
                      </FormLabel>
                      <Button
                        type="button"
                        variant="ghost"
                        size="xs"
                        onClick={() => form.setValue(s.key, rules.defaults[s.key], { shouldDirty: true })}
                      >
                        <RotateCcwIcon /> Mặc định
                      </Button>
                    </div>
                    <FormControl>
                      <Textarea
                        rows={8}
                        className="min-h-40 font-mono text-xs"
                        disabled={!form.watch("enabled")}
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>
                      {s.description} Viết tiếng Anh cho Gemini hiểu tốt nhất; có thể dùng {"{{product_name}}"}.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}
          </CardContent>
          <CardFooter className="justify-end">
            <Button type="submit" disabled={form.formState.isSubmitting || !form.formState.isDirty}>
              <SaveIcon /> Lưu quy tắc
            </Button>
          </CardFooter>
        </Card>
      </form>
    </Form>
  )
}
