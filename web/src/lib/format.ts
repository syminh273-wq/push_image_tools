import {
  FootprintsIcon,
  MusicIcon,
  PackageIcon,
  ShirtIcon,
  ShoppingBagIcon,
  SparklesIcon,
  UtensilsCrossedIcon,
  type LucideIcon,
} from "lucide-react"

import type { Account, Category, PairStatus, Prompt, SystemRules } from "@/lib/api"

export const CATEGORIES: { value: Category; label: string; icon: LucideIcon }[] = [
  { value: "clothes", label: "Quần áo", icon: ShirtIcon },
  { value: "cosmetics", label: "Mỹ phẩm", icon: SparklesIcon },
  { value: "bag", label: "Túi xách", icon: ShoppingBagIcon },
  { value: "shoes", label: "Giày dép", icon: FootprintsIcon },
  { value: "dance", label: "Nhảy", icon: MusicIcon },
  { value: "food", label: "Đồ ăn / uống", icon: UtensilsCrossedIcon },
  { value: "other", label: "Khác", icon: PackageIcon },
]

export function categoryOf(value: string | null | undefined) {
  return CATEGORIES.find((c) => c.value === value) ?? CATEGORIES[CATEGORIES.length - 1]
}

export const STATUS_LABEL: Record<PairStatus, string> = {
  queued: "Đang chờ",
  running: "Đang chạy",
  done: "Hoàn thành",
  failed: "Lỗi",
}

export const ACCOUNT_STATUS_LABEL: Record<Account["status"], string> = {
  ready: "Sẵn sàng",
  verify: "Cần xác minh",
  signed_out: "Chưa đăng nhập",
  no_video: "Không có Create video",
  error: "Lỗi",
  unknown: "Chưa kiểm tra",
}

export const PRODUCT_VAR = "{{product_name}}"

export const basename = (p: string | null | undefined) => (p ? p.split("/").pop() ?? "" : "")

/** Files uploaded through the web live in data/uploads and are served at /uploads/<name>. */
export const uploadUrl = (p: string | null | undefined) => (p ? `/uploads/${encodeURIComponent(basename(p))}` : "")

export const outputUrl = (p: string | null | undefined) => (p ? `/outputs/${encodeURIComponent(basename(p))}` : "")

export function fmtElapsed(s: number) {
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`
}

export function fmtTime(iso: string | null | undefined) {
  if (!iso) return "—"
  const d = new Date(iso)
  return d.toLocaleString("vi-VN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })
}

export function fmtSize(bytes: number) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** "[3/7] Attaching ..." -> 3 */
export function stepNumber(step: string | null | undefined) {
  const m = step?.match(/^\[(\d)\/7\]/)
  return m ? Number(m[1]) : 0
}

/** The rule block for a prompt — must match prompt_store.rules_for() on the server. */
export function rulesFor(prompt: Pick<Prompt, "inputs" | "use_rules">, rules: SystemRules | null) {
  if (!rules?.enabled || !prompt.use_rules) return ""
  const parts = [rules.general]
  if (prompt.inputs.product_image) parts.push(rules.product)
  if (prompt.inputs.model_image) parts.push(rules.person)
  const body = parts.filter((x) => x.trim()).join("\n")
  return body ? `STRICT CONSISTENCY RULES (must be followed in every frame):\n${body}` : ""
}

/** The text sent to Gemini — must match prompt_store.render() on the server. */
export function renderPrompt(prompt: Prompt, productName: string, rules: SystemRules | null) {
  const name = productName.trim()
  const content = prompt.content.replaceAll(PRODUCT_VAR, name || "[tên sản phẩm]")
  const block = rulesFor(prompt, rules).replaceAll(PRODUCT_VAR, name || "the product")
  return block ? `${content}\n\n${block}` : content
}
