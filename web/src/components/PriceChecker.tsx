import { useMemo, useState } from "react"
import { longDate, premium, ranAt } from "../lib/format"
import { lookupTicker, normalizeTicker } from "../lib/lookup"
import {
  daysUntil,
  judgeOption,
  moneyMove,
  nearestQuote,
  quotesFor,
  type CheckerQuote,
  type PriceBoard,
} from "../lib/priceCheck"
import { Button } from "./ui/button"
import { Input } from "./ui/input"

type Side = "call" | "put"

export function PriceChecker({
  boards,
  generatedAt,
  minOi,
  earningsWindow,
  fileHasChecker,
}: {
  boards: PriceBoard[]
  generatedAt?: string | null
  minOi: number
  earningsWindow: number
  fileHasChecker: boolean
}) {
  const [query, setQuery] = useState("")
  const [side, setSide] = useState<Side>("call")
  const [expiry, setExpiry] = useState("")
  const [strike, setStrike] = useState<number | null>(null)
  const [fetched, setFetched] = useState<Record<string, PriceBoard>>({})
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle")
  const [lookupError, setLookupError] = useState<string | null>(null)
  const today = new Date().toISOString().slice(0, 10)
  const typed = query.trim().toUpperCase()
  const board = (typed && fetched[typed]) || boards.find((item) => item.ticker === typed) || null
  const suggestions = boards.filter((item) => item.ticker.startsWith(typed)).slice(0, 12)

  async function checkStock() {
    const ticker = normalizeTicker(query)
    if (!ticker) {
      setStatus("error")
      setLookupError("Use a US ticker, such as F or AAPL.")
      return
    }
    setStatus("loading")
    setLookupError(null)
    try {
      const next = await lookupTicker(ticker, today)
      setFetched((current) => ({ ...current, [next.ticker]: next }))
      setQuery(next.ticker)
      setExpiry("")
      setStrike(null)
      setStatus("idle")
    } catch (error) {
      setStatus("error")
      setLookupError(error instanceof Error ? error.message : "The lookup did not finish.")
    }
  }

  const liveExpirations = useMemo(() => {
    if (!board) return []
    return board.expirations.filter((row) => daysUntil(row.expiry, today) >= 1)
  }, [board, today])

  const chosenExpiry = liveExpirations.some((row) => row.expiry === expiry) ? expiry : (liveExpirations[0]?.expiry ?? "")
  const quotes = board && chosenExpiry ? quotesFor(board, side, chosenExpiry, minOi) : []
  const chosen = quotes.find((quote) => quote.strike === strike) ?? nearestQuote(quotes, board?.price ?? 0)

  const waiting = !board
  const statusLine = status === "loading"
    ? `Looking up ${normalizeTicker(query) ?? "that ticker"}. This usually takes under a minute. No login.`
    : lookupError
      ? lookupError
      : board?.fresh
        ? "Loaded just now from a delayed free quote. Not a live broker price. Earnings dates are not in this lookup."
        : board
          ? `From the last saved check${generatedAt ? ` · ${ranAt(generatedAt)}` : ""}. Not a live broker quote.`
          : typed
            ? `No chain yet for ${typed}. Press Check this stock. Any US ticker works, even when the last run saved nothing.`
            : boards.length
              ? "Type any US ticker, or pick a saved name. Then choose a date and a strike."
              : fileHasChecker
                ? "This run did not save a chain. Type any US ticker and press Check this stock."
                : "Type any US ticker, such as F or AAPL, and press Check this stock. The date and strike boxes fill in after the chain loads."

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault()
        void checkStock()
      }}
    >
      <p className="text-sm leading-relaxed">{statusLine}</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="block w-full max-w-sm text-sm">
          <span className="mb-1 block text-muted">Ticker</span>
          <Input
            value={query}
            placeholder="Such as F or AAPL"
            aria-label="Ticker"
            autoCapitalize="characters"
            onChange={(event) => {
              setQuery(event.target.value.toUpperCase())
              setStrike(null)
              setLookupError(null)
              if (status === "error") setStatus("idle")
            }}
          />
        </label>
        <Button type="submit" variant="default" disabled={status === "loading"}>
          {status === "loading" ? "Checking…" : "Check this stock"}
        </Button>
      </div>
      {suggestions.length > 0 && !board ? (
        <div className="flex flex-wrap gap-2">
          {suggestions.map((item) => (
            <Button
              key={item.ticker}
              type="button"
              onClick={() => {
                setQuery(item.ticker)
                setStrike(null)
                setLookupError(null)
              }}
            >
              {item.ticker}
            </Button>
          ))}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant={side === "call" ? "default" : "outline"} onClick={() => { setSide("call"); setStrike(null) }}>
          Call
        </Button>
        <Button type="button" variant={side === "put" ? "default" : "outline"} onClick={() => { setSide("put"); setStrike(null) }}>
          Put
        </Button>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block text-muted">Expiration</span>
          <select
            className="h-11 w-full rounded-md border border-line bg-card px-3 disabled:text-muted"
            value={chosenExpiry}
            aria-label="Expiration"
            disabled={waiting || liveExpirations.length === 0}
            onChange={(event) => {
              setExpiry(event.target.value)
              setStrike(null)
            }}
          >
            {liveExpirations.length === 0 ? <option value="">Waiting for a chain</option> : null}
            {liveExpirations.map((row) => (
              <option key={row.expiry} value={row.expiry}>
                {longDate(row.expiry)} · {daysUntil(row.expiry, today) === 1 ? "1 day" : `${daysUntil(row.expiry, today)} days`}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted">Strike</span>
          <select
            className="h-11 w-full rounded-md border border-line bg-card px-3 disabled:text-muted"
            value={chosen ? String(chosen.strike) : ""}
            aria-label="Strike"
            disabled={!quotes.length}
            onChange={(event) => setStrike(Number(event.target.value))}
          >
            {quotes.length === 0 ? <option value="">Waiting for a chain</option> : null}
            {quotes.map((quote) => (
              <option key={quote.strike} value={quote.strike}>
                {premium(quote.strike)} {side} · bid {premium(quote.bid)} ask {premium(quote.ask)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {board && quotes.length === 0 && liveExpirations.length > 0 ? (
        <p className="text-sm leading-relaxed">No {side}s on this date have that many open contracts. Lower the number in Settings.</p>
      ) : null}
      {board && chosen ? (
        <VerdictOnly
          board={board}
          quote={chosen}
          side={side}
          expiry={chosenExpiry}
          today={today}
          earningsWindow={earningsWindow}
        />
      ) : null}
    </form>
  )
}

function VerdictOnly({
  board,
  quote,
  side,
  expiry,
  today,
  earningsWindow,
}: {
  board: PriceBoard
  quote: CheckerQuote
  side: Side
  expiry: string
  today: string
  earningsWindow: number
}) {
  const dte = daysUntil(expiry, today)
  const earningsDays = board.earningsDate ? daysUntil(board.earningsDate, today) : null
  const judged = judgeOption({
    spot: board.price,
    iv: quote.iv,
    hv20: board.hv20,
    hv60: board.hv60,
    ivPercentile: quote.ivPercentile,
    bid: quote.bid,
    ask: quote.ask,
    oi: quote.oi,
    dte,
    earningsDays,
    earningsWindow,
    strike: quote.strike,
    side,
  })
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted">
        {board.company} · about {premium(board.price)}
        {board.earningsDate ? ` · earnings ${longDate(board.earningsDate)}` : " · no earnings date in this lookup"}
      </p>
      <VerdictCard result={judged} board={board} quote={quote} dte={dte} earningsDays={earningsDays} />
    </div>
  )
}

function VerdictCard({
  result,
  board,
  quote,
  dte,
  earningsDays,
}: {
  result: ReturnType<typeof judgeOption>
  board: PriceBoard
  quote: CheckerQuote | null
  dte: number
  earningsDays: number | null
}) {
  const tone =
    result.verdict === "Cheap" ? "text-call" : result.verdict === "Expensive" ? "text-put" : result.verdict === "Fair" ? "text-copper" : "text-muted"
  const gap = result.spreadPct == null ? null : Math.round(result.spreadPct * 100)
  return (
    <div className="rounded-xl border border-line bg-card p-5">
      <p className={`font-serif text-5xl ${tone}`}>{result.verdict ?? "Can't say"}</p>
      <p className="mt-3 max-w-3xl text-base leading-relaxed">{result.reason}</p>
      <ul className="mt-4 space-y-1 text-sm leading-relaxed text-muted">
        <li>Option price implies {percent(quote?.iv)} swings a year. The stock's 20-day swings are {percent(board.hv20)}. The 60-day swings are {percent(board.hv60)}.</li>
        {result.expectedMove != null && result.typicalMove != null ? (
          <li>Priced-in move about {moneyMove(result.expectedMove)} over {dte === 1 ? "1 day" : `${dte} days`}. Usual move about {moneyMove(result.typicalMove)}.</li>
        ) : null}
        <li>
          {quote?.ivPercentile == null
            ? "There is not a long enough record of the stock's own swings to rank this price."
            : `That option price is higher than ${Math.round(quote.ivPercentile)}% of this stock's own 20-day swings over the past year.`}
        </li>
        <li>
          {quote ? `Bid ${premium(quote.bid)}, ask ${premium(quote.ask)}${gap == null ? "" : ` (${gap}% gap)`}. ${Math.round(quote.oi).toLocaleString("en-US")} open.` : ""}
        </li>
        <li>
          {earningsDays == null
            ? "No earnings date in this file."
            : earningsDays < 0
              ? "The earnings date in this file has passed."
              : `${earningsDays === 0 ? "Earnings are today." : earningsDays === 1 ? "Earnings are in 1 day." : `Earnings are in ${earningsDays} days.`} ${earningsDays <= dte ? "That is before this option expires." : "That is after this option expires, so it is not part of this price."}`}
        </li>
      </ul>
      {result.greeks ? (
        <div className="mt-4 rounded-lg border border-line bg-paper px-4 py-3">
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-copper">Greeks</p>
          <ul className="mt-2 space-y-2 text-sm leading-relaxed">
            <li>{result.greeks.deltaLine}</li>
            <li>{result.greeks.gammaLine}</li>
            <li>{result.greeks.thetaLine}</li>
            <li>{result.greeks.vegaLine}</li>
          </ul>
          {result.greeks.warnings.length ? (
            <ul className="mt-3 space-y-1 text-sm leading-relaxed text-put">
              {result.greeks.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
          <p className="mt-2 text-xs leading-relaxed text-muted">
            A simple model from the stock price, the strike, the time left, and the option's expected swing. It assumes a 4% interest rate and no dividend. It is not your broker's number.
          </p>
        </div>
      ) : null}
    </div>
  )
}

function percent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "unknown"
  return `${Math.round(value * 100)}%`
}
