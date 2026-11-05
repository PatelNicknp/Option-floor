/** Cheap, Fair, or Expensive for one saved contract. No network. */

import { blackScholesGreeks, type Greeks } from "./greeks"

export type VerdictName = "Cheap" | "Fair" | "Expensive"

export type CheckerQuote = {
  strike: number
  bid: number
  ask: number
  oi: number
  iv: number | null
  ivPercentile: number | null
}

export type CheckerExpiry = {
  expiry: string
  calls: CheckerQuote[]
  puts: CheckerQuote[]
}

export type PriceBoard = {
  ticker: string
  company: string
  price: number
  hv20: number | null
  hv60: number | null
  earningsDate: string | null
  expirations: CheckerExpiry[]
}

export type JudgeInput = {
  spot: number
  iv: number | null
  hv20: number | null
  hv60: number | null
  ivPercentile: number | null
  bid: number
  ask: number
  oi: number
  dte: number
  earningsDays: number | null
  earningsWindow: number
  strike?: number
  side?: "call" | "put"
}

export type JudgeResult = {
  verdict: VerdictName | null
  reason: string
  expectedMove: number | null
  typicalMove: number | null
  spreadPct: number | null
  greeks: Greeks | null
}

const CHEAP_RATIO = 0.85
const RICH_RATIO = 1.35
const EXTREME_RATIO = 2
const LOW_OI = 50
const WIDE_SPREAD = 0.3
const THIN_SPREAD = 0.15
const HIGH_THETA_SHARE = 0.03
const LOW_DELTA = 0.15

export function daysUntil(iso: string, todayIso: string): number {
  const parse = (value: string) => {
    const [year, month, day] = value.slice(0, 10).split("-").map(Number)
    return Date.UTC(year, month - 1, day)
  }
  return Math.round((parse(iso) - parse(todayIso)) / 86400000)
}

export function moneyMove(value: number): string {
  if (!Number.isFinite(value)) return "$0"
  if (value >= 100) return `$${Math.round(value)}`
  if (value >= 10) return `$${value.toFixed(1)}`
  return `$${value.toFixed(2)}`
}

