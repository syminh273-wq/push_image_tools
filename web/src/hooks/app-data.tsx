import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { toast } from "sonner"

import { api, type Counts, type ModelImage, type OutputFile, type Pair, type Processes, type Prompt, type SystemRules } from "@/lib/api"

export type RunSettings = {
  showBrowser: boolean
  maxParallel: number
  launchDelay: number
}

const SETTINGS_KEY = "adstudio.runSettings"
const DEFAULT_SETTINGS: RunSettings = { showBrowser: true, maxParallel: 2, launchDelay: 15 }

function loadSettings(): RunSettings {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") }
  } catch {
    return DEFAULT_SETTINGS
  }
}

type AppData = {
  pairs: Pair[] | null
  counts: Counts
  processes: Processes | null
  prompts: Prompt[] | null
  rules: SystemRules | null
  outputs: OutputFile[] | null
  models: ModelImage[] | null
  settings: RunSettings
  setSettings: (s: RunSettings) => void
  refreshPairs: () => Promise<void>
  refreshProcesses: () => Promise<void>
  refreshPrompts: () => Promise<void>
  refreshRules: () => Promise<void>
  refreshOutputs: () => Promise<void>
  refreshModels: () => Promise<void>
  runPair: (id: string) => Promise<void>
  runAll: () => Promise<void>
}

const Ctx = createContext<AppData | null>(null)

const EMPTY_COUNTS: Counts = { queued: 0, running: 0, done: 0, failed: 0 }

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [pairs, setPairs] = useState<Pair[] | null>(null)
  const [counts, setCounts] = useState<Counts>(EMPTY_COUNTS)
  const [processes, setProcesses] = useState<Processes | null>(null)
  const [prompts, setPrompts] = useState<Prompt[] | null>(null)
  const [outputs, setOutputs] = useState<OutputFile[] | null>(null)
  const [models, setModels] = useState<ModelImage[] | null>(null)
  const [rules, setRules] = useState<SystemRules | null>(null)
  const [settings, setSettingsState] = useState<RunSettings>(loadSettings)
  const batchStream = useRef<EventSource | null>(null)

  const refreshPairs = useCallback(async () => {
    const data = await api<{ pairs: Pair[]; counts: Counts }>("/api/pairs")
    setPairs([...data.pairs].reverse())
    setCounts({ ...EMPTY_COUNTS, ...data.counts })
  }, [])
  const refreshProcesses = useCallback(async () => setProcesses(await api<Processes>("/api/processes")), [])
  const refreshPrompts = useCallback(async () => {
    setPrompts((await api<{ prompts: Prompt[] }>("/api/prompts")).prompts)
  }, [])
  const refreshRules = useCallback(async () => setRules(await api<SystemRules>("/api/system-rules")), [])
  const refreshOutputs = useCallback(async () => {
    setOutputs((await api<{ files: OutputFile[] }>("/api/outputs")).files)
  }, [])
  const refreshModels = useCallback(async () => {
    setModels((await api<{ models: ModelImage[] }>("/api/models")).models)
  }, [])

  // Initial load only. After this, components must call refresh*() explicitly
  // (on mount, button click, route change, etc.). No background polling.
  useEffect(() => {
    console.info("[app-data] initial load (no-polling build v2)")
    refreshPairs().catch((e) => toast.error(e.message))
    refreshProcesses().catch((e) => toast.error(e.message))
    refreshOutputs().catch((e) => toast.error(e.message))
    refreshPrompts().catch((e) => toast.error(e.message))
    refreshRules().catch((e) => toast.error(e.message))
    refreshModels().catch((e) => toast.error(e.message))
  }, [refreshPairs, refreshProcesses, refreshOutputs, refreshPrompts, refreshRules, refreshModels])

  const setSettings = useCallback((s: RunSettings) => {
    setSettingsState(s)
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(s))
    } catch {
      /* private mode: settings last for this tab only */
    }
  }, [])

  const runPair = useCallback(
    async (id: string) => {
      await api(`/api/pairs/${id}/run`, { method: "POST", json: { headless: !settings.showBrowser } })
      await Promise.all([refreshPairs(), refreshProcesses()])
    },
    [settings.showBrowser, refreshPairs, refreshProcesses],
  )

  const runAll = useCallback(async () => {
    const data = await api<{ batch_id: string; count: number; already_running?: boolean }>("/api/run-all", {
      method: "POST",
      json: { headless: !settings.showBrowser, max_parallel: settings.maxParallel, delay: settings.launchDelay },
    })
    toast.success(data.already_running ? "Run All đang chạy — đã cập nhật" : `Bắt đầu chạy ${data.count} video`)
    batchStream.current?.close()
    const es = new EventSource(`/api/stream/_batch:${data.batch_id}`)
    batchStream.current = es
    es.addEventListener("batch", (e) => {
      const obj = JSON.parse((e as MessageEvent).data)
      if (obj.event === "job_started" || obj.event === "job_finished") {
        refreshPairs().catch(() => {})
        refreshOutputs().catch(() => {})
      }
      if (obj.event === "finished") {
        es.close()
        refreshPairs().catch(() => {})
        if (obj.reason === "queue empty") toast.success("Run All đã xong")
        else toast.warning(`Run All dừng: ${obj.reason}`)
      }
    })
    await refreshProcesses()
  }, [settings, refreshPairs, refreshOutputs, refreshProcesses])

  useEffect(() => () => batchStream.current?.close(), [])

  const value = useMemo(
    () => ({
      pairs, counts, processes, prompts, rules, outputs, models, settings, setSettings,
      refreshPairs, refreshProcesses, refreshPrompts, refreshRules, refreshOutputs, refreshModels, runPair, runAll,
    }),
    [pairs, counts, processes, prompts, rules, outputs, models, settings, setSettings,
     refreshPairs, refreshProcesses, refreshPrompts, refreshRules, refreshOutputs, refreshModels, runPair, runAll],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAppData() {
  const v = useContext(Ctx)
  if (!v) throw new Error("useAppData must be used inside <AppDataProvider>")
  return v
}
