import { dayMove, dollars, longDate, payoffRows, premium, stopPlain, takeProfitPlain, voteWord } from "../lib/format"
import { sizeTrade } from "../lib/sizing"
import type { Settings } from "../lib/settings"
import type { Idea } from "../types"
import { PriceChart } from "./Chart"

const TAGS: Record<string, string> = {
  cheap: "Under the premium cap",
  leap: "LEAPS",
  squeeze: "Squeeze guess",
  underpriced: "Cheap versus recent swings",
  "earnings-soon": "Earnings are close",
  filing: "Fresh filing",
  policy: "Policy in the mix",
}

export function TradeCard({ idea, settings }: { idea: Idea; settings: Settings }) {
  const isBuy = idea.action.startsWith("BUY")
  const localCount = settings.features.sizing
    ? sizeTrade(idea.entry.mid, settings.account, settings.minSpend, settings.maxSpend)
    : idea.contracts
  const count = localCount ?? idea.contracts
  const spend = Math.round(count * idea.entry.mid * 100)
  const different = localCount != null && localCount !== idea.contracts
  const votes = idea.agents.filter((vote) => settings.features[vote.id as keyof Settings["features"]] !== false)
  const moves = settings.payoffMoves.flatMap((move) => [-move, move]).sort((a, b) => a - b)
  const rows =
    localCount != null && localCount !== idea.contracts
      ? payoffRows(idea.side, idea.contract.strike, idea.entry.mid, localCount, idea.price, moves)
      : idea.payoff.rows.filter((row) => moves.includes(row.pct))
  const move = dayMove(idea.changePct)
  const call = idea.side === "call"

  return (
    <article className={`overflow-hidden rounded-xl border border-line bg-card shadow-card ${call ? "border-l-4 border-l-call" : "border-l-4 border-l-put"}`}>
      <div className="p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-serif text-4xl leading-none">{idea.ticker}</p>
            <p className="mt-2 text-sm text-muted">
              {idea.company} · about {premium(idea.price)}
              {move ? ` · ${move}` : ""}
            </p>
          </div>
          <div className="text-right">
            <p className={`text-sm font-semibold uppercase tracking-wide ${isBuy ? (call ? "text-call" : "text-put") : "text-copper"}`}>
              {idea.action}
            </p>
            <p className="mt-1 text-sm text-muted">{idea.confidence === "Off" ? "No final call" : `${idea.confidence} confidence`}</p>
          </div>
        </div>

        <p className="mt-5 font-serif text-2xl leading-snug">
          {longDate(idea.contract.expiry)} · {premium(idea.contract.strike)} {idea.side}
        </p>
        {idea.contract.isLeap ? (
          <p className="mt-2 text-sm text-muted">This is a LEAPS contract. It expires more than nine months out. It can still go to zero.</p>
        ) : null}

        <dl className="mt-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg bg-paper px-3 py-3">
            <dt className="text-xs uppercase tracking-wide text-muted">Try to pay</dt>
            <dd className="mt-1 text-lg">{premium(idea.entry.low)} to {premium(idea.entry.high)}</dd>
          </div>
          <div className="rounded-lg bg-paper px-3 py-3">
            <dt className="text-xs uppercase tracking-wide text-muted">Spend</dt>
            <dd className="mt-1 text-lg">{count} contract{count === 1 ? "" : "s"} · about {dollars(spend)}</dd>
          </div>
          <div className="rounded-lg bg-paper px-3 py-3">
            <dt className="text-xs uppercase tracking-wide text-muted">Leave by</dt>
            <dd className="mt-1 text-lg">{longDate(idea.lastExitDate)}</dd>
          </div>
        </dl>
        {localCount == null ? (
          <p className="mt-3 text-sm text-put">This contract does not fit your page's small-bet settings. The file planned {idea.contracts} contract{idea.contracts === 1 ? "" : "s"} (about {dollars(idea.spend)}).</p>
        ) : different ? (
          <p className="mt-3 text-sm text-muted">The file planned {idea.contracts} contract{idea.contracts === 1 ? "" : "s"} (about {dollars(idea.spend)}). Your page settings change it to {localCount}.</p>
        ) : null}

        <p className="mt-5 text-lg leading-relaxed">{idea.reason}</p>
        {idea.news?.url ? (
          <a className="mt-2 inline-flex min-h-11 items-center text-copper underline decoration-copper/40 underline-offset-4" href={idea.news.url} target="_blank" rel="noreferrer">
            Read the headline
          </a>
        ) : null}

        {idea.tags?.length ? (
          <ul className="mt-4 flex flex-wrap gap-2 text-xs text-muted">
            {idea.tags.map((tag) => (
              <li key={tag} className="rounded-full border border-line px-2 py-1">{TAGS[tag] ?? tag}</li>
            ))}
          </ul>
        ) : null}

        {isBuy ? (
          <div className="mt-5 space-y-2 text-sm leading-relaxed">
            <p><span className="font-medium">Take profit. </span>{localCount == null ? idea.takeProfit.plain : takeProfitPlain(idea.entry.mid, localCount)}</p>
            <p><span className="font-medium">Stop. </span>{localCount == null ? idea.stopLoss.plain : stopPlain(idea.entry.mid, localCount)}</p>
            <p><span className="font-medium">Last day. </span>{idea.lastExitPlain}</p>
          </div>
        ) : (
          <p className="mt-5 text-sm text-muted">This is research only. It is not a buy instruction.</p>
        )}

        {idea.riskFlags?.length ? (
          <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-put">
            {idea.riskFlags.map((flag) => <li key={flag}>{flag}</li>)}
          </ul>
        ) : null}

        {isBuy && idea.instruction?.length ? (
          <div className="mt-5 rounded-lg bg-paper px-4 py-3">
            <p className="text-sm font-medium">What you would do at your own broker</p>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm leading-relaxed">
              {idea.instruction.map((step) => <li key={step}>{step}</li>)}
            </ol>
          </div>
        ) : null}

        {settings.features.underpriced && idea.ivSentence ? (
          <p className="mt-4 text-sm leading-relaxed text-muted">{idea.ivSentence}</p>
        ) : null}

        {settings.features.chart && idea.chart?.points ? (
          <div className="mt-5">
            <PriceChart points={idea.chart.points} label={`${idea.ticker} daily price and moving averages`} />
          </div>
        ) : null}

        {settings.features.payoff && rows.length ? (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[28rem] text-left text-sm">
              <caption className="mb-2 text-left text-muted">{idea.payoff.note}</caption>
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-wide text-muted">
                  <th className="py-2 font-medium">Stock move</th>
                  <th className="py-2 font-medium">Stock price</th>
                  <th className="py-2 font-medium">Option at expiration</th>
                  <th className="py-2 font-medium">Profit or loss</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.pct} className="border-b border-line/80">
                    <td className="py-2">{row.pct > 0 ? `+${row.pct}%` : `${row.pct}%`}</td>
                    <td className="py-2">{premium(row.stock)}</td>
                    <td className="py-2">{dollars(row.value)}</td>
                    <td className={`py-2 ${row.pnl >= 0 ? "text-call" : "text-put"}`}>{dollars(row.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {votes.length ? (
          <ul className="mt-5 divide-y divide-line border-t border-line">
            {votes.map((vote) => (
              <li key={vote.id} className="py-3">
                <p className="text-sm">
                  <span className="font-medium">{vote.name}</span>
                  <span className={`ml-2 ${vote.vote === "yes" ? "text-call" : vote.vote === "no" ? "text-put" : "text-muted"}`}>{voteWord(vote.vote)}</span>
                  {settings.features.scorecard && vote.weight && Math.abs(vote.weight - 1) >= 0.02 ? (
                    <span className="ml-2 text-muted">{vote.weight > 1 ? "Counts a little more lately." : "Counts a little less lately."}</span>
                  ) : null}
                </p>
                <p className="mt-1 text-sm leading-relaxed text-muted">{vote.reason}</p>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </article>
  )
}
