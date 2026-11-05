/** Load any US ticker from free delayed quotes. No login and no token. */

import { daysUntil, type CheckerQuote, type PriceBoard } from "./priceCheck"

const STRIKES_PER_SIDE = 15
const MIN_HISTORY = 30

export type RawContract = {
  side: "call" | "put"
  expiry: string
  strike: number
  bid: number
  ask: number
  oi: number
  iv: number | null
}

/** A public reader. Yahoo, Nasdaq, and Cboe do not let this website read them directly. */
export function readerUrl(target: string): string {
  return `https://r.jina.ai/${target}`
}

export function cboeChainUrl(symbol: string): string {
  return `https://cdn.cboe.com/api/global/delayed_quotes/options/${encodeURIComponent(symbol)}.json`
}

export function yahooChartUrl(symbol: string): string {
  return `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=2y&interval=1d&includePrePost=false`
}

export function normalizeTicker(raw: string): string | null {
  const ticker = raw.trim().toUpperCase().replace(/\s+/g, "")
  if (!/^[A-Z]{1,5}([.-][A-Z]{1,2})?$/.test(ticker)) return null
  return ticker
}

export function cboeSymbol(ticker: string): string {
  return ticker.replace(/[.-]/g, "")
}

export function yahooSymbol(ticker: string): string {
  return ticker.replace(/\./g, "-")
}

export function extractJson(text: string): unknown {
  const marker = "Markdown Content:"
  const at = text.indexOf(marker)
  const slice = at >= 0 ? text.slice(at + marker.length) : text
  const start = slice.indexOf("{")
  const end = slice.lastIndexOf("}")
  if (start < 0 || end <= start) throw new Error("The reader did not return price data.")
  return JSON.parse(slice.slice(start, end + 1))
}

export function parseCboeOptionSymbol(symbol: string): { expiry: string; side: "call" | "put"; strike: number } | null {
  const match = /(\d{6})([CP])(\d{8})$/.exec(symbol)
  if (!match) return null
  const yy = Number(match[1].slice(0, 2))
  const month = match[1].slice(2, 4)
  const day = match[1].slice(4, 6)
  const strike = Number(match[3]) / 1000
  if (!Number.isFinite(strike) || strike <= 0) return null
  return {
    expiry: `${2000 + yy}-${month}-${day}`,
    side: match[2] === "P" ? "put" : "call",
    strike,
  }
}

export function parseCboeChain(payload: unknown): { price: number | null; contracts: RawContract[] } {
  if (!payload || typeof payload !== "object") throw new Error("No option chain.")
  const data = (payload as { data?: unknown }).data
  if (!data || typeof data !== "object") throw new Error("No option chain.")
  const row = data as { current_price?: unknown; options?: unknown }
  if (!Array.isArray(row.options)) throw new Error("No option chain.")
  const contracts: RawContract[] = []
  for (const item of row.options) {
    if (!item || typeof item !== "object") continue
    const raw = item as Record<string, unknown>
    const parsed = parseCboeOptionSymbol(String(raw.option ?? ""))
    if (!parsed) continue
    const iv = typeof raw.iv === "number" ? raw.iv : Number(raw.iv)
    contracts.push({
      ...parsed,
      bid: asNumber(raw.bid),
      ask: asNumber(raw.ask),
      oi: asNumber(raw.open_interest),
      iv: Number.isFinite(iv) ? iv : null,
    })
  }
  const price = typeof row.current_price === "number" && row.current_price > 0 ? row.current_price : null
  return { price, contracts }
}

export function parseYahooChart(payload: unknown): { price: number | null; name: string; closes: number[] } {
  if (!payload || typeof payload !== "object") throw new Error("No daily prices.")
  const result = ((payload as { chart?: { result?: unknown[] } }).chart?.result ?? [])[0]
  if (!result || typeof result !== "object") throw new Error("No daily prices.")
  const row = result as {
    meta?: { regularMarketPrice?: unknown; shortName?: unknown; longName?: unknown; symbol?: unknown }
    timestamp?: unknown[]
    indicators?: { quote?: { close?: unknown[] }[]; adjclose?: { adjclose?: unknown[] }[] }
  }
  const stamps = row.timestamp ?? []
  const adj = row.indicators?.adjclose?.[0]?.adjclose
  const rawCloses = row.indicators?.quote?.[0]?.close
  const series = adj && adj.length === stamps.length ? adj : rawCloses
  const closes: number[] = []
  if (series) {
    for (const value of series) {
      if (typeof value === "number" && value > 0) closes.push(value)
    }
  }
  const meta = row.meta ?? {}
  const market = typeof meta.regularMarketPrice === "number" ? meta.regularMarketPrice : null
  const name = String(meta.shortName || meta.longName || meta.symbol || "")
  return { price: market != null && market > 0 ? market : (closes.at(-1) ?? null), name, closes }
}

export function realizedVol(closes: number[], window = 20): number | null {
  if (closes.length < window + 1) return null
  const tail = closes.slice(-(window + 1))
  const returns: number[] = []
  for (let index = 1; index < tail.length; index += 1) {
    const earlier = tail[index - 1]
    const later = tail[index]
    if (earlier <= 0 || later <= 0) return null
    returns.push(Math.log(later / earlier))
  }
  if (returns.length < 2) return null
  const mean = returns.reduce((sum, value) => sum + value, 0) / returns.length
  const variance = returns.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (returns.length - 1)
  return Math.sqrt(variance) * Math.sqrt(252)
}

