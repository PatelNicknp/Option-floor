import { useMemo, useState } from "react"
import { longDate, premium, ranAt } from "../lib/format"
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
  const today = new Date().toISOString().slice(0, 10)
  const typed = query.trim().toUpperCase()
  const board = boards.find((item) => item.ticker === typed) ?? null
  const suggestions = boards.filter((item) => item.ticker.startsWith(typed)).slice(0, 12)

  const liveExpirations = useMemo(() => {
    if (!board) return []
    return board.expirations.filter((row) => daysUntil(row.expiry, today) >= 1)
  }, [board, today])

  const chosenExpiry = liveExpirations.some((row) => row.expiry === expiry) ? expiry : (liveExpirations[0]?.expiry ?? "")
  const quotes = board && chosenExpiry ? quotesFor(board, side, chosenExpiry, minOi) : []
  const chosen = quotes.find((quote) => quote.strike === strike) ?? nearestQuote(quotes, board?.price ?? 0)

  if (!boards.length) {
    return (
      <p className="max-w-3xl text-sm leading-relaxed">
        {fileHasChecker
          ? "This run did not save an option chain, so there is nothing to check yet. The next morning or evening run will save chains for the names it already looks up."
          : "This file was built before the price checker. The next run will fill it. The page cannot ask Yahoo itself."}
      </p>
    )
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        {boards.length} name{boards.length === 1 ? "" : "s"} from the last check
        {generatedAt ? ` · ${ranAt(generatedAt)}` : ""}. Not a live broker quote.
      </p>
      <label className="block max-w-sm text-sm">
        <span className="mb-1 block text-muted">Ticker</span>
        <Input
          value={query}
          placeholder="Such as SOFI"
          aria-label="Ticker"
          autoCapitalize="characters"
          onChange={(event) => {
            setQuery(event.target.value.toUpperCase())
            setStrike(null)
          }}
        />
      </label>
      {board ? null : (
        <div>
          <p className="text-sm leading-relaxed">
            {typed
              ? `${typed} is not in this file. The checker only has names the last run already pulled a chain for.`
              : "Pick a name from the last run, or type its ticker."}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {(typed ? suggestions : boards.slice(0, 12)).map((item) => (
              <Button key={item.ticker} onClick={() => { setQuery(item.ticker); setStrike(null) }}>
                {item.ticker}
              </Button>
            ))}
          </div>
          {!typed && boards.length > 12 ? <p className="mt-2 text-sm text-muted">Type to find the rest.</p> : null}
        </div>
      )}
      {board ? (
        <CheckerForm
          board={board}
          side={side}
          expiry={chosenExpiry}
          quotes={quotes}
          chosen={chosen}
          today={today}
          earningsWindow={earningsWindow}
          onSide={(next) => {
            setSide(next)
            setStrike(null)
          }}
          onExpiry={(next) => {
            setExpiry(next)
            setStrike(null)
          }}
          onStrike={setStrike}
          expirations={liveExpirations.map((row) => row.expiry)}
        />
      ) : null}
    </div>
  )
}

function CheckerForm({
  board,
  side,
  expiry,
  quotes,
  chosen,
  today,
  earningsWindow,
  expirations,
  onSide,
  onExpiry,
  onStrike,
}: {
  board: PriceBoard
  side: Side
  expiry: string
  quotes: CheckerQuote[]
  chosen: CheckerQuote | null
  today: string
  earningsWindow: number
  expirations: string[]
  onSide: (side: Side) => void
  onExpiry: (expiry: string) => void
  onStrike: (strike: number) => void
}) {
  const dte = expiry ? daysUntil(expiry, today) : 0
  const earningsDays = board.earningsDate ? daysUntil(board.earningsDate, today) : null
  const judged = chosen
    ? judgeOption({
        spot: board.price,
        iv: chosen.iv,
        hv20: board.hv20,
        hv60: board.hv60,
        ivPercentile: chosen.ivPercentile,
        bid: chosen.bid,
        ask: chosen.ask,
        oi: chosen.oi,
        dte,
        earningsDays,
        earningsWindow,
      })
    : null

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        {board.company} · about {premium(board.price)} in this file
        {board.earningsDate ? ` · earnings ${longDate(board.earningsDate)}` : " · no earnings date in this file"}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant={side === "call" ? "default" : "outline"} onClick={() => onSide("call")}>
          Call
        </Button>
        <Button variant={side === "put" ? "default" : "outline"} onClick={() => onSide("put")}>
          Put
        </Button>
      </div>
      {expirations.length === 0 ? (
        <p className="text-sm leading-relaxed">The saved dates have passed. The next run will load new ones.</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm">
            <span className="mb-1 block text-muted">Expiration</span>
            <select
              className="h-11 w-full rounded-md border border-line bg-card px-3"
              value={expiry}
              aria-label="Expiration"
              onChange={(event) => onExpiry(event.target.value)}
            >
              {expirations.map((item) => (
                <option key={item} value={item}>
                  {longDate(item)} · {daysUntil(item, today)} days
                </option>
              ))}
            </select>
          </label>
          {quotes.length ? (
            <label className="text-sm">
              <span className="mb-1 block text-muted">Strike</span>
              <select
                className="h-11 w-full rounded-md border border-line bg-card px-3"
                value={chosen ? String(chosen.strike) : ""}
                aria-label="Strike"
                onChange={(event) => onStrike(Number(event.target.value))}
              >
                {quotes.map((quote) => (
                  <option key={quote.strike} value={quote.strike}>
                    {premium(quote.strike)} {side} · bid {premium(quote.bid)} ask {premium(quote.ask)}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="text-sm leading-relaxed">No {side}s on this date have that many open contracts. Lower the number in Settings.</p>
          )}
        </div>
      )}
      {judged ? <VerdictCard result={judged} board={board} quote={chosen} dte={dte} earningsDays={earningsDays} /> : null}
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
    </div>
  )
}

function percent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "unknown"
  return `${Math.round(value * 100)}%`
}
