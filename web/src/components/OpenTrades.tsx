import { longDate, premium } from "../lib/format"
import { openTotals, signedDollars, signedPct, sparkPath, viewTrade } from "../lib/openTrades"
import type { PaperTrade } from "../types"

function tone(value: number | null | undefined): string {
  if (value == null) return "text-muted"
  if (value > 0.005) return "text-call"
  if (value < -0.005) return "text-put"
  return "text-ink"
}

function shortDate(iso: string | null | undefined): string {
  return longDate(iso).replace(/, \d{4}$/, "")
}

export function OpenTotalsLine({ trades }: { trades: PaperTrade[] }) {
  const totals = openTotals(trades)
  if (!totals.count) return null
  return (
    <div className="mt-2 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line text-sm sm:grid-cols-4">
      <div className="bg-card px-3 py-2">
        <p className="text-xs uppercase tracking-wide text-muted">Total cost</p>
        <p className="mt-0.5 text-lg font-medium">${totals.cost.toFixed(2)}</p>
      </div>
      <div className="bg-card px-3 py-2">
        <p className="text-xs uppercase tracking-wide text-muted">Worth now</p>
        <p className="mt-0.5 text-lg font-medium">${totals.value.toFixed(2)}</p>
      </div>
      <div className="bg-card px-3 py-2">
        <p className="text-xs uppercase tracking-wide text-muted">Gain or loss</p>
        <p className={`mt-0.5 text-lg font-semibold ${tone(totals.pnl)}`}>{signedDollars(totals.pnl)}</p>
      </div>
      <div className="bg-card px-3 py-2">
        <p className="text-xs uppercase tracking-wide text-muted">Percent</p>
        <p className={`mt-0.5 text-lg font-semibold ${tone(totals.pnl)}`}>{totals.pct == null ? "Unknown" : signedPct(totals.pct)}</p>
      </div>
      {totals.priced < totals.count ? (
        <p className="col-span-2 bg-card px-3 py-2 text-xs text-muted sm:col-span-4">
          {totals.count - totals.priced} open trade{totals.count - totals.priced === 1 ? "" : "s"} had no price, so the totals leave {totals.count - totals.priced === 1 ? "it" : "them"} out.
        </p>
      ) : null}
    </div>
  )
}

