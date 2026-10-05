import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

export function PageHeader({
  icon: Icon,
  title,
  description,
  children,
  className,
}: {
  icon?: LucideIcon
  title: string
  description?: string
  children?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="flex items-start gap-3">
        {Icon && (
            <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary/15 to-primary/5 ring-1 ring-primary/15">
              <Icon className="size-5 text-primary" />
            </div>
          )}
          <div className="grid gap-1">
            <h1 className="font-heading text-2xl font-semibold tracking-tight text-balance">{title}</h1>
            {description && (
              <p className="max-w-2xl text-sm text-muted-foreground text-pretty">{description}</p>
            )}
          </div>
        </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  )
}