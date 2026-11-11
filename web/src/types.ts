import type { PriceBoard } from "./lib/priceCheck"

export type Vote = {
  id: string
  name: string
  vote: string
  reason: string
  weight: number
}

export type ChartPoint = {
  c: number
  ma10: number | null
  ma20: number | null
  ma50: number | null
  ma150: number | null
  ma200: number | null
}

export type Idea = {
  id: string
  ticker: string
  company: string
  price: number
  changePct: number | null
  action: string
  side: "call" | "put" | string
  confidence: string
  score: number
  contract: {
    symbol: string
    strike: number
    expiry: string
    type: string
    dte: number
    isLeap: boolean
  }
  entry: { low: number; high: number; mid: number }
  bid: number
  ask: number
  oi: number
  volume: number
  iv: number | null
  hv: number | null
  ivLabel: string
  ivSentence: string
  spend: number
  contracts: number
  takeProfit: { price: number; dollars: number; plain: string }
  stopLoss: { price: number; dollars: number; plain: string }
  lastExitDate: string
  lastExitPlain: string
  reason: string
  news: { title: string; url: string; source: string; published: string | null }
  agents: Vote[]
  payoff: { rows: { pct: number; stock: number; value: number; pnl: number }[]; note: string }
  chart: { points: ChartPoint[]; trend: string }
  tags: string[]
  earningsDate: string | null
  riskFlags: string[]
  shortRatio: number | null
  instruction: string[]
}

export type SourceRow = { id: string; label: string; ok: boolean; detail: string }

export type PaperTrade = {
  id: string
  ticker: string
  action: string
  contractSymbol?: string
  strike?: number
  expiry?: string
  entry?: number
  lastMark?: number
  contracts?: number
  remainingContracts?: number
  status?: string
  outcome?: string
  realizedPnl?: number
  openedAt?: string
  closedAt?: string
  lastExitDate?: string
  halfClosed?: boolean
  checkNote?: string
  reason?: string
  newsUrl?: string
  confidence?: string
  side?: string
  stockAtEntry?: number | null
  lastStock?: number | null
  lastStockAt?: string
  lastChecked?: string
  markHistory?: MarkPoint[]
  probableNews?: boolean
}

export type MarkPoint = { at: string; mark: number; stock?: number | null }

export type Report = {
  version: number
  generatedAt: string | null
  runLabel?: string
  disclaimer?: string
  banner?: string
  stale?: boolean
  staleFrom?: string
  sourceHealth?: SourceRow[]
  regime?: {
    mood: string
    prefer: string
    title: string
    summary: string
    applied?: boolean
    vix?: number | null
    spyPrice?: number | null
  }
  configEcho?: {
    account?: number
    minSpend?: number
    maxSpend?: number
    maxOpen?: number
    maxPremium?: number
    minOpenInterest?: number
    priceMin?: number
    priceMax?: number
    acceptProbableNews?: boolean
    priceFirst?: boolean
    features?: Record<string, boolean>
  }
  universe?: { candidates?: number; priced?: number; chains?: number; priceChecked?: number; inRange?: number }
  ideas?: Idea[]
  watch?: Idea[]
  skipped?: { ticker: string; reason: string }[]
  catalysts?: { date: string; kind: string; title: string; url: string; tickers: string[]; plain: string }[]
  flow?: { ticker: string; contract: string; side: string; strike: number; expiry: string; volume: number; oi: number; ratio: number; note: string }[]
  squeezes?: { ticker: string; shortRatio: number; headline: string; url: string; note: string }[]
  priceChecks?: PriceBoard[]
  scorecard?: {
    account?: number
    openCount?: number
    openRisk?: number
    realizedPnl?: number
    open?: PaperTrade[]
    closed?: PaperTrade[]
    agents?: { id: string; name: string; wins: number; losses: number; weight: number; plain: string }[]
    summary?: string
    paused?: boolean
  }
  weeklyReview?: { weekOf: string; note: string; paused?: boolean }
  xPosts?: string
}
