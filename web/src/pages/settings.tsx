import { useEffect } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import { SaveIcon } from "lucide-react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { RulesCard } from "@/components/rules-card"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { useAppData, type RunSettings } from "@/hooks/app-data"

const schema = z.object({
  showBrowser: z.boolean(),
  maxParallel: z.coerce.number().int("Số nguyên").min(0, "Không âm").max(20, "Tối đa 20"),
  launchDelay: z.coerce.number().min(0, "Không âm").max(300, "Tối đa 300 giây"),
})

export function SettingsPage() {
  const { settings, setSettings } = useAppData()
  const form = useForm<z.input<typeof schema>, unknown, RunSettings>({
    resolver: zodResolver(schema),
    defaultValues: settings,
  })

  useEffect(() => form.reset(settings), [settings, form])

  return (
    <div className="grid max-w-3xl gap-6">
      <RulesCard />
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((v) => {
            setSettings(v)
            toast.success("Đã lưu cài đặt")
          })}
        >
          <Card>
            <CardHeader>
              <CardTitle>Cách chạy video</CardTitle>
              <CardDescription>Áp dụng cho "Chạy ngay" và "Run All". Lưu trên trình duyệt này.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <FormField
                control={form.control}
                name="showBrowser"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center justify-between gap-4 rounded-lg border p-4">
                    <div className="space-y-1">
                      <FormLabel>Hiện cửa sổ Chrome</FormLabel>
                      <FormDescription>
                        Google ít bắt xác minh hơn khi cửa sổ hiện; bạn cũng tự xử lý được trang xác minh.
                      </FormDescription>
                    </div>
                    <FormControl>
                      <Switch checked={field.value} onCheckedChange={field.onChange} />
                    </FormControl>
                  </FormItem>
                )}
              />
              <div className="grid gap-4 sm:grid-cols-2">
                <FormField
                  control={form.control}
                  name="maxParallel"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Số video chạy song song</FormLabel>
                      <FormControl>
                        <Input type="number" min={0} max={20} {...field} value={String(field.value ?? "")} />
                      </FormControl>
                      <FormDescription>0 = mỗi tài khoản rảnh chạy 1 video.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="launchDelay"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Giãn cách mở Chrome (giây)</FormLabel>
                      <FormControl>
                        <Input type="number" min={0} max={300} {...field} value={String(field.value ?? "")} />
                      </FormControl>
                      <FormDescription>Mở chậm giúp tránh bị Google chặn.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
            </CardContent>
            <CardFooter className="justify-end">
              <Button type="submit">
                <SaveIcon /> Lưu
              </Button>
            </CardFooter>
          </Card>
      </form>
    </Form>
    </div>
  )
}
