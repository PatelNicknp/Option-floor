import { useCallback, useEffect, useMemo, useState } from "react"
import { ChartLegend } from "./components/Chart"
import { FeatureBlock } from "./components/FeatureBlock"
import { TradeCard } from "./components/TradeCard"
import { Button } from "./components/ui/button"
import { Input } from "./components/ui/input"
import { daySpan, dollars, longDate, outcomePlain, premium, ranAt } from "./lib/format"
import {
  FEATURE_IDS,
  STORAGE_KEY,
  defaultSettings,
  downloadConfig,
  readSavedSettings,
  settingsFromEcho,
  type FeatureId,
  type Settings,
} from "./lib/settings"
import type { Idea, Report } from "./types"

const NAV = [
  ["ideas", "Ideas"],
  ["mood", "Mood"],
  ["calendar", "Calendar"],
  ["flow", "Flow"],
  ["squeeze", "Squeezes"],
  ["scorecard", "Scorecard"],
  ["review", "Review"],
  ["save", "Settings file"],
]

const DESK: { id: FeatureId; title: string; description: string; help: string }[] = [
  {
    id: "news",
    title: "News Scout",
    description: "Reads company headlines and filings and says whether the news supports a call, a put, or neither.",
    help: "A call needs news that the company is doing better. A put needs news that it is doing worse. A mild headline is not enough. Turning this off hides the vote on each card. The job still reads the news, because ideas start there.",
  },
  {
    id: "policy",
    title: "Policy & Politics Scout",
    description: "Looks at the Fed, the White House, Congress, the Federal Register, and the FDA. A sector guess is labeled as a guess.",
    help: "A new law or a Fed note rarely names one small stock. When this scout connects a headline to a whole industry, the card says it is a rough guess. It cannot be the only reason for a buy.",
  },
  {
    id: "sentiment",
    title: "Sentiment Scout",
    description: "Counts upbeat and grim words in the headlines. X posts are not included.",
    help: "There is no stable way to read X without a login, so those posts are skipped. Word counts are a tone check. They do not override a clear headline.",
  },
  {
    id: "chart",
    title: "Chart Reader",
    description: "Uses daily prices only. Green, orange, blue, yellow, and red are the 10, 20, 50, 150, and 200 day averages.",
    help: "There is no intraday chart. If the averages point the other way from the news, this scout votes no. Turning it off hides the chart on each card.",
  },
  {
    id: "options",
    title: "Options Picker",
    description: "Picks one strike and one expiration, including a cheap LEAPS when the price is still under the cap.",
    help: "The picker wants a real bid and ask, some open interest, and a premium near the middle of your spend band. If this scout is turned off in config.json, the next run will not name a contract.",
  },
  {
    id: "risk",
    title: "Risk Checker",
    description: "Throws out contracts that are hard to trade, and skips earnings that are only a day or two away.",
    help: "A wide bid-ask spread means you can overpay and struggle to sell. Earnings in the next two days can crush an option even if you guess the direction. Leave this on.",
  },
  {
    id: "devil",
    title: "Devil's Advocate",
    description: "Looks for the hole: a wide market, a thin contract, a chart that fights the idea, or news that may already be in the stock.",
    help: "One worry is a pass. Two worries are a no. Three or more block the idea. Pass means it is not a reason to do the trade and not a reason to block it.",
  },
  {
    id: "head",
    title: "Head Trader",
    description: "Turns the votes into Buy call, Buy put, or no trade, and stamps High, Medium, or Low confidence.",
    help: "This switch hides the Head Trader's line on each card. It does not cancel a buy that is already in the file. To stop new buy instructions, turn Head Trader off in config.json before the next run.",
  },
]