export function judgeOption(input: JudgeInput): JudgeResult {
  const empty = (reason: string): JudgeResult => ({
    verdict: null,
    reason,
    expectedMove: null,
    typicalMove: null,
    spreadPct: null,
    greeks: null,
  })

  if (!(input.spot > 0) || !(input.dte >= 1)) {
    return empty("This expiration is too close, or the stock price is missing, so there is no move to compare.")
  }
  const swings = [input.hv20, input.hv60].filter((value): value is number => value != null && value > 0.01)
  if (input.iv == null || !(input.iv > 0) || swings.length === 0) {
    return empty("There is not enough daily history, or no option price to compare, so this cannot be called cheap or expensive.")
  }
  if (!(input.bid > 0) || !(input.ask > 0) || input.ask < input.bid) {
    return empty("There is no real bid and ask, so the price is not reliable enough to call cheap or expensive.")
  }

  const usual = swings.reduce((sum, value) => sum + value, 0) / swings.length
  const ratio = input.iv / usual
  const span = Math.sqrt(input.dte / 365)
  const expectedMove = input.spot * input.iv * span
  const typicalMove = input.spot * usual * span
  const mid = (input.bid + input.ask) / 2
  const spreadPct = mid > 0 ? (input.ask - input.bid) / mid : null

  let score = 0
  if (ratio < CHEAP_RATIO) score = -2
  else if (ratio > RICH_RATIO) score = 2
  const percentile = input.ivPercentile
  let rankBump = 0
  if (percentile != null && Number.isFinite(percentile)) {
    if (percentile >= 80) rankBump = 1
    else if (percentile <= 20) rankBump = -1
  }
  score += rankBump

  let verdict: VerdictName = score <= -2 ? "Cheap" : score >= 2 ? "Expensive" : "Fair"
  const beforeRank: VerdictName = ratio < CHEAP_RATIO ? "Cheap" : ratio > RICH_RATIO ? "Expensive" : "Fair"
  const rankSoftened = rankBump !== 0 && beforeRank !== "Fair" && verdict === "Fair"

  const windowDays = Number.isFinite(input.earningsWindow) ? Math.max(0, input.earningsWindow) : 14
  const earningsDays = input.earningsDays
  const earningsInPlay =
    earningsDays != null && earningsDays >= 0 && earningsDays <= Math.min(windowDays, input.dte)

  let earningsSoftened = false
  if (earningsInPlay && verdict === "Expensive" && ratio < EXTREME_RATIO) {
    verdict = "Fair"
    earningsSoftened = true
  }
  const earningsExtreme = Boolean(earningsInPlay && verdict === "Expensive" && ratio >= EXTREME_RATIO)

  const wide = spreadPct != null && spreadPct >= WIDE_SPREAD
  const thinWide = input.oi < LOW_OI && spreadPct != null && spreadPct >= THIN_SPREAD
  let spreadShifted = false
  if (wide || thinWide) {
    if (verdict === "Cheap") {
      verdict = "Fair"
      spreadShifted = true
    } else if (verdict === "Fair") {
      verdict = "Expensive"
      spreadShifted = true
    }
  }

  const greeks =
    input.side && input.strike != null
      ? blackScholesGreeks({
          spot: input.spot,
          strike: input.strike,
          iv: input.iv,
          dte: input.dte,
          side: input.side,
        })
      : null
  let thetaShifted = false
  let longShotShifted = false
  const premiumDollars = mid * 100
  const thetaShare = greeks && premiumDollars > 0 ? greeks.dollarsLostPerDay / premiumDollars : 0
  const highTheta = Boolean(greeks && thetaShare >= HIGH_THETA_SHARE)
  const lowDelta = Boolean(greeks && Math.abs(greeks.delta) < LOW_DELTA)
  const chancePct = greeks ? Math.round(Math.abs(greeks.delta) * 100) : null
  if (highTheta) {
    if (verdict === "Cheap") {
      verdict = "Fair"
      thetaShifted = true
    } else if (verdict === "Fair") {
      verdict = "Expensive"
      thetaShifted = true
    }
  }
  if (lowDelta && verdict === "Cheap") {
    verdict = "Fair"
    longShotShifted = true
  }
  if (greeks) {
    if (highTheta && !thetaShifted) {
      greeks.warnings.push(
        `Time decay is high relative to the price: about ${moneyMove(greeks.dollarsLostPerDay)} a day, which is ${Math.round(thetaShare * 100)}% of what you pay.`,
      )
    }
    if (lowDelta && !longShotShifted && !thetaShifted && chancePct != null) {
      greeks.warnings.push(`The rough chance of finishing in the money is only about ${chancePct}%. That is a long shot.`)
    }
  }

  return {
    verdict,
    reason: reasonLine({
      verdict,
      expectedMove,
      typicalMove,
      dte: input.dte,
      spreadShifted,
      spreadPct,
      earningsInPlay,
      earningsSoftened,
      earningsExtreme,
      earningsDays,
      rankSoftened,
      beforeRank,
      percentile,
      oi: input.oi,
      thetaShifted,
      thetaLoss: greeks?.dollarsLostPerDay ?? null,
      thetaShare,
      longShotShifted,
      lowDelta,
      chancePct,
    }),
    expectedMove,
    typicalMove,
    spreadPct,
    greeks,
  }
}

export function nearestQuote(quotes: CheckerQuote[], spot: number): CheckerQuote | null {
  if (!quotes.length || !(spot > 0)) return quotes[0] ?? null
  return quotes.reduce((best, quote) =>
    Math.abs(quote.strike - spot) < Math.abs(best.strike - spot) ? quote : best,
  )
}

export function quotesFor(board: PriceBoard, side: "call" | "put", expiry: string, minOi: number): CheckerQuote[] {
  const row = board.expirations.find((item) => item.expiry === expiry)
  if (!row) return []
  const floor = Number.isFinite(minOi) ? Math.max(0, minOi) : 0
  const quotes = side === "put" ? row.puts : row.calls
  return quotes.filter((quote) => quote.oi >= floor)
}

