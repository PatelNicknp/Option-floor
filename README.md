# Options Floor

A paper desk for cheap option ideas. It reads free news first, then looks at daily charts and option chains, and writes exact **buy call** or **buy put** instructions for a small account.

It does **not** place trades, connect to a broker, or send alerts. You decide whether to type anything at your own brokerage.

The default account is **$800**. Each idea spends about **$40 to $80**. At most **5** paper ideas stay open. The premium cap is **$0.80** a share ($80 a contract). Sell half at a double when you hold two or more contracts. With one contract, sell the whole thing at a double. Get out if the option loses half its value.

## Look at the page

```bash
cd web
npm install
npm run dev
```

Open [http://127.0.0.1:4317](http://127.0.0.1:4317).

The page reads `web/public/data/latest.json`. Switches on the page change what you see in this browser. They do not change the next scheduled run until you replace `config.json`. Use **Download config.json** at the bottom of the page, then put that file in the project folder.

## Build a new idea file

From the project folder:

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest
python3 -m pipeline.run
```

The job writes:

- `data/latest.json` — the page the site shows
- `data/scorecard.json` — open and finished paper trades
- copies of both under `web/public/data/`

If a news wire, Yahoo, or a filing feed does not answer, that source is skipped and the run continues. If most sources fail and nothing new qualifies, the page keeps the last good ideas and says they are not fresh.

## Publish it

This is a static site plus a scheduled job, the GitHub Pages style.

1. Put the project in a Git repository and push it.
2. In the repository settings, turn on **Pages** and deploy from the `main` branch, folder **`/docs`**.
3. Turn on **Actions**. The workflow `.github/workflows/options-floor.yml` runs the tests, rebuilds the idea file, and rebuilds the site.
4. The public address will look like `https://YOUR-NAME.github.io/YOUR-REPO/`.

You can also run the job by hand from the Actions tab (“Run workflow”).

### When it runs

Weekdays, twice:

| Clock | Eastern Standard Time | Eastern Daylight Time |
| --- | --- | --- |
| 15:15 UTC | 10:15 AM | 11:15 AM |
| 23:30 UTC | 6:30 PM | 7:30 PM |

GitHub schedules use UTC and do not follow daylight saving. In the summer the runs are one hour later in New York. Change the two `cron` lines in the workflow if you want them exact in both seasons. A run at any other hour is labeled “Manual check.”

## What the desk does

News comes first. The job reads Google News, Yahoo Finance headlines, SEC 8-K filings, the Federal Register, the White House, the Federal Reserve, FDA press releases, and Congress feeds. It keeps roughly the best few dozen company names that have a real catalyst, prefers stocks around **$5 to $40**, and only then asks Yahoo for daily prices and option chains. A pricier stock can still appear when a LEAPS contract is under the premium cap.

Press-release wires come in too: PR Newswire, GlobeNewswire, and Business Wire. A release that says "(NASDAQ: ABC)" is tied to that ticker. If a wire's own feed refuses the request, the job reads that wire's releases through Google News instead. The FDA feed works the same way: the official press-release feed first, then fda.gov pages through Google News.

**Price first.** Before pulling any daily charts, one quick Yahoo call per 20 names checks the price of every news name. Names inside `priceMin` to `priceMax` go first, then cheap-LEAPS names up to `higherPriceMax`. Big names outside the range are listed as skipped instead of using up chart and option-chain pulls. Turn this off with `"priceFirst": false`.

**Probably good or bad news.** With `"acceptProbableNews": true` (the default), a headline that only leans good or bad can still become an idea, but the Head Trader never stamps it above **Low** confidence and the card says so. Set it to `false` to go back to clear news only.

If the Nasdaq earnings calendar refuses the request, the job reads the next earnings date for each in-range name from Yahoo (`earningsBackupTickers`, default 20).

**Open trades.** Every run saves the option price (and the stock price) for each open paper trade in `markHistory`. The Scorecard shows each open trade's cost, value now, gain or loss in dollars and percent, a small price line since entry, a bar from the half-loss exit to the double, days held and days left, and one plain sentence. Trades opened before this history existed start with the two prices that were really stored (entry and last check). Their entry stock price shows as "Not recorded".

Nasdaq Trader symbol files supply the stock list. FINRA’s daily short-volume file supplies the squeeze check. No source needs a login or an API key.

Each idea shows the ticker, buy call or buy put, the exact contract, a limit-price range, dollars to spend, the take-profit, the stop, the last exit date, a plain reason, a news link, every scout’s vote, and a confidence stamp.

The scouts are rules with a written vote, not hidden models:

- News Scout
- Policy & Politics Scout
- Sentiment Scout
- Chart Reader (daily candles only; 10 green, 20 orange, 50 blue, 150 yellow, 200 red)
- Options Picker
- Risk Checker
- Devil’s Advocate
- Head Trader

Also on the page: a catalyst calendar, the cheap-option cap, an expiration payoff table, unusual volume versus open interest, a squeeze list, an implied-volatility check, an option price checker (type any US ticker and get Cheap, Fair, or Expensive), small-bet sizing, a paper scorecard, and a weekly note.

The scorecard is how the desk “learns.” After a scout has voted yes on at least four finished paper ideas, a better record counts a little more and a worse record counts a little less. Squeeze and “cheap versus recent swings” tags do the same. Until then every vote counts evenly.

## Tests

```bash
python3 -m pytest
cd web && npm test
```

The research tests do not use the network. They cover sizing, payoff, headline matching, the option picker, paper exits, and a full idea built from fake prices.

## Limits

- This is not advice. Options can expire worthless. You can lose the whole premium.
- Quotes are delayed. The job looks about twice a day, so a double or a stop can be touched and missed between runs.
- Yahoo sometimes refuses a symbol. That name is skipped.
- X posts are not read. There is no stable no-login feed.
- Short interest here is FINRA’s **daily short-sale volume**, not short interest as a percent of the whole company.
- The payoff table is the value **at expiration**, not a live price. A contract with time left is often worth more than the table before that day.
- The job prices up to 36 news names and downloads option chains for up to 18 of them, a few expirations each, so it does not hammer Yahoo. It does not see the whole options market.
- Earnings dates come from Nasdaq’s public calendar and from Yahoo when that field is present. FDA meeting dates appear when a free page actually includes them. Press releases are the fallback.
- Generic words such as “United States,” “industrial,” or “children” are not treated as a company. A publisher name at the end of a Google headline (“Yahoo Finance”) is ignored. Law-firm ads (“investors have opportunity to lead a securities fraud lawsuit”) are ignored. A policy note becomes a trade only when the company itself is named in a specific way.
- Learning weights do nothing useful until several paper ideas have finished. That takes time, because exits are a double, a half loss, or the last exit date.