export function App() {
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [settings, setSettings] = useState<Settings>(() => readSavedSettings() ?? defaultSettings())
  const [persist, setPersist] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    const hadSaved = localStorage.getItem(STORAGE_KEY) != null
    fetch(`${import.meta.env.BASE_URL}data/latest.json`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`The idea file returned ${response.status}.`)
        return (await response.json()) as Report
      })
      .then((data) => {
        setReport(data)
        if (!hadSaved) setSettings(settingsFromEcho(data.configEcho))
        setPersist(true)
        setLoading(false)
      })
      .catch((reason: unknown) => {
        const message = reason instanceof Error ? reason.message : "The idea file did not load."
        setError(message)
        setPersist(true)
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!persist) return
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  }, [settings, persist])

  const visible = useMemo(() => visibleIdeas(report?.ideas ?? [], settings), [report, settings])
  const watches = useMemo(() => visibleIdeas(report?.watch ?? [], settings), [report, settings])

  function toggle(id: FeatureId) {
    setSettings((current) => ({ ...current, features: { ...current.features, [id]: !current.features[id] } }))
  }

  function patch(partial: Partial<Settings>) {
    setSettings((current) => ({ ...current, ...partial }))
  }

  const echo = report?.configEcho
  const jobCap = typeof echo?.maxPremium === "number" ? echo.maxPremium : null
  const capNote =
    jobCap != null && settings.maxPremium > jobCap + 0.001
      ? `Your page cap is ${premium(settings.maxPremium)}. This file was built with a ${premium(jobCap)} cap, so nothing more expensive is here until the next run.`
      : null

  return (
    <div className="mx-auto max-w-5xl px-4 pb-20">
      <a href="#ideas" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-20 focus:bg-card focus:px-3 focus:py-2">
        Skip to ideas
      </a>
      <header className="border-b-2 border-ink pb-6 pt-8">
        <p className="text-xs font-medium uppercase tracking-[0.22em] text-copper">Signals only · no broker</p>
        <h1 className="mt-2 font-serif text-5xl text-ink sm:text-6xl">Options Floor</h1>
        <p className="mt-3 max-w-2xl text-lg leading-relaxed">
          Cheap option ideas for a small account. You place any trade yourself. This page never sends an order and never calls a broker.
        </p>
        <p className="mt-3 text-sm text-muted">
          {report?.runLabel ? `${report.runLabel} · ` : ""}
          {ranAt(report?.generatedAt)}
          {report?.scorecard?.openCount != null ? ` · ${report.scorecard.openCount} open paper idea${report.scorecard.openCount === 1 ? "" : "s"}` : ""}
        </p>
      </header>

      <p className="mt-4 rounded-lg border border-copper/30 bg-[#f8efe6] px-4 py-3 text-sm leading-relaxed">
        {report?.disclaimer ||
          "Options Floor is not a broker and not advice. Options can expire worthless. You can lose the whole premium."}
      </p>

      <nav className="sticky top-0 z-10 -mx-4 mt-4 flex gap-2 overflow-x-auto border-b border-line bg-paper/95 px-4 py-2 backdrop-blur">
        {NAV.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="inline-flex min-h-11 shrink-0 items-center rounded-full px-3 text-sm font-medium text-ink hover:bg-line/70">
            {label}
          </a>
        ))}
        <Button variant="ghost" className="shrink-0" onClick={load}>
          Reload file
        </Button>
      </nav>

      {loading ? <p className="mt-8 text-muted">Reading the latest idea file…</p> : null}
      {error ? (
        <div className="mt-8 rounded-lg border border-put/30 bg-card p-4">
          <p className="font-medium">The idea file did not load.</p>
          <p className="mt-2 text-sm text-muted">{error} If you just opened the project, run the data job once, then reload.</p>
        </div>
      ) : null}
      {report?.banner ? <p className="mt-6 rounded-lg border border-line bg-card px-4 py-3 text-sm leading-relaxed">{report.banner}</p> : null}
      {report?.stale ? <p className="mt-3 text-sm text-muted">Last good file: {ranAt(report.staleFrom)}.</p> : null}

      <FeatureBlock
        id="ideas"
        kicker="Today"
        title="Today's ideas"
        description="Each card names a cheap call or put, the price to aim for, and how much of the account it would use. If the list is empty, the desk would rather wait."
        enabled={settings.features.ideas}
        onToggle={(next) => patch({ features: { ...settings.features, ideas: next } })}
        settings={
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-sm">
              <span className="mb-1 block text-muted">Minimum confidence</span>
              <select
                className="h-11 w-full rounded-md border border-line bg-card px-3"
                value={settings.confidence}
                onChange={(event) => patch({ confidence: event.target.value as Settings["confidence"] })}
              >
                <option value="all">High, medium, and low</option>
                <option value="medium">Medium and high</option>
                <option value="high">High only</option>
              </select>
            </label>
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input type="checkbox" checked={settings.leapsOnly} onChange={(event) => patch({ leapsOnly: event.target.checked })} />
              Only show LEAPS
            </label>
            <label className="flex min-h-11 items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" checked={settings.hideRiskFlags} onChange={(event) => patch({ hideRiskFlags: event.target.checked })} />
              Hide ideas that have a risk note
            </label>
            {capNote ? <p className="text-sm text-muted sm:col-span-2">{capNote}</p> : null}
          </div>
        }
        help={
          <div className="space-y-2">
            <p>A card is a paper plan. At your broker you look up the same expiration and strike, then use a limit order inside the price range. This site cannot do that for you.</p>
            <p>One option contract controls 100 shares. A price of $0.50 costs about $50.</p>
            <p>High, medium, and low are how much the desk agrees. They are not a promise.</p>
          </div>
        }
      >
        {report ? (
          <div className="space-y-4">
            <p className="text-sm text-muted">
              Showing {visible.length} of {(report.ideas ?? []).length} buy instruction{(report.ideas ?? []).length === 1 ? "" : "s"}.
              {report.universe ? ` Looked at ${report.universe.candidates ?? 0} news names, priced ${report.universe.priced ?? 0}, and pulled ${report.universe.chains ?? 0} option chains.` : ""}
            </p>
            {visible.length === 0 ? (
              <p className="rounded-lg border border-dashed border-line px-4 py-6 text-sm leading-relaxed">
                No buy made the cut{(report.ideas ?? []).length ? " with these switches" : ""}. That is a normal result. Waiting is allowed.
              </p>
            ) : (
              visible.map((idea) => <TradeCard key={idea.id} idea={idea} settings={settings} />)
            )}
            {watches.length ? (
              <div className="space-y-3">
                <h3 className="text-xl">Research only</h3>
                <p className="text-sm text-muted">Head Trader was off when this file was built, so these are not buy instructions.</p>
                {watches.map((idea) => <TradeCard key={idea.id} idea={idea} settings={settings} />)}
              </div>
            ) : null}
            {(report.skipped ?? []).length ? (
              <details className="rounded-lg border border-line bg-card px-4 py-3">
                <summary className="min-h-11 text-sm font-medium">Looked at and set aside ({report.skipped!.length})</summary>
                <ul className="mt-3 space-y-2 text-sm">
                  {report.skipped!.map((row, index) => (
                    <li key={`${row.ticker}-${index}`}><span className="font-medium">{row.ticker}.</span> {row.reason}</li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}
      </FeatureBlock>

      <FeatureBlock
        id="mood"
        kicker="The tape"
        title="Market mood"
        description="A calm rising market leans toward calls. A scared market leans toward puts. If the picture is muddy, the desk would rather wait."
        enabled={settings.features.mood}
        onToggle={() => toggle("mood")}
        help={
          <p>
            Mood uses the S&P 500 daily chart and the VIX. Calm means the S&P is above its 10, 50, and 200 day averages and the VIX is under 18.
            Fear means the VIX is 25 or higher, or the S&P is under the longer averages. Anything else is a wait. This is a tilt, not a command.
          </p>
        }
      >
        {report?.regime ? (
          <div className="rounded-xl border border-line bg-card p-5">
            <p className="font-serif text-2xl">{report.regime.title}</p>
            <p className="mt-2 max-w-3xl leading-relaxed">{report.regime.summary}</p>
            <p className="mt-3 text-sm text-muted">
              {report.regime.spyPrice != null ? `S&P 500 ${premium(report.regime.spyPrice)}. ` : ""}
              {report.regime.vix != null ? `VIX ${report.regime.vix.toFixed(1)}.` : "VIX did not load."}
              {report.regime.applied === false ? " Mood was not used for the decisions in this file." : ""}
            </p>
          </div>
        ) : <p className="text-sm text-muted">No mood reading in this file.</p>}
      </FeatureBlock>

      <FeatureBlock
        id="calendar"
        kicker="Dates"
        title="Catalyst calendar"
        description="Dates that can move a stock: earnings, FDA news, court dates, the Fed, and fresh filings."
        enabled={settings.features.calendar}
        onToggle={() => toggle("calendar")}
        settings={<NumberField label="Days ahead" value={settings.calendarDays} step={1} onChange={(calendarDays) => patch({ calendarDays })} />}
        help={
          <p>
            Earnings come from Nasdaq's public calendar for names already in the news. FDA items come from press releases when the meeting calendar page has no readable dates.
            Fed meetings are read from the Fed's public calendar page. A missing source is skipped. The file keeps roughly three weeks of earnings. This slider only hides rows on the page.
          </p>
        }
      >
        <CatalystList report={report} days={settings.calendarDays} />
      </FeatureBlock>

      <FeatureBlock
        id="flow"
        kicker="Clues"
        title="Unusual options flow"
        description="Contracts where today's volume is several times the open interest. Someone traded a lot. That is not a reason to copy them."
        enabled={settings.features.flow}
        onToggle={() => toggle("flow")}
        settings={<NumberField label="Minimum volume divided by open interest" value={settings.flowRatio} step={0.5} onChange={(flowRatio) => patch({ flowRatio })} />}
        help={
          <p>
            The job only downloads option chains for tickers that already have a news catalyst, and only a few expiration dates on each name.
            A quiet contract can still be a fine idea. A loud contract can still be a bad one. Volume under 500 is ignored.
          </p>
        }
      >
        <FlowList report={report} ratio={settings.flowRatio} />
      </FeatureBlock>

      <FeatureBlock
        id="squeeze"
        kicker="Shorts"
        title="Squeeze hunter"
        description="Stocks with heavy short selling and good news. A squeeze is a guess, not a promise."
        enabled={settings.features.squeeze}
        onToggle={() => toggle("squeeze")}
        settings={<NumberField label="Minimum short-sale share of volume (0.45 means 45%)" value={settings.squeezeRatio} step={0.05} onChange={(squeezeRatio) => patch({ squeezeRatio })} />}
        help={
          <p>
            This uses FINRA's free daily short-volume file. It says what share of the day's reported volume was short sales.
            It is not short interest as a percent of the whole company. The job only flags names already in the news, at 45% or higher. Lowering the slider cannot invent rows the file does not have.
          </p>
        }
      >
        <SqueezeList report={report} ratio={settings.squeezeRatio} />
      </FeatureBlock>

      <h2 className="mt-4 font-serif text-3xl">How a card is built</h2>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted">
        Switches here change this page immediately. They do not place trades. The twice-a-day job reads config.json.
        Download that file at the bottom if you want the next run to match what you set here.
      </p>

      <FeatureBlock
        id="chart"
        kicker="Daily chart"
        title="Chart reader"
        description="Daily candles only. The lines on each card are the averages below. Price is the dark line."
        enabled={settings.features.chart}
        onToggle={() => toggle("chart")}
        help={<p>Green 10, orange 20, blue 50, yellow 150, red 200. If a line is missing, there are not enough days yet. No 5-minute charts.</p>}
      >
        <ChartLegend />
      </FeatureBlock>

      <FeatureBlock
        id="cheap"
        kicker="Price cap"
        title="Cheap option finder"
        description="The desk looks for contracts at or under your premium cap. One contract costs the premium times 100."
        enabled={settings.features.cheap}
        onToggle={() => toggle("cheap")}
        settings={<NumberField label="Maximum premium, in dollars" value={settings.maxPremium} step={0.05} onChange={(maxPremium) => patch({ maxPremium })} />}
        help={
          <p>
            The default cap is $0.80, so one contract is $80 or less. Lowering the cap hides pricier cards on this page.
            Raising it above the cap used to build the file does not add new contracts until the next run. Stocks are preferred between $5 and $40. A pricier stock can still appear if a LEAPS contract is under the cap.
          </p>
        }
      >
        <ul className="space-y-2 text-sm">
          {visible.map((idea) => (
            <li key={idea.id}>
              {idea.ticker} {longDate(idea.contract.expiry)} {premium(idea.contract.strike)} {idea.side} is about {premium(idea.entry.mid)}.
            </li>
          ))}
          {visible.length === 0 ? <li className="text-muted">No cards are showing, so there is nothing to price.</li> : null}
        </ul>
      </FeatureBlock>

      <FeatureBlock
        id="payoff"
        kicker="If you hold"
        title="Payoff calculator"
        description="Each card can show what the option is worth at expiration if the stock moves 5, 10, or 20 percent. Before expiration it is often worth more if time is left."
        enabled={settings.features.payoff}
        onToggle={() => toggle("payoff")}
        settings={
          <div className="flex flex-wrap gap-4 text-sm">
            {[5, 10, 20].map((move) => (
              <label key={move} className="flex min-h-11 items-center gap-2">
                <input
                  type="checkbox"
                  checked={settings.payoffMoves.includes(move)}
                  onChange={(event) => {
                    const next = event.target.checked
                      ? [...settings.payoffMoves, move]
                      : settings.payoffMoves.filter((item) => item !== move)
                    patch({ payoffMoves: next })
                  }}
                />
                Plus and minus {move}%
              </label>
            ))}
          </div>
        }
        help={<p>The table uses expiration value only: what the contract is worth on the last day if you exercise the math, not a broker's live quote. No fancy pricing model. A call finishes at zero if the stock is below the strike. A put finishes at zero if the stock is above the strike.</p>}
      >
        <p className="text-sm text-muted">The tables sit on the cards above. An example: a $0.50 call costs about $50. If it expires worthless, the loss is that $50, not more.</p>
      </FeatureBlock>

      <FeatureBlock
        id="underpriced"
        kicker="Rough check"
        title="Underpriced option check"
        description="Compares the option's implied volatility with how much the stock has actually been moving. It is a rough check, not a promise."
        enabled={settings.features.underpriced}
        onToggle={() => toggle("underpriced")}
        help={<p>Implied volatility is the yearly percent of swings baked into the option's price. Realized volatility is how much the stock actually moved over the last month of daily bars. If the option's number is much lower, the card says it looks a bit cheap versus those swings. If it is much higher, you may be paying extra for the news.</p>}
      >
        <ul className="space-y-3 text-sm leading-relaxed">
          {visible.filter((idea) => idea.ivSentence).map((idea) => (
            <li key={idea.id}><span className="font-medium">{idea.ticker}. </span>{idea.ivSentence}</li>
          ))}
          {visible.length === 0 ? <li className="text-muted">No cards are showing.</li> : null}
        </ul>
      </FeatureBlock>

      <FeatureBlock
        id="sizing"
        kicker="Account"
        title="Small bets"
        description="Default account $800. Each idea spends about $40 to $80, and at most 5 ideas stay open. Sell half at a double when you hold 2 or more. With 1 contract, sell it all at a double. Get out if the option loses half."
        enabled={settings.features.sizing}
        onToggle={() => toggle("sizing")}
        settings={
          <div className="grid gap-4 sm:grid-cols-2">
            <NumberField label="Account size, dollars" value={settings.account} step={50} onChange={(account) => patch({ account })} />
            <NumberField label="Minimum spend per idea" value={settings.minSpend} step={5} onChange={(minSpend) => patch({ minSpend })} />
            <NumberField label="Maximum spend per idea" value={settings.maxSpend} step={5} onChange={(maxSpend) => patch({ maxSpend })} />
            <NumberField label="Maximum open paper ideas" value={settings.maxOpen} step={1} onChange={(maxOpen) => patch({ maxOpen })} />
          </div>
        }
        help={
          <p>
            A single idea also stays at or under 10% of the account. The paper scorecard records the size from the job.
            Cards on this page use the numbers you type here, and they say so when the two differ. Checks for the double and the stop happen at the morning and evening runs, not every minute.
          </p>
        }
      >
        <p className="text-sm leading-relaxed">
          {report?.scorecard?.summary || "No scorecard summary yet."} Your page allows up to {settings.maxOpen} open ideas and about {dollars(settings.minSpend)} to {dollars(settings.maxSpend)} each.
        </p>
      </FeatureBlock>

      <div className="mt-10 border-t border-ink pt-8">
        <p className="text-xs font-medium uppercase tracking-[0.16em] text-copper">The desk</p>
        <h2 className="mt-1 font-serif text-3xl">Who votes</h2>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted">
          Each person is a scored rule with a sentence you can read. Yes pushes the idea. No fights it. Pass sits out.
          After a few finished paper trades, a scout who was right more often counts a little more.
        </p>
      </div>
      {DESK.map((agent) => (
        <FeatureBlock
          key={agent.id}
          id={agent.id}
          title={agent.title}
          description={agent.description}
          enabled={settings.features[agent.id]}
          onToggle={() => toggle(agent.id)}
          settings={
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={Boolean(settings.agentYesOnly[agent.id])}
                onChange={(event) => patch({ agentYesOnly: { ...settings.agentYesOnly, [agent.id]: event.target.checked } })}
              />
              Only show ideas this scout voted Yes on
            </label>
          }
          help={<p>{agent.help}</p>}
        >
          <VoteList ideas={[...visible, ...watches]} agentId={agent.id} />
        </FeatureBlock>
      ))}

      <FeatureBlock
        id="scorecard"
        kicker="Paper"
        title="Scorecard"
        description="Every buy instruction is tracked on paper. Later runs check the double, the half-loss, and the last exit date. Finished results change how much each scout's yes vote counts."
        enabled={settings.features.scorecard}
        onToggle={() => toggle("scorecard")}
        help={
          <p>
            This is not a brokerage account. Nothing is bought. Prices are checked when the job runs, about twice a day, so a target can be touched and missed between runs.
            Weights stay even until a scout has a yes vote on at least four finished ideas. You cannot sell half of a single contract.
          </p>
        }
      >
        <ScorecardView report={report} />
      </FeatureBlock>

      <FeatureBlock
        id="review"
        kicker="Week"
        title="Weekly self-review"
        description="A short note about what the paper trades did. It refreshes on Fridays and when a week has passed."
        enabled={settings.features.review}
        onToggle={() => toggle("review")}
        help={<p>The note is a tally. It does not predict next week. If squeeze guesses have lost often enough, the note says they will count less. That part is real: the next run uses the paper record.</p>}
      >
        {report?.weeklyReview ? (
          <div className="rounded-xl border border-line bg-card p-5">
            <p className="text-sm text-muted">Week of {longDate(report.weeklyReview.weekOf)}{report.weeklyReview.paused ? " · paused" : ""}</p>
            <p className="mt-2 leading-relaxed">{report.weeklyReview.note}</p>
          </div>
        ) : <p className="text-sm text-muted">No weekly note yet.</p>}
      </FeatureBlock>

      <section id="save" className="border-t border-line py-8">
        <h2 className="font-serif text-3xl">Save these choices for the job</h2>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed">
          The switches above are stored in this browser. The morning and evening job does not see them until you replace config.json in the project.
          Download the file, then put it in the project folder in place of the old one. The next run follows it.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="default" onClick={() => downloadConfig(settings)}>Download config.json</Button>
          <Button
            onClick={() => {
              localStorage.removeItem(STORAGE_KEY)
              setSettings(settingsFromEcho(report?.configEcho))
            }}
          >
            Match this file again
          </Button>
        </div>
      </section>

      <section id="sources" className="border-t border-line py-8">
        <h2 className="font-serif text-3xl">Where this file came from</h2>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-muted">
          Free sources only. No login and no API key. If a wire is down, it is skipped and the run continues.
          {report?.xPosts ? ` ${report.xPosts}` : ""}
        </p>
        <ul className="mt-4 divide-y divide-line border-y border-line">
          {(report?.sourceHealth ?? []).map((row) => (
            <li key={row.id} className="flex flex-col gap-1 py-3 text-sm sm:flex-row sm:items-baseline sm:justify-between">
              <span className="font-medium">{row.label} · {row.ok ? "Answered" : "Skipped"}</span>
              <span className="text-muted sm:max-w-xl sm:text-right">{row.detail}</span>
            </li>
          ))}
          {(report?.sourceHealth ?? []).length === 0 ? <li className="py-3 text-sm text-muted">No source list in this file.</li> : null}
        </ul>
      </section>

      <footer className="border-t border-ink py-8 text-sm leading-relaxed text-muted">
        <p className="font-medium text-ink">A few words</p>
        <p className="mt-2">A call makes money only if the stock rises enough before the date. A put makes money only if it falls enough. The strike is the price in the contract. The expiration is the last day it exists. The premium is what you pay. You can lose all of it. You cannot lose more than the premium on a long call or put bought for cash.</p>
        <p className="mt-3">Options Floor does not send alerts, texts, or emails. Open the page when you want to look.</p>
      </footer>
    </div>
  )
}

function visibleIdeas(ideas: Idea[], settings: Settings): Idea[] {
  return ideas.filter((idea) => {
    if (settings.features.cheap && idea.ask > settings.maxPremium + 1e-9) return false
    if (settings.leapsOnly && !idea.contract.isLeap) return false
    if (settings.confidence === "high" && idea.confidence !== "High") return false
    if (settings.confidence === "medium" && idea.confidence === "Low") return false
    if (settings.hideRiskFlags && (idea.riskFlags?.length ?? 0) > 0) return false
    for (const id of FEATURE_IDS) {
      if (!settings.agentYesOnly[id] || !settings.features[id]) continue
      const vote = idea.agents?.find((item) => item.id === id)
      if (!vote || vote.vote !== "yes") return false
    }
    return true
  })
}

function NumberField({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (value: number) => void }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-muted">{label}</span>
      <Input
        type="number"
        step={step}
        value={Number.isFinite(value) ? value : 0}
        onChange={(event) => {
          const next = Number(event.target.value)
          if (Number.isFinite(next)) onChange(next)
        }}
      />
    </label>
  )
}

function CatalystList({ report, days }: { report: Report | null; days: number }) {
  const rows = (report?.catalysts ?? [])
    .filter((row) => {
      const span = daySpan(row.date)
      return span >= -2 && span <= days
    })
    .sort((a, b) => {
      const rank = (span: number) => (span >= 0 ? span : 100 + Math.abs(span))
      return rank(daySpan(a.date)) - rank(daySpan(b.date))
    })
  const shown = rows.slice(0, 12)
  if (!shown.length) return <p className="text-sm text-muted">No dates in this window.</p>
  return (
    <div className="space-y-3">
      {rows.length > shown.length ? <p className="text-sm text-muted">Showing {shown.length} of {rows.length} dates. Raise “days ahead” in Settings if you want more.</p> : null}
    <ul className="space-y-3">
      {shown.map((row, index) => (
        <li key={`${row.date}-${row.title}-${index}`} className="rounded-lg border border-line bg-card px-4 py-3">
          <p className="text-xs uppercase tracking-wide text-copper">{row.kind} · {longDate(row.date)}</p>
          <p className="mt-1 font-medium">{row.title}</p>
          {row.plain && row.plain !== row.title ? <p className="mt-1 text-sm text-muted">{row.plain}</p> : null}
          {row.url ? <a className="mt-1 inline-flex min-h-11 items-center text-sm text-copper underline" href={row.url} target="_blank" rel="noreferrer">Source</a> : null}
        </li>
      ))}
    </ul>
    </div>
  )
}

function FlowList({ report, ratio }: { report: Report | null; ratio: number }) {
  const rows = (report?.flow ?? []).filter((row) => row.ratio >= ratio)
  if (!rows.length) return <p className="text-sm text-muted">No unusual volume in this file at that bar.</p>
  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <li key={`${row.contract}-${row.ratio}`} className="rounded-lg border border-line bg-card px-4 py-3 text-sm leading-relaxed">
          <p className="font-medium">{row.ticker} · {row.side} · {premium(row.strike)} · {longDate(row.expiry)}</p>
          <p className="mt-1 text-muted">{row.note}</p>
        </li>
      ))}
    </ul>
  )
}

