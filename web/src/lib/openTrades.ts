import type { MarkPoint, PaperTrade } from "../types"

export const STOP_PCT = -50
export const TARGET_PCT = 100

export type TradeView = {
  cost: number | null
  value: number | null
  pnl: number | null
  pct: number | null
  daysHeld: number | null
  daysLeft: number | null
  barPosition: number | null
  status: string
  history: MarkPoint[]
}

function isoDay(iso: string | null | undefined): number | null {
  if (!iso) return null
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number)
  if (!year || !month || !day) return null
  return Date.UTC(year, month - 1, day)
}

/** Today's calendar date in New York, as a UTC midnight timestamp. */
export function todayInNewYork(now: Date = new Date()): number {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now)
  return isoDay(parts) ?? Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
}

export function daysBetween(fromIso: string | null | undefined, toDay: number): number | null {
  const from = isoDay(fromIso)
  if (from == null) return null
  return Math.round((toDay - from) / 86400000)
}

/** Where the current change sits on a bar that runs from the half-loss exit to the double. 0 to 100. */
export function barPosition(pct: number | null): number | null {
  if (pct == null || Number.isNaN(pct)) return null
  const clamped = Math.max(STOP_PCT, Math.min(TARGET_PCT, pct))
  return ((clamped - STOP_PCT) / (TARGET_PCT - STOP_PCT)) * 100
}

export function statusSentence(pct: number | null, daysLeft: number | null): string {
  let text: string
  if (pct == null) {
    text = "No fresh option price yet, so the result is unknown."
  } else {
    const size = Math.abs(Math.round(pct))
    if (pct >= TARGET_PCT) text = `Up ${size}%, at or past the double target. The next check takes profit on paper.`
    else if (pct >= 60) text = `Up ${size}%, getting close to the double target.`
    else if (pct >= 15) text = `Up ${size}%, moving the right way.`
    else if (pct >= 2) text = `Up ${size}%, a little ahead so far.`
    else if (pct > -2) text = "About flat, close to what it cost."
    else if (pct > -15) text = `Down ${size}%, a little behind so far.`
    else if (pct > -35) text = `Down ${size}%, behind but still well above the half-loss exit.`
    else if (pct > STOP_PCT) text = `Down ${size}%, getting close to the half-loss exit.`
    else text = `Down ${size}%, at or past the half-loss exit. The next check closes it on paper.`
  }
  if (daysLeft != null) {
    if (daysLeft <= 0) text += " The leave-by date is here."
    else if (daysLeft <= 7) text += ` Only ${daysLeft} day${daysLeft === 1 ? "" : "s"} left before the leave-by date.`
  }
  return text
}

/** History for the small chart. Falls back to the two stored prices, never made-up ones. */
export function tradeHistory(trade: PaperTrade): MarkPoint[] {
  const stored = (trade.markHistory ?? []).filter((point) => typeof point.mark === "number" && point.mark > 0)
  if (stored.length) return stored
  const points: MarkPoint[] = []
  if (trade.entry != null && trade.openedAt) points.push({ at: trade.openedAt, mark: trade.entry })
  if (trade.lastMark != null && trade.lastChecked && trade.lastChecked.slice(0, 10) > (trade.openedAt ?? "").slice(0, 10)) {
    points.push({ at: trade.lastChecked, mark: trade.lastMark })
  }
  return points
}

export function viewTrade(trade: PaperTrade, today: number = todayInNewYork()): TradeView {
  const count = trade.remainingContracts ?? trade.contracts ?? 0
  const entry = trade.entry ?? null
  const mark = trade.lastMark ?? null
  const cost = entry != null ? entry * 100 * count : null
  const value = mark != null ? mark * 100 * count : null
  const pnl = cost != null && value != null ? value - cost : null
  const pct = entry != null && entry > 0 && mark != null ? (mark / entry - 1) * 100 : null
  const daysHeld = daysBetween(trade.openedAt, today)
  const exit = isoDay(trade.lastExitDate)
  const daysLeft = exit == null ? null : Math.round((exit - today) / 86400000)
  return {
    cost,
    value,
    pnl,
    pct,
    daysHeld: daysHeld == null ? null : Math.max(0, daysHeld),
    daysLeft,
    barPosition: barPosition(pct),
    status: statusSentence(pct, daysLeft),
    history: tradeHistory(trade),
  }
}

export type OpenTotals = { cost: number; value: number; pnl: number; pct: number | null; priced: number; count: number }

export function openTotals(trades: PaperTrade[]): OpenTotals {
  let cost = 0
  let value = 0
  let priced = 0
  for (const trade of trades) {
    const view = viewTrade(trade)
    if (view.cost == null || view.value == null) continue
    cost += view.cost
    value += view.value
    priced += 1
  }
  const pnl = value - cost
  return { cost, value, pnl, pct: cost > 0 ? (pnl / cost) * 100 : null, priced, count: trades.length }
}

export function signedDollars(value: number): string {
  const sign = value > 0.005 ? "+" : value < -0.005 ? "−" : ""
  return `${sign}$${Math.abs(value).toFixed(2)}`
}

export function signedPct(value: number): string {
  const sign = value > 0.05 ? "+" : value < -0.05 ? "−" : ""
  return `${sign}${Math.abs(value).toFixed(1)}%`
}

/** SVG path for a small line chart. Returns null when there is nothing to draw. */
export function sparkPath(values: number[], width: number, height: number, pad = 4): { line: string; points: [number, number][]; min: number; max: number } | null {
  if (values.length === 0) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || Math.max(0.01, max * 0.1)
  const low = max - min ? min : min - span / 2
  const step = values.length > 1 ? (width - pad * 2) / (values.length - 1) : 0
  const points = values.map((value, index): [number, number] => {
    const x = values.length > 1 ? pad + index * step : width / 2
    const y = height - pad - ((value - low) / span) * (height - pad * 2)
    return [Math.round(x * 10) / 10, Math.round(y * 10) / 10]
  })
  const line = points.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x} ${y}`).join(" ")
  return { line, points, min: low, max: low + span }
}
