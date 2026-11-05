import type { Report } from "../types"

export const FEATURE_IDS = [
  "ideas",
  "mood",
  "calendar",
  "flow",
  "squeeze",
  "chart",
  "cheap",
  "payoff",
  "underpriced",
  "sizing",
  "news",
  "policy",
  "sentiment",
  "options",
  "risk",
  "devil",
  "head",
  "scorecard",
  "review",
] as const

export type FeatureId = (typeof FEATURE_IDS)[number]

export const JOB_FEATURES = FEATURE_IDS.filter((id) => id !== "ideas")

export type Settings = {
  features: Record<FeatureId, boolean>
  maxPremium: number
  account: number
  minSpend: number
  maxSpend: number
  maxOpen: number
  minOpenInterest: number
  priceMin: number
  priceMax: number
  confidence: "all" | "medium" | "high"
  leapsOnly: boolean
  hideRiskFlags: boolean
  agentYesOnly: Partial<Record<FeatureId, boolean>>
  payoffMoves: number[]
  flowRatio: number
  squeezeRatio: number
  calendarDays: number
}

export const STORAGE_KEY = "options-floor-settings-v1"

export function defaultSettings(): Settings {
  const features = {} as Record<FeatureId, boolean>
  for (const id of FEATURE_IDS) features[id] = true
  return {
    features,
    maxPremium: 0.8,
    account: 800,
    minSpend: 40,
    maxSpend: 80,
    maxOpen: 5,
    minOpenInterest: 50,
    priceMin: 5,
    priceMax: 40,
    confidence: "all",
    leapsOnly: false,
    hideRiskFlags: false,
    agentYesOnly: {},
    payoffMoves: [5, 10, 20],
    flowRatio: 5,
    squeezeRatio: 0.45,
    calendarDays: 21,
  }
}

export function settingsFromEcho(echo: Report["configEcho"]): Settings {
  const next = defaultSettings()
  if (!echo) return next
  if (typeof echo.account === "number") next.account = echo.account
  if (typeof echo.minSpend === "number") next.minSpend = echo.minSpend
  if (typeof echo.maxSpend === "number") next.maxSpend = echo.maxSpend
  if (typeof echo.maxOpen === "number") next.maxOpen = echo.maxOpen
  if (typeof echo.maxPremium === "number") next.maxPremium = echo.maxPremium
  if (typeof echo.minOpenInterest === "number") next.minOpenInterest = echo.minOpenInterest
  if (typeof echo.priceMin === "number") next.priceMin = echo.priceMin
  if (typeof echo.priceMax === "number") next.priceMax = echo.priceMax
  for (const id of JOB_FEATURES) {
    const value = echo.features?.[id]
    if (typeof value === "boolean") next.features[id] = value
  }
  return next
}

export function readSavedSettings(): Settings | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return mergeSettings(JSON.parse(raw) as Partial<Settings>)
  } catch {
    return null
  }
}

export function mergeSettings(partial: Partial<Settings> | null | undefined): Settings {
  const base = defaultSettings()
  if (!partial) return base
  return {
    ...base,
    ...partial,
    features: { ...base.features, ...(partial.features ?? {}) },
    agentYesOnly: { ...(partial.agentYesOnly ?? {}) },
    payoffMoves: Array.isArray(partial.payoffMoves) ? partial.payoffMoves : base.payoffMoves,
  }
}

export function toJobConfig(settings: Settings) {
  const features: Record<string, boolean> = {}
  for (const id of JOB_FEATURES) features[id] = settings.features[id]
  return {
    account: settings.account,
    minSpend: settings.minSpend,
    maxSpend: settings.maxSpend,
    maxOpen: settings.maxOpen,
    maxPremium: settings.maxPremium,
    minOpenInterest: settings.minOpenInterest,
    priceMin: settings.priceMin,
    priceMax: settings.priceMax,
    allowHigherPriceIfCheapLeap: true,
    higherPriceMax: 80,
    maxCandidateTickers: 36,
    maxChainTickers: 18,
    headlineBatch: 15,
    requestPauseSeconds: 0.4,
    earningsDays: 6,
    features,
  }
}

export function downloadConfig(settings: Settings) {
  const blob = new Blob([JSON.stringify(toJobConfig(settings), null, 2) + "\n"], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = "config.json"
  link.click()
  URL.revokeObjectURL(url)
}
