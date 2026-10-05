import { useEffect, useMemo, useState } from "react"
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table"
import { ListOrderedIcon, PlayIcon, PlusIcon, RotateCcwIcon, SearchIcon } from "lucide-react"
import { toast } from "sonner"

import { EmptyState } from "@/components/empty-state"
import { PageHeader } from "@/components/page-header"
import { PairSheet } from "@/components/pair-sheet"
import { StatusBadge } from "@/components/status-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useAppData } from "@/hooks/app-data"
import { navigate, useRoute } from "@/hooks/use-route"
import type { Pair, PairStatus } from "@/lib/api"
import { STATUS_LABEL, fmtTime, uploadUrl } from "@/lib/format"

export function QueuePage() {
  const { pairs, counts, models, runPair, refreshPairs, refreshProcesses } = useAppData()
  const { params } = useRoute()
  const openId = params.get("pair")
  const [status, setStatus] = useState<"all" | PairStatus>("all")
  const [search, setSearch] = useState("")

  useEffect(() => {
    refreshPairs().catch(() => {})
    refreshProcesses().catch(() => {})
  }, [refreshPairs, refreshProcesses])

  const columns = useMemo<ColumnDef<Pair>[]>(
    () => [
      {
        id: "product",
        header: "Sản phẩm",
        accessorFn: (p) => `${p.product_name ?? ""} ${p.prompt_name ?? ""}`,
        cell: ({ row: { original: p } }) => (
          <div className="flex items-center gap-3">
            <img
              src={uploadUrl(p.product_image ?? p.image)}
              alt=""
              className="size-10 shrink-0 rounded-md border bg-muted object-cover"
            />
            <div className="min-w-0">
              <p className="truncate font-medium">{p.product_name || "—"}</p>
              <p className="truncate text-xs text-muted-foreground">{p.prompt_name}</p>
            </div>
          </div>
        ),
      },
      {
        id: "model",
        header: "Model",
        cell: ({ row: { original: p } }) => {
          const m = models?.find((x) => x.image === p.model_image)
          if (!m) return <span className="text-xs text-muted-foreground">—</span>
          return (
            <Badge variant="outline" className="gap-1.5">
              <img src={uploadUrl(m.image)} alt="" className="size-4 rounded-sm object-cover" />
              <span className="max-w-[120px] truncate">{m.name}</span>
            </Badge>
          )
        },
      },
      {
        id: "account",
        header: "Tài khoản",
        cell: ({ row: { original: p } }) => (
          <span className="text-sm text-muted-foreground">
            {p.assigned_account ?? (p.account && p.account !== "auto" ? p.account : "Tự chọn")}
          </span>
        ),
      },
      {
        id: "status",
        header: "Trạng thái",
        cell: ({ row: { original: p } }) => <StatusBadge status={p.status} />,
      },
      {
        id: "created",
        header: "Tạo lúc",
        cell: ({ row: { original: p } }) => (
          <span className="text-sm whitespace-nowrap text-muted-foreground">{fmtTime(p.created_at)}</span>
        ),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Thao tác</span>,
        cell: ({ row: { original: p } }) =>
          p.status === "running" ? null : (
            <Button
              size="sm"
              variant={p.status === "queued" ? "default" : "outline"}
              onClick={(e) => {
                e.stopPropagation()
                runPair(p.id)
                  .then(() => toast.success("Đã bắt đầu chạy"))
                  .catch((err) => toast.error(err.message))
              }}
            >
              {p.status === "queued" ? <PlayIcon /> : <RotateCcwIcon />}
              {p.status === "queued" ? "Chạy" : "Chạy lại"}
            </Button>
          ),
      },
    ],
    [runPair, models],
  )

  const data = useMemo(() => (pairs ?? []).filter((p) => status === "all" || p.status === status), [pairs, status])
  const table = useReactTable({
    data,
    columns,
    state: { globalFilter: search },
    onGlobalFilterChange: setSearch,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 20 } },
  })

  const setOpen = (id: string | null) => navigate("queue", id ? { pair: id } : undefined)
  const total = counts.queued + counts.running + counts.done + counts.failed

  if (pairs && !pairs.length) {
    return (
      <EmptyState
        icon={ListOrderedIcon}
        title="Hàng đợi trống"
        description="Tạo video đầu tiên: chọn prompt, nhập tên sản phẩm, tải ảnh lên."
        action={
          <Button onClick={() => navigate("create")}>
            <PlusIcon /> Tạo video
          </Button>
        }
      />
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        icon={ListOrderedIcon}
        title="Hàng đợi"
        description="Tất cả video đang chờ, đang chạy, đã xong hoặc lỗi. Bấm vào hàng để xem chi tiết."
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Tabs value={status} onValueChange={(v) => setStatus(v as typeof status)} className="min-w-0 overflow-x-auto">
          <TabsList>
            <TabsTrigger value="all">Tất cả ({total})</TabsTrigger>
            {(Object.keys(STATUS_LABEL) as PairStatus[]).map((s) => (
              <TabsTrigger key={s} value={s}>
                {STATUS_LABEL[s]} ({counts[s]})
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="relative sm:ml-auto sm:w-64">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Tìm sản phẩm / prompt…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8"
            aria-label="Tìm trong hàng đợi"
          />
        </div>
      </div>

      <Card className="py-0">
        {!pairs ? (
          <div className="space-y-2 p-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : (
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
              {table.getRowModel().rows.length ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    className="cursor-pointer"
                    data-state={row.original.id === openId ? "selected" : undefined}
                    onClick={() => setOpen(row.original.id)}
                    onKeyDown={(e) => e.key === "Enter" && setOpen(row.original.id)}
                    tabIndex={0}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id} className="max-w-xs first:pl-4 last:pr-4 last:text-right">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
                    Không có job nào khớp.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </Card>

      {table.getPageCount() > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
          Trang {table.getState().pagination.pageIndex + 1}/{table.getPageCount()}
          <Button variant="outline" size="sm" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
            Trước
          </Button>
          <Button variant="outline" size="sm" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
            Sau
          </Button>
        </div>
      )}

      <PairSheet
        pairId={openId}
        onOpenChange={(o) => !o && setOpen(null)}
        defaultTab={params.get("tab") === "log" ? "log" : "detail"}
      />
    </div>
  )
}