function Sparkline({ trade, up }: { trade: PaperTrade; up: boolean | null }) {
  const history = viewTrade(trade).history
  const width = 300
  const height = 56
  const shape = sparkPath(history.map((point) => point.mark), width, height)
  if (!shape) return null
  const entry = trade.entry ?? history[0].mark
  const entryY = height - 4 - ((entry - shape.min) / (shape.max - shape.min)) * (height - 8)
  const color = up == null ? "#6e6458" : up ? "#1b7a49" : "#a33b32"
  const last = shape.points[shape.points.length - 1]
  return (
    <div className="mt-3">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-14 w-full" preserveAspectRatio="none" role="img" aria-label={`Option price since entry, ${history.length} checks`}>
        <line x1="0" x2={width} y1={entryY} y2={entryY} stroke="#e4d7c4" strokeDasharray="4 4" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        <path d={shape.line} fill="none" stroke={color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {shape.points.map(([x, y], index) => (
          <circle key={index} cx={x} cy={y} r={index === shape.points.length - 1 ? 3.5 : 2} fill={color} />
        ))}
        <circle cx={last[0]} cy={last[1]} r="6" fill={color} opacity="0.15" />
      </svg>
      <div className="flex justify-between text-xs text-muted">
        <span>{shortDate(history[0].at)} · {premium(history[0].mark)}</span>
        <span>
          {history.length <= 2 ? "Fills in each run · " : ""}
          {shortDate(history[history.length - 1].at)} · {premium(history[history.length - 1].mark)}
        </span>
      </div>
    </div>
  )
}

function ProgressBar({ trade, position, pct }: { trade: PaperTrade; position: number | null; pct: number | null }) {
  const entry = trade.entry
  const zero = 100 / 3
  const fill = position == null ? null : position >= zero ? { left: zero, width: position - zero } : { left: position, width: zero - position }
  const up = pct != null && pct >= 0
  return (
    <div className="mt-4">
      <div className="relative h-3 rounded-full bg-paper ring-1 ring-line">
        {fill ? (
          <div
            className={`absolute top-0 h-3 ${up ? "rounded-r-full bg-call/70" : "rounded-l-full bg-put/70"}`}
            style={{ left: `${fill.left}%`, width: `${fill.width}%` }}
          />
        ) : null}
        <div className="absolute -top-1 h-5 w-px bg-muted/60" style={{ left: `${zero}%` }} aria-hidden="true" />
        {position != null ? (
          <div
            className="absolute -top-1.5 h-6 w-6 -translate-x-1/2 rounded-full border-2 border-card bg-ink shadow"
            style={{ left: `${position}%` }}
            aria-label={`Now ${pct == null ? "unknown" : signedPct(pct)}`}
          />
        ) : null}
      </div>
      <div className="relative mt-2 h-4 text-xs font-medium">
        <span className="absolute left-0 text-put">{entry != null ? premium(entry * 0.5) : ""}</span>
        <span className="absolute -translate-x-1/2 whitespace-nowrap text-muted" style={{ left: `${zero}%` }}>Paid {entry != null ? premium(entry) : "?"}</span>
        <span className="absolute right-0 text-call">{entry != null ? premium(entry * 2) : ""}</span>
      </div>
      <div className="mt-1 flex justify-between text-xs text-muted">
        <span>Half-loss exit (−50%)</span>
        <span>Double target (+100%)</span>
      </div>
    </div>
  )
}

function Fact({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className={`mt-0.5 ${muted ? "text-muted italic" : ""}`}>{value}</dd>
    </div>
  )
}

export function OpenTradeCard({ trade }: { trade: PaperTrade }) {
  const view = viewTrade(trade)
  const side = trade.side || (trade.action.includes("CALL") ? "call" : "put")
  const call = side === "call"
  const count = trade.remainingContracts ?? trade.contracts ?? 0
  const up = view.pnl == null ? null : view.pnl >= 0
  return (
    <li className={`rounded-xl border border-line bg-card shadow-card ${call ? "border-l-4 border-l-call" : "border-l-4 border-l-put"}`}>
      <div className="p-4 sm:p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-serif text-3xl leading-none">{trade.ticker}</p>
            <p className={`mt-2 text-sm font-semibold uppercase tracking-wide ${call ? "text-call" : "text-put"}`}>
              {trade.action} · {count} contract{count === 1 ? "" : "s"}
            </p>
          </div>
          <div className="text-right">
            <p className={`font-serif text-3xl leading-none ${tone(view.pnl)}`}>{view.pct == null ? "?" : signedPct(view.pct)}</p>
            <p className={`mt-2 text-sm font-medium ${tone(view.pnl)}`}>{view.pnl == null ? "No price yet" : signedDollars(view.pnl)}</p>
          </div>
        </div>

        <p className="mt-3 text-sm">
          Paid <span className="font-medium">{trade.entry != null ? premium(trade.entry) : "?"}</span>
          {" → "}now <span className="font-medium">{trade.lastMark != null ? premium(trade.lastMark) : "?"}</span>
          <span className="text-muted"> a share · {view.cost != null ? `$${view.cost.toFixed(0)} in` : ""}{view.value != null ? `, $${view.value.toFixed(0)} now` : ""}</span>
        </p>

        <Sparkline trade={trade} up={up} />
        <ProgressBar trade={trade} position={view.barPosition} pct={view.pct} />

        <p className="mt-4 rounded-lg bg-paper px-3 py-2 text-sm leading-relaxed">{view.status}</p>

        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-3 md:grid-cols-2 xl:grid-cols-3">
          <Fact label="Contract" value={`${trade.strike != null ? `$${Number.isInteger(trade.strike) ? trade.strike : trade.strike.toFixed(2)}` : "?"} ${side} · expires ${longDate(trade.expiry)}`} />
          <Fact label="Stock when bought" value={trade.stockAtEntry != null ? premium(trade.stockAtEntry) : "Not recorded"} muted={trade.stockAtEntry == null} />
          <Fact label="Stock now" value={trade.lastStock != null ? premium(trade.lastStock) : "Not checked yet"} muted={trade.lastStock == null} />
          <Fact label="Opened" value={`${shortDate(trade.openedAt)}${view.daysHeld != null ? ` · ${view.daysHeld} day${view.daysHeld === 1 ? "" : "s"} held` : ""}`} />
          <Fact
            label="Leave by"
            value={`${shortDate(trade.lastExitDate)}${view.daysLeft != null ? ` · ${Math.max(0, view.daysLeft)} day${view.daysLeft === 1 ? "" : "s"} left` : ""}`}
          />
          <Fact label="Last price check" value={trade.lastChecked ? longDate(trade.lastChecked) : "Not yet"} />
        </dl>

        {trade.halfClosed ? <p className="mt-3 text-sm text-muted">Sold half at a double. The rest is still open.</p> : null}
        {trade.checkNote ? <p className="mt-3 text-sm text-copper">{trade.checkNote}</p> : null}
        {trade.probableNews ? <p className="mt-3 text-sm text-muted">The news only leaned this way, so it was capped at Low confidence.</p> : null}
      </div>
    </li>
  )
}