export function hvHistory(closes: number[], window = 20): number[] {
  const vols: number[] = []
  for (let end = window + 1; end <= closes.length; end += 1) {
    const vol = realizedVol(closes.slice(0, end), window)
    if (vol != null && vol > 0) vols.push(vol)
  }
  return vols.slice(-252)
}

export function percentileBelow(samples: number[], value: number | null): number | null {
  if (value == null || value <= 0 || samples.length < MIN_HISTORY) return null
  const below = samples.filter((item) => item < value).length
  return Math.round((100 * below) / samples.length)
}

export function buildLookupBoard(input: {
  ticker: string
  company: string
  price: number
  closes: number[]
  contracts: RawContract[]
  today: string
}): PriceBoard | null {
  if (!(input.price > 0)) return null
  const history = hvHistory(input.closes, 20)
  const grouped = new Map<string, RawContract[]>()
  for (const contract of input.contracts) {
    if (daysUntil(contract.expiry, input.today) < 1) continue
    const list = grouped.get(contract.expiry) ?? []
    list.push(contract)
    grouped.set(contract.expiry, list)
  }
  const expirations = [...grouped.keys()]
    .sort()
    .map((expiry) => {
      const rows = grouped.get(expiry) ?? []
      return {
        expiry,
        calls: trimSide(rows, "call", input.price, history),
        puts: trimSide(rows, "put", input.price, history),
      }
    })
    .filter((row) => row.calls.length > 0 || row.puts.length > 0)
  if (!expirations.length) return null
  const hv20 = realizedVol(input.closes, 20)
  const hv60 = realizedVol(input.closes, 60)
  return {
    ticker: input.ticker,
    company: input.company || input.ticker,
    price: round(input.price, 2),
    hv20: hv20 == null ? null : round(hv20, 4),
    hv60: hv60 == null ? null : round(hv60, 4),
    earningsDate: null,
    expirations,
    fresh: true,
  }
}

export async function lookupTicker(raw: string, today: string, fetchImpl: typeof fetch = fetch): Promise<PriceBoard> {
  const ticker = normalizeTicker(raw)
  if (!ticker) throw new Error("Use a US ticker, such as F or AAPL.")
  let chainText = ""
  let chartText = ""
  try {
    const [chainResponse, chartResponse] = await Promise.all([
      fetchImpl(readerUrl(cboeChainUrl(cboeSymbol(ticker)))),
      fetchImpl(readerUrl(yahooChartUrl(yahooSymbol(ticker)))),
    ])
    if (!chainResponse.ok) throw new Error(`The free reader returned ${chainResponse.status}. Wait a minute and try again.`)
    chainText = await chainResponse.text()
    if (chartResponse.ok) chartText = await chartResponse.text()
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("The free reader")) throw error
    throw new Error("The free reader did not answer. Wait a minute and try again.")
  }
  let chain: { price: number | null; contracts: RawContract[] }
  try {
    chain = parseCboeChain(extractJson(chainText))
  } catch {
    throw new Error(`${ticker} did not come back as a US stock with options. Check the spelling.`)
  }
  let chart = { price: null as number | null, name: ticker, closes: [] as number[] }
  if (chartText) {
    try {
      chart = parseYahooChart(extractJson(chartText))
    } catch {
      chart = { price: null, name: ticker, closes: [] }
    }
  }
  const price = chain.price ?? chart.price
  if (price == null) throw new Error(`No stock price came back for ${ticker}.`)
  const board = buildLookupBoard({
    ticker,
    company: chart.name || ticker,
    price,
    closes: chart.closes,
    contracts: chain.contracts,
    today,
  })
  if (!board) throw new Error(`${ticker} has no listed option with a bid, an ask, and an expected swing.`)
  return board
}

function trimSide(contracts: RawContract[], side: "call" | "put", spot: number, history: number[]): CheckerQuote[] {
  const best = new Map<number, RawContract>()
  for (const contract of contracts) {
    if (contract.side !== side || !quoted(contract)) continue
    const previous = best.get(contract.strike)
    if (!previous || contract.oi > previous.oi) best.set(contract.strike, contract)
  }
  const pool = [...best.values()].sort((a, b) => Math.abs(a.strike - spot) - Math.abs(b.strike - spot) || a.strike - b.strike)
  return pool.slice(0, STRIKES_PER_SIDE).sort((a, b) => a.strike - b.strike).map((contract) => ({
    strike: contract.strike,
    bid: round(contract.bid, 2),
    ask: round(contract.ask, 2),
    oi: Math.round(contract.oi),
    iv: round(contract.iv ?? 0, 4),
    ivPercentile: percentileBelow(history, contract.iv),
  }))
}

function quoted(contract: RawContract): boolean {
  return contract.iv != null && contract.iv > 0 && contract.bid > 0 && contract.ask >= contract.bid
}

function asNumber(value: unknown): number {
  const number = typeof value === "number" ? value : Number(value)
  return Number.isFinite(number) ? number : 0
}

function round(value: number, digits: number): number {
  const scale = 10 ** digits
  return Math.round(value * scale) / scale
}