function SqueezeList({ report, ratio }: { report: Report | null; ratio: number }) {
  const rows = (report?.squeezes ?? []).filter((row) => row.shortRatio >= ratio)
  if (!rows.length) return <p className="text-sm text-muted">No squeeze guesses cleared the bar.</p>
  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <li key={row.ticker} className="rounded-lg border border-line bg-card px-4 py-3 text-sm leading-relaxed">
          <p className="font-medium">{row.ticker} · short volume {Math.round(row.shortRatio * 100)}%</p>
          <p className="mt-1">{row.note}</p>
          {row.url ? <a className="mt-1 inline-flex min-h-11 items-center text-copper underline" href={row.url} target="_blank" rel="noreferrer">{row.headline || "Headline"}</a> : null}
        </li>
      ))}
    </ul>
  )
}

function VoteList({ ideas, agentId }: { ideas: Idea[]; agentId: string }) {
  const rows = ideas.flatMap((idea) => {
    const vote = idea.agents?.find((item) => item.id === agentId)
    return vote ? [{ ticker: idea.ticker, vote }] : []
  })
  if (!rows.length) return <p className="text-sm text-muted">No vote from this scout on the cards that are showing.</p>
  return (
    <ul className="space-y-2 text-sm">
      {rows.map((row) => (
        <li key={`${row.ticker}-${row.vote.vote}`}>
          <span className="font-medium">{row.ticker} · {row.vote.vote === "yes" ? "Yes" : row.vote.vote === "no" ? "No" : "Pass"}. </span>
          {row.vote.reason}
        </li>
      ))}
    </ul>
  )
}