function reasonLine(input: {
  verdict: VerdictName
  expectedMove: number
  typicalMove: number
  dte: number
  spreadShifted: boolean
  spreadPct: number | null
  earningsInPlay: boolean
  earningsSoftened: boolean
  earningsExtreme: boolean
  earningsDays: number | null
  rankSoftened: boolean
  beforeRank: VerdictName
  percentile: number | null
  oi: number
  thetaShifted?: boolean
  thetaLoss?: number | null
  thetaShare?: number
  longShotShifted?: boolean
  lowDelta?: boolean
  chancePct?: number | null
}): string {
  const look = input.verdict.toLowerCase()
  const priced = moneyMove(input.expectedMove)
  const usual = moneyMove(input.typicalMove)
  const days = input.dte === 1 ? "1 day" : `${input.dte} days`
  const gap = input.spreadPct == null ? null : Math.round(input.spreadPct * 100)
  const when = earningsWhen(input.earningsDays)
  const open = openPhrase(input.oi)

  if (input.thetaShifted && input.thetaLoss != null && input.thetaShare != null) {
    const pct = Math.round(input.thetaShare * 100)
    const chance =
      input.lowDelta && input.chancePct != null
        ? `, and the rough chance of finishing in the money is only about ${input.chancePct}%`
        : ""
    return `This looks ${look} because one contract loses about ${moneyMove(input.thetaLoss)} a day, about ${pct}% of what you pay, if the stock sits still${chance}.`
  }
  if (input.longShotShifted && input.chancePct != null) {
    return `This looks fair because the rough chance of finishing in the money is only about ${input.chancePct}%, so a lower price is still a long shot.`
  }
  if (input.spreadShifted && gap != null) {
    const thin = input.oi < LOW_OI ? ` and ${open}` : ""
    const earn = input.earningsInPlay ? `, even with earnings ${when}` : ""
    return `This looks ${look} because the ask is ${gap}% above the bid${thin}, so you pay up to get in${earn}.`
  }
  if (input.earningsSoftened) {
    return `This looks fair because earnings are ${when}, so a priced-in move of about ${priced} versus a usual ${usual} is the announcement, not an everyday markup.`
  }
  if (input.earningsExtreme) {
    return `This looks expensive even with earnings ${when}, because it prices in about a ${priced} move and the stock's usual move over ${days} is about ${usual}.`
  }
  if (input.rankSoftened && input.percentile != null) {
    const rank = Math.round(input.percentile)
    const earn = input.earningsInPlay ? `, and earnings are ${when}` : ""
    if (input.beforeRank === "Expensive") {
      return `This looks fair because recent swings were bigger than this price, yet the price is higher than only ${rank}% of this stock's own swings this past year${earn}.`
    }
    return `This looks fair because the price is under the last couple of months' swings, yet it is still higher than ${rank}% of this stock's own swings this past year${earn}.`
  }

  const move =
    input.verdict === "Fair"
      ? `This looks fair because it prices in about a ${priced} move, close to this stock's usual ${usual} move over ${days}`
      : `This looks ${look} because it prices in about a ${priced} move, and this stock's usual move over ${days} is about ${usual}`
  return `${move}${extraClause(input.percentile, gap, input.oi)}.`
}

function extraClause(percentile: number | null, gap: number | null, oi: number): string {
  if (gap != null && gap >= 30) return `, and the ask is ${gap}% above the bid`
  if (percentile != null && percentile >= 80) {
    return `, and that price is higher than ${Math.round(percentile)}% of this stock's own swings this past year`
  }
  if (percentile != null && percentile <= 20) {
    return `, and that price is higher than only ${Math.round(percentile)}% of this stock's own swings this past year`
  }
  if (oi < LOW_OI) return `, and ${openPhrase(oi)}, so the quote can jump`
  return ""
}

function earningsWhen(days: number | null): string {
  if (days == null) return "soon"
  if (days <= 0) return "today"
  if (days === 1) return "in 1 day"
  return `in ${days} days`
}

function openPhrase(oi: number): string {
  const count = Math.max(0, Math.round(oi))
  if (count === 1) return "only 1 contract is open"
  return `only ${count} contracts are open`
}
