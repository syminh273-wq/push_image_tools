import { useMemo, useState } from "react"
import { zodResolver } from "@hookform/resolvers/zod"
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table"
import {
  EyeIcon,
  EyeOffIcon,
  KeyRoundIcon,
  LogInIcon,
  MoreHorizontalIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchCheckIcon,
  SmartphoneIcon,
  Trash2Icon,
  UsersIcon,
  XIcon,
} from "lucide-react"
import { useForm } from "react-hook-form"
import { toast } from "sonner"
import { z } from "zod"

import { EmptyState } from "@/components/empty-state"
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
import { Card } from "@/components/ui/card"
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
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useAppData } from "@/hooks/app-data"
import { api, type Account } from "@/lib/api"
import { ACCOUNT_STATUS_LABEL, fmtTime } from "@/lib/format"

type Confirm = { kind: "delete" | "forget"; account: Account }

export function AccountsPage() {
  const { processes, refreshProcesses } = useAppData()
  const [adding, setAdding] = useState(false)
  const [confirm, setConfirm] = useState<Confirm | null>(null)

  async function act(path: string, method: string, ok: string) {
    try {
      await api(path, { method })
      toast.success(ok)
      await refreshProcesses()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  const columns = useMemo<ColumnDef<Account>[]>(
    () => [
      {
        header: "Tài khoản",
        cell: ({ row: { original: a } }) => (
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 font-medium">
              {a.name}
              {a.has_password && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <KeyRoundIcon className="size-3.5 text-muted-foreground" aria-label="Đã lưu mật khẩu" />
                  </TooltipTrigger>
                  <TooltipContent>Mật khẩu lưu trong Keychain — tự đăng nhập lại</TooltipContent>
                </Tooltip>
              )}
            </p>
            <p className="truncate text-xs text-muted-foreground">{a.email || "—"}</p>
          </div>
        ),
      },
      {
        header: "Trạng thái",
        cell: ({ row: { original: a } }) => (
          <Badge variant={a.status === "ready" ? "default" : a.status === "unknown" ? "outline" : "destructive"}>
            {ACCOUNT_STATUS_LABEL[a.status] ?? a.status}
          </Badge>
        ),
      },
      {
        header: "Hiện tại",
        cell: ({ row: { original: a } }) =>
          a.login?.state === "waiting" ? (
            <Badge variant="secondary">Đang đăng nhập…</Badge>
          ) : a.busy ? (
            <Badge variant="secondary">Đang chạy video</Badge>
          ) : a.blocked ? (
            <Badge variant="destructive">
              {a.blocked.reason === "quota" ? "Hết quota" : a.blocked.reason}
              {a.blocked.until ? ` đến ${a.blocked.until.slice(11)}` : ""}
            </Badge>
          ) : (
            <span className="text-sm text-muted-foreground">Rảnh</span>
          ),
      },
      {
        header: "Kiểm tra lúc",
        cell: ({ row: { original: a } }) => (
          <span className="text-sm whitespace-nowrap text-muted-foreground">{fmtTime(a.checked_at)}</span>
        ),
      },
      {
        header: "Ghi chú",
        cell: ({ row: { original: a } }) => {
          const note =
            a.login?.state === "waiting"
              ? a.login.message || "Hoàn tất đăng nhập trong cửa sổ Chrome"
              : a.message || (a.login && a.login.state !== "done" ? `${a.login.state}: ${a.login.message ?? ""}` : "")
          if (a.login?.state === "waiting") {
            // Sign-in in progress: the user may have to act (tap Yes, pick a number) — show it all.
            return (
              <p className="flex max-w-80 items-start gap-1.5 text-sm font-medium whitespace-normal" role="status">
                <SmartphoneIcon className="mt-0.5 size-4 shrink-0" />
                {note}
              </p>
            )
          }
          return (
            <p className="max-w-64 truncate text-xs text-muted-foreground" title={note}>
              {note}
            </p>
          )
        },
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Thao tác</span>,
        cell: ({ row: { original: a } }) => {
          const enc = encodeURIComponent(a.name)
          if (a.busy) return null
          if (a.login?.state === "waiting") {
            return (
              <Button size="sm" variant="outline" onClick={() => act(`/api/accounts/${enc}/login/cancel`, "POST", "Đã huỷ")}>
                <XIcon /> Huỷ đăng nhập
              </Button>
            )
          }
          return (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label={`Thao tác cho ${a.name}`}>
                  <MoreHorizontalIcon />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => act(`/api/accounts/${enc}/login`, "POST", "Đã mở cửa sổ đăng nhập")}>
                  <LogInIcon /> Đăng nhập
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => act(`/api/accounts/${enc}/scan`, "POST", "Đang kiểm tra")}>
                  <SearchCheckIcon /> Kiểm tra
                </DropdownMenuItem>
                {a.has_password && (
                  <DropdownMenuItem onSelect={() => setConfirm({ kind: "forget", account: a })}>
                    <KeyRoundIcon /> Quên mật khẩu
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive" onSelect={() => setConfirm({ kind: "delete", account: a })}>
                  <Trash2Icon /> Xoá
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )
        },
      },
    ],
    [],
  )

  const accounts = processes?.accounts ?? []
  const table = useReactTable({ data: accounts, columns, getCoreRowModel: getCoreRowModel() })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-muted-foreground">
          Mỗi tài khoản là một profile Chrome riêng, chạy tối đa 1 video một lúc.
        </p>
        <div className="ml-auto flex gap-2">
          <Button
            variant="outline"
            disabled={processes?.scanning}
            onClick={() => act("/api/accounts/scan", "POST", "Đang kiểm tra tất cả tài khoản")}
          >
            <RefreshCwIcon className={processes?.scanning ? "animate-spin" : undefined} />
            {processes?.scanning ? "Đang kiểm tra…" : "Kiểm tra tất cả"}
          </Button>
          <Button onClick={() => setAdding(true)}>
            <PlusIcon /> Thêm tài khoản
          </Button>
        </div>
      </div>

      {!processes ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : !accounts.length ? (
        <EmptyState
          icon={UsersIcon}
          title="Chưa có tài khoản"
          description="Thêm một tài khoản Google có quyền tạo video trên Gemini."
          action={
            <Button onClick={() => setAdding(true)}>
              <PlusIcon /> Thêm tài khoản
            </Button>
          }
        />
      ) : (
        <Card className="py-0">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((h) => (
                    <TableHead key={h.id} className="first:pl-4 last:pr-4 last:text-right">
                      {flexRender(h.column.columnDef.header, h.getContext())}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className="first:pl-4 last:pr-4 last:text-right">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      <AddAccountDialog open={adding} onOpenChange={setAdding} onAdded={refreshProcesses} />

      <AlertDialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirm?.kind === "delete"
                ? `Xoá profile "${confirm.account.name}"?`
                : `Quên mật khẩu của "${confirm?.account.name}"?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirm?.kind === "delete"
                ? "Tool đăng xuất và xoá profile Chrome này; tài khoản Google của bạn không bị ảnh hưởng."
                : "Mật khẩu bị xoá khỏi Keychain; profile vẫn giữ đăng nhập."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Huỷ</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (!confirm) return
                const enc = encodeURIComponent(confirm.account.name)
                if (confirm.kind === "delete") act(`/api/accounts/${enc}`, "DELETE", "Đã xoá")
                else act(`/api/accounts/${enc}/password`, "DELETE", "Đã quên mật khẩu")
              }}
            >
              {confirm?.kind === "delete" ? "Xoá" : "Quên mật khẩu"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

const accountSchema = z
  .object({
    name: z
      .string()
      .trim()
      .min(1, "Nhập tên profile")
      .regex(/^[A-Za-z0-9_-]+$/, "Chỉ dùng chữ, số, '_' hoặc '-'"),
    email: z.union([z.literal(""), z.string().trim().email("Email không hợp lệ")]),
    password: z.string(),
    twoFactor: z.enum(["phone", "authenticator"]),
    totp: z.string().trim(),
  })
  .refine((v) => !v.password || v.email, { path: ["email"], message: "Cần email khi lưu mật khẩu" })
  .refine((v) => v.twoFactor !== "authenticator" || v.totp, {
    path: ["totp"],
    message: "Nhập setup key của Google Authenticator",
  })
type AccountValues = z.infer<typeof accountSchema>

function AddAccountDialog({
  open,
  onOpenChange,
  onAdded,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  onAdded: () => Promise<void>
}) {
  const form = useForm<AccountValues>({
    resolver: zodResolver(accountSchema),
    defaultValues: { name: "", email: "", password: "", twoFactor: "phone", totp: "" },
  })
  const [showPassword, setShowPassword] = useState(false)
  const twoFactor = form.watch("twoFactor")

  async function submit(v: AccountValues) {
    try {
      const totp = v.twoFactor === "authenticator" ? v.totp : ""
      await api("/api/accounts", {
        method: "POST",
        json: { name: v.name, email: v.email, password: v.password, totp },
      })
      toast.success(
        v.twoFactor === "phone"
          ? "Đã mở Chrome để đăng nhập — nếu Google hỏi, mở điện thoại và bấm Yes"
          : "Đã mở cửa sổ Chrome để đăng nhập",
      )
      form.reset()
      setShowPassword(false)
      onOpenChange(false)
      await onAdded()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setShowPassword(false)
        onOpenChange(o)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Thêm tài khoản</DialogTitle>
          <DialogDescription>
            Một cửa sổ Chrome mở trang đăng nhập Google. Có email + mật khẩu thì tool tự điền; không thì bạn tự đăng nhập.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(submit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Tên profile</FormLabel>
                  <FormControl>
                    <Input placeholder="account_01" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email (tuỳ chọn)</FormLabel>
                  <FormControl>
                    <Input type="email" placeholder="you@gmail.com" autoComplete="off" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Mật khẩu (tuỳ chọn)</FormLabel>
                  <div className="relative">
                    <FormControl>
                      <Input
                        type={showPassword ? "text" : "password"}
                        autoComplete="new-password"
                        className="pr-9"
                        {...field}
                      />
                    </FormControl>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-sm"
                      className="absolute top-1/2 right-1 -translate-y-1/2 text-muted-foreground"
                      aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                      aria-pressed={showPassword}
                      onClick={() => setShowPassword((v) => !v)}
                    >
                      {showPassword ? <EyeOffIcon /> : <EyeIcon />}
                    </Button>
                  </div>
                  <FormDescription>Lưu trong macOS Keychain, dùng để tự đăng nhập lại.</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="twoFactor"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Xác minh 2 bước</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent position="popper">
                      <SelectItem value="phone">
                        <SmartphoneIcon /> Tap Yes on your phone or tablet
                      </SelectItem>
                      <SelectItem value="authenticator">
                        <KeyRoundIcon /> Google Authenticator (mã 6 số)
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription>
                    {twoFactor === "phone"
                      ? "Khi Google hỏi, mở điện thoại/máy tính bảng và bấm Yes; số cần chọn (nếu có) hiện ở bảng Tài khoản."
                      : "Tool tự nhập mã 6 số từ setup key, không cần điện thoại."}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            {twoFactor === "authenticator" && (
              <FormField
                control={form.control}
                name="totp"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Setup key Google Authenticator</FormLabel>
                    <FormControl>
                      <Input autoComplete="off" placeholder="VD: abcd efgh ijkl mnop …" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}
            <DialogFooter>
              <DialogClose asChild>
                <Button type="button" variant="ghost">
                  Huỷ
                </Button>
              </DialogClose>
              <Button type="submit" disabled={form.formState.isSubmitting}>
                <LogInIcon /> Thêm & đăng nhập
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
