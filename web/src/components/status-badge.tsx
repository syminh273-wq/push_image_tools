import { CheckCircle2Icon, ClockIcon, LoaderCircleIcon, XCircleIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { PairStatus } from "@/lib/api"
import { STATUS_LABEL } from "@/lib/format"

const STYLE = {
  queued: { variant: "outline", icon: ClockIcon },
  running: { variant: "secondary", icon: LoaderCircleIcon },
  done: { variant: "default", icon: CheckCircle2Icon },
  failed: { variant: "destructive", icon: XCircleIcon },
} as const

export function StatusBadge({ status }: { status: PairStatus }) {
  const s = STYLE[status] ?? STYLE.queued
  return (
    <Badge variant={s.variant}>
      <s.icon className={status === "running" ? "animate-spin" : undefined} />
      {STATUS_LABEL[status] ?? status}
    </Badge>
  )
}
