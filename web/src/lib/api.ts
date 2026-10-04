export type PairStatus = "queued" | "running" | "done" | "failed"

export type Pair = {
  id: string
  prompt_id: string
  prompt_name: string | null
  product_name: string | null
  model_image: string | null
  product_image: string | null
  image: string | null
  video: string | null
  video_start: number
  prompt: string
  account: string | null
  assigned_account?: string | null
  timeout: number
  status: PairStatus
  created_at: string
  started_at: string | null
  finished_at: string | null
  exit_code: number | null
  output: string | null
  retry_count?: number
  abandoned?: boolean
}

export type Category = "clothes" | "cosmetics" | "bag" | "shoes" | "dance" | "food" | "other"

export type PromptInputs = {
  model_image: boolean
  product_image: boolean
  ref_video: boolean
}

export type Prompt = {
  id: string
  name: string
  category: Category
  content: string
  inputs: PromptInputs
  use_rules: boolean
  needs_product_name: boolean
  created_at: string
  updated_at: string
}

export type PromptPayload = Pick<Prompt, "name" | "category" | "content" | "inputs" | "use_rules">

export type RuleKey = "general" | "product" | "person"

export type SystemRules = Record<RuleKey, string> & {
  enabled: boolean
  defaults: Record<RuleKey, string>
}

export type Account = {
  name: string
  email: string | null
  status: "ready" | "verify" | "signed_out" | "no_video" | "error" | "unknown"
  checked_at: string | null
  message: string | null
  login: { state: string; message: string | null } | null
  busy: boolean
  blocked: { reason: string; until: string | null } | null
  has_password: boolean
}

export type RunningJob = {
  pair_id: string
  image: string
  account: string
  email: string | null
  headless: boolean
  elapsed_s: number
  step: string | null
  last_log: string | null
}

export type Processes = {
  jobs: RunningJob[]
  accounts: Account[]
  scanning: boolean
  dispatcher: { active: boolean; batch_id: string | null; max_parallel: number }
  queued: number
  settings: { max_parallel: number; launch_delay_s: number; headless_default: boolean }
}

export type OutputFile = {
  name: string
  size: number
  mtime: string
  url: string
  pair_id: string | null
  prompt_name: string | null
  product_name: string | null
  category: Category | null
}

export type ModelImage = {
  id: string
  name: string
  image: string
  tags: string[]
  note: string
  use_count: number
  created_at: string
  updated_at: string
  missing: boolean
}

export type Counts = Record<PairStatus, number>

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init
  const res = await fetch(path, {
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json", ...rest.headers } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText)
  return data as T
}

export async function uploadFile(file: File, kind: "image" | "video"): Promise<string> {
  const fd = new FormData()
  fd.append("file", file)
  fd.append("kind", kind)
  const data = await api<{ path: string }>("/api/upload", { method: "POST", body: fd })
  return data.path
}