function ScorecardView({ report }: { report: Report | null }) {
  const book = report?.scorecard
  if (!book) return <p className="text-sm text-muted">No scorecard in this file.</p>
  return (
    <div className="space-y-4">
      <p className="leading-relaxed">{book.summary}</p>
      {book.paused ? <p className="text-sm text-muted">Tracking is paused in this file.</p> : null}
      <div>
        <h3 className="text-xl">Open</h3>
        {(book.open ?? []).length === 0 ? <p className="mt-2 text-sm text-muted">No open paper ideas.</p> : (
          <ul className="mt-2 space-y-2 text-sm">
            {(book.open ?? []).map((trade) => (
              <li key={trade.id} className="rounded-lg border border-line bg-card px-4 py-3">
                <p className="font-medium">{trade.ticker} · {trade.action} · {trade.remainingContracts} left</p>
                <p className="mt-1 text-muted">
                  In at {trade.entry != null ? premium(trade.entry) : "?"}
                  {trade.lastMark != null ? `, last seen ${premium(trade.lastMark)}` : ""}.
                  Leave by {longDate(trade.lastExitDate)}.
                  {trade.halfClosed ? " Sold half at a double. The rest is still open." : ""}
                  {trade.checkNote ? ` ${trade.checkNote}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h3 className="text-xl">Finished</h3>
        {(book.closed ?? []).length === 0 ? <p className="mt-2 text-sm text-muted">Nothing has finished yet. Weights stay even until they do.</p> : (
          <ul className="mt-2 space-y-2 text-sm">
            {(book.closed ?? []).map((trade) => (
              <li key={trade.id} className="rounded-lg border border-line bg-card px-4 py-3">
                <p className="font-medium">{trade.ticker} · {outcomePlain(trade.outcome || "")} · {dollars(trade.realizedPnl || 0)}</p>
                <p className="mt-1 text-muted">Closed {longDate(trade.closedAt)}.</p>
              </li>
            ))}
          </ul>
        )}
      </div>
      {(book.agents ?? []).length ? (
        <div>
          <h3 className="text-xl">Scout weights</h3>
          <ul className="mt-2 space-y-2 text-sm">
            {book.agents!.map((agent) => (
              <li key={agent.id}><span className="font-medium">{agent.name}.</span> {agent.plain}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
