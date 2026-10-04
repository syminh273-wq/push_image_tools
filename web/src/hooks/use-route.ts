import { useSyncExternalStore } from "react"

export type Page = "create" | "queue" | "running" | "gallery" | "prompts" | "models" | "accounts" | "settings" | "tiktok"

const PAGES: Page[] = ["create", "queue", "running", "gallery", "prompts", "models", "accounts", "settings", "tiktok"]

function subscribe(cb: () => void) {
  window.addEventListener("hashchange", cb)
  return () => window.removeEventListener("hashchange", cb)
}

const getHash = () => window.location.hash

/** Hash routing (#/queue?pair=p_x) so Flask only has to serve index.html. */
export function useRoute() {
  const hash = useSyncExternalStore(subscribe, getHash)
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?")
  const page = (PAGES.includes(path as Page) ? path : "create") as Page
  return { page, params: new URLSearchParams(query) }
}

export function navigate(page: Page, params?: Record<string, string>) {
  const q = params ? `?${new URLSearchParams(params)}` : ""
  window.location.hash = `/${page}${q}`
}
