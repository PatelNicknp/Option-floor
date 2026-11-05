"""Download free, no-login sources and hand a bundle to the engine."""

from __future__ import annotations

import urllib.parse
from datetime import date, datetime, timedelta, timezone

from pipeline.http_client import SEC_UA, HttpClient, attempt
from pipeline.models import Bundle, Equity, NewsItem
from pipeline.parsers import (
    earnings_date_from_quote,
    parse_fomc_dates,
    parse_federal_register,
    parse_feed,
    parse_finra_short_volume,
    parse_nasdaq_earnings,
    parse_nasdaq_listed,
    parse_other_listed,
    parse_sec_tickers,
    parse_yahoo_chart,
    parse_yahoo_options,
)
from pipeline.textutil import build_index, is_noise_headline, match_tickers, strip_publisher

GOOGLE = [
    'stock (earnings OR "raises guidance" OR "cuts guidance") when:2d',
    'FDA (approval OR "advisory committee" OR "phase 3") stock when:3d',
    "stock (upgrade OR downgrade OR buyout OR merger OR acquisition) when:2d",
    'stock (lawsuit OR investigation OR "SEC charges" OR offering) when:2d',
    'stocks (tariff OR Congress OR "White House" OR "Federal Reserve") when:2d',
]


def build_bundle(client: HttpClient, config: dict, now: datetime, open_trades: list[dict] | None = None) -> Bundle:
    health: list[dict] = []
    symbols = _symbols(client, health)
    print(f"Symbols: {len(symbols)}", flush=True)
    index = build_index(symbols)
    items = _headlines(client, health)
    _attach_tickers(items, index)
    print(f"Headlines: {len(items)}", flush=True)

    from pipeline.textutil import rank_tickers

    ranked = [ticker for ticker, _score in rank_tickers(items, now_ts=now.timestamp())]
    extra = _yahoo_headlines(client, ranked[: int(config["headlineBatch"])], health)
    if extra:
        _attach_tickers(extra, index)
        items.extend(extra)
        items = [item for item in _dedupe(items) if not is_noise_headline(item.title)]
        ranked = [ticker for ticker, _score in rank_tickers(items, now_ts=now.timestamp())]

    earnings = attempt(health, "nasdaq_earnings", "Nasdaq earnings calendar", lambda: _earnings(client, int(config["earningsDays"])), [])
    short_ratios = attempt(health, "finra_short", "FINRA short volume", lambda: _finra(client), {})
    spy = attempt(health, "spy", "S&P 500 daily prices", lambda: _chart(client, "SPY"), None)
    vix_equity = attempt(health, "vix", "VIX", lambda: _chart(client, "^VIX"), None)

    quote_list = [ticker for ticker in ranked if ticker in symbols][: int(config["maxCandidateTickers"])]
    # A matched ticker should already be in the symbol map. Keep unknowns only if Yahoo can price them.
    if len(quote_list) < min(8, len(ranked)):
        for ticker in ranked:
            if ticker not in quote_list:
                quote_list.append(ticker)
            if len(quote_list) >= int(config["maxCandidateTickers"]):
                break
    quotes = _quotes(client, quote_list, symbols, health)
    _apply_earnings(quotes, earnings, now.date())
    chain_symbols = _chain_symbols(quotes, ranked, config)
    print("Option chains for: " + (", ".join(chain_symbols) if chain_symbols else "(none)"), flush=True)
    chains = _chains(client, chain_symbols, symbols, quotes, now.date(), health)
    marks = _marks(client, open_trades or [], chains, symbols, health)
    vix = vix_equity.price if isinstance(vix_equity, Equity) else None
    spy_closes = spy.closes if isinstance(spy, Equity) else None
    return Bundle(
        now=now,
        items=items,
        symbols=symbols,
        quotes=quotes,
        chains=chains,
        short_ratios=short_ratios if isinstance(short_ratios, dict) else {},
        earnings=earnings if isinstance(earnings, list) else [],
        spy_closes=spy_closes,
        vix=vix,
        source_health=health,
        marks=marks,
    )


def _symbols(client: HttpClient, health: list[dict]) -> dict:
    symbols = {}
    sources = [
        ("nasdaq_listed", "Nasdaq symbol list", "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", parse_nasdaq_listed),
        ("other_listed", "NYSE and other symbol list", "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", parse_other_listed),
    ]
    for source_id, label, url, parser in sources:
        try:
            _, body = client.get(url)
            found = parser(body.decode("utf-8", "replace"))
            added = 0
            for symbol, info in found.items():
                if symbol not in symbols:
                    symbols[symbol] = info
                    added += 1
            health.append({"id": source_id, "label": label, "ok": True, "detail": f"{added} stocks"})
        except Exception as exc:  # noqa: BLE001
            health.append({"id": source_id, "label": label, "ok": False, "detail": f"Skipped. {exc}"[:300]})
    try:
        payload = client.get_json("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": SEC_UA, "Accept": "application/json"})
        found = parse_sec_tickers(payload)
        added = 0
        for symbol, info in found.items():
            if symbol not in symbols:
                symbols[symbol] = info
                added += 1
        health.append({"id": "sec_tickers", "label": "SEC company list", "ok": True, "detail": f"Added {added} names that were not already listed"})
    except Exception as exc:  # noqa: BLE001
        health.append({"id": "sec_tickers", "label": "SEC company list", "ok": False, "detail": f"Skipped. {exc}"[:300]})
    return symbols


def _headlines(client: HttpClient, health: list[dict]) -> list[NewsItem]:
    items: list[NewsItem] = []
    google_rows: list[NewsItem] = []
    google_errors = 0
    for query in GOOGLE:
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
        try:
            _, body = client.get(url)
            google_rows.extend(parse_feed(body, "google", limit=20))
        except Exception as exc:  # noqa: BLE001
            google_errors += 1
            print(f"  Google News skip: {exc}", flush=True)
    if google_rows or google_errors < len(GOOGLE):
        health.append({"id": "google_news", "label": "Google News", "ok": bool(google_rows), "detail": f"{len(google_rows)} headlines"})
    else:
        health.append({"id": "google_news", "label": "Google News", "ok": False, "detail": "Skipped. No Google News feeds answered."})
    items.extend(google_rows)

    feeds = [
        ("sec_filings", "SEC filings", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&owner=include&count=40&output=atom", {"User-Agent": SEC_UA}, "sec"),
        ("fed", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", None, "fed"),
        ("whitehouse", "White House", "https://www.whitehouse.gov/news/feed/", None, "whitehouse"),
        ("whitehouse_actions", "White House actions", "https://www.whitehouse.gov/presidential-actions/feed/", None, "whitehouse"),
        ("fda", "FDA", "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml", None, "fda"),
        ("congress", "Congress", "https://www.congress.gov/rss/presented-to-president.xml", None, "congress"),
        ("congress_bills", "Congress bills", "https://www.congress.gov/rss/most-viewed-bills.xml", None, "congress"),
    ]
    for source_id, label, url, headers, source in feeds:
        try:
            _, body = client.get(url, headers=headers)
            found = parse_feed(body, source, limit=25)
            items.extend(found)
            health.append({"id": source_id, "label": label, "ok": True, "detail": f"{len(found)} items"})
        except Exception as exc:  # noqa: BLE001
            health.append({"id": source_id, "label": label, "ok": False, "detail": f"Skipped. {exc}"[:300]})

    def register():
        payload = client.get_json("https://www.federalregister.gov/api/v1/documents.json?per_page=25&order=newest")
        return parse_federal_register(payload)

    items.extend(attempt(health, "federal_register", "Federal Register", register, []))

    def fomc():
        _, body = client.get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
        found = parse_fomc_dates(body.decode("utf-8", "replace"), datetime.now().year)
        if not found:
            raise RuntimeError("The Fed calendar page had no readable meeting dates.")
        return found

    items.extend(attempt(health, "fomc", "Fed meeting calendar", fomc, []))
    return [item for item in _dedupe(items) if not is_noise_headline(item.title)]


def _yahoo_headlines(client: HttpClient, tickers: list[str], health: list[dict]) -> list[NewsItem]:
    if not tickers:
        health.append({"id": "yahoo_headlines", "label": "Yahoo Finance headlines", "ok": True, "detail": "No tickers to look up yet."})
        return []
    found: list[NewsItem] = []
    errors = 0
    for start in range(0, len(tickers), 5):
        batch = tickers[start : start + 5]
        yahoo_batch = [ticker.replace(".", "-") for ticker in batch]
        url = (
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s="
            + ",".join(urllib.parse.quote(ticker) for ticker in yahoo_batch)
            + "&region=US&lang=en-US"
        )
        try:
            _, body = client.get(url)
            found.extend(parse_feed(body, "yahoo", limit=30))
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  Yahoo headlines skip: {exc}", flush=True)
    health.append(
        {
            "id": "yahoo_headlines",
            "label": "Yahoo Finance headlines",
            "ok": bool(found) or errors == 0,
            "detail": f"{len(found)} headlines" if found else "Skipped. Yahoo headlines did not answer.",
        }
    )
    if not found and errors:
        health[-1]["ok"] = False
    return found


def _quotes(client: HttpClient, tickers: list[str], symbols: dict, health: list[dict]) -> dict:
    quotes = {}
    failed: list[str] = []
    for ticker in tickers:
        yahoo = symbols[ticker].yahoo if ticker in symbols else ticker.replace(".", "-")
        try:
            equity = _chart(client, yahoo)
            if equity is None or equity.price <= 0:
                failed.append(ticker)
                continue
            equity.symbol = ticker
            if ticker in symbols and symbols[ticker].name:
                equity.name = symbols[ticker].name
            quotes[ticker] = equity
        except Exception as exc:  # noqa: BLE001
            failed.append(ticker)
            print(f"  price skip {ticker}: {exc}", flush=True)
    detail = f"Loaded {len(quotes)} of {len(tickers)} daily charts."
    if failed:
        detail += " Skipped " + ", ".join(failed[:8]) + "."
    if not tickers:
        detail = "No tickers selected, so no prices were requested."
    health.append({"id": "yahoo_prices", "label": "Yahoo daily prices", "ok": bool(quotes) or not tickers, "detail": detail})
    return quotes


def _chains(client: HttpClient, tickers: list[str], symbols: dict, quotes: dict, today: date, health: list[dict]) -> dict:
    chains = {}
    failed: list[str] = []
    for ticker in tickers:
        yahoo = symbols[ticker].yahoo if ticker in symbols else ticker.replace(".", "-")
        try:
            contracts, quote = _chain(client, yahoo, today)
            if not contracts:
                failed.append(ticker)
                continue
            chains[ticker] = contracts
            equity = quotes.get(ticker)
            when = earnings_date_from_quote(quote)
            if equity is not None and equity.earnings_date is None and when is not None and when >= today:
                equity.earnings_date = when
            long_name = quote.get("longName") or quote.get("shortName")
            if equity is not None and long_name and (not equity.name or equity.name == ticker):
                equity.name = str(long_name)
        except Exception as exc:  # noqa: BLE001
            failed.append(ticker)
            print(f"  options skip {ticker}: {exc}", flush=True)
    detail = f"Loaded option chains for {len(chains)} of {len(tickers)} tickers."
    if failed:
        detail += " Skipped " + ", ".join(failed[:8]) + "."
    if not tickers:
        detail = "No tickers in the price range, so no option chains were requested."
    health.append({"id": "yahoo_options", "label": "Yahoo option chains", "ok": bool(chains) or not tickers, "detail": detail})
    return chains


def _marks(client: HttpClient, trades: list[dict], chains: dict, symbols: dict, health: list[dict]) -> dict[str, float]:
    marks: dict[str, float] = {}
    needed = [trade for trade in trades if trade.get("status") == "open" and trade.get("contractSymbol")]
    if not needed:
        return marks
    checked = 0
    for trade in needed:
        symbol = trade["contractSymbol"]
        found = _find_contract(chains.get(trade["ticker"]) or [], symbol)
        if found is not None and found.mid > 0:
            marks[symbol] = found.mid
            checked += 1
            continue
        yahoo = symbols[trade["ticker"]].yahoo if trade["ticker"] in symbols else str(trade["ticker"]).replace(".", "-")
        try:
            mid = _mark_one(client, yahoo, symbol, trade.get("expiry"))
            if mid:
                marks[symbol] = mid
                checked += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  mark skip {symbol}: {exc}", flush=True)
    health.append(
        {
            "id": "paper_marks",
            "label": "Open paper trades",
            "ok": checked == len(needed),
            "detail": f"Checked the price on {checked} of {len(needed)} open paper ideas.",
        }
    )
    return marks


def _chart(client: HttpClient, yahoo_symbol: str):
    safe = urllib.parse.quote(yahoo_symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{safe}?range=2y&interval=1d&includePrePost=false"
    try:
        payload = client.get_json(url)
    except Exception:
        payload = client.yahoo_json(url)
    equity = parse_yahoo_chart(payload, yahoo_symbol)
    if equity is None:
        raise RuntimeError(f"No candles for {yahoo_symbol}")
    return equity


def _chain(client: HttpClient, yahoo_symbol: str, today: date):
    safe = urllib.parse.quote(yahoo_symbol, safe="")
    base = f"https://query1.finance.yahoo.com/v7/finance/options/{safe}"
    payload = client.yahoo_json(base)
    expirations, contracts, quote = parse_yahoo_options(payload)
    wanted = _pick_expirations(expirations, today)
    chosen = list(contracts)
    seen = {stamp for stamp in expirations if _stamp_date(stamp) == (contracts[0].expiry if contracts else None)}
    for stamp in wanted:
        if stamp in seen:
            continue
        more_payload = client.yahoo_json(f"{base}?date={stamp}")
        _, more, _ = parse_yahoo_options(more_payload)
        chosen.extend(more)
        seen.add(stamp)
    # Keep a contract once.
    unique = {}
    for contract in chosen:
        unique[contract.symbol] = contract
    return list(unique.values()), quote


def _pick_expirations(stamps: list[int], today: date) -> list[int]:
    parsed = []
    for stamp in stamps:
        when = _stamp_date(stamp)
        if when is None:
            continue
        days = (when - today).days
        if days >= 5:
            parsed.append((days, stamp))
    parsed.sort()

    def first(low: int, high: int) -> int | None:
        for days, stamp in parsed:
            if low <= days <= high:
                return stamp
        return None

    chosen = []
    for stamp in (first(7, 55), first(56, 180), first(270, 900)):
        if stamp and stamp not in chosen:
            chosen.append(stamp)
    if not chosen and parsed:
        chosen.append(parsed[0][1])
    return chosen


def _stamp_date(stamp: int) -> date | None:
    try:
        return datetime.fromtimestamp(int(stamp), tz=timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None


def _find_contract(contracts, symbol: str):
    for contract in contracts:
        if contract.symbol == symbol:
            return contract
    return None


def _mark_one(client: HttpClient, yahoo_symbol: str, contract_symbol: str, expiry: str | None) -> float | None:
    safe = urllib.parse.quote(yahoo_symbol, safe="")
    base = f"https://query1.finance.yahoo.com/v7/finance/options/{safe}"
    urls = [base]
    if expiry:
        when = date.fromisoformat(expiry)
        stamp = int(datetime(when.year, when.month, when.day, tzinfo=timezone.utc).timestamp())
        urls.append(f"{base}?date={stamp}")
    for url in urls:
        _expirations, contracts, _quote = parse_yahoo_options(client.yahoo_json(url))
        found = _find_contract(contracts, contract_symbol)
        if found is not None and found.mid > 0:
            return found.mid
    return None


def _finra(client: HttpClient) -> dict[str, float]:
    last_error: Exception | None = None
    today = date.today()
    for offset in range(8):
        day = today - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        url = f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{day.strftime('%Y%m%d')}.txt"
        try:
            _, body = client.get(url)
            ratios = parse_finra_short_volume(body.decode("utf-8", "replace"))
            if ratios:
                print(f"FINRA short volume file {day.isoformat()} ({len(ratios)} symbols)", flush=True)
                return ratios
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(last_error or "No FINRA short-volume file")


def _earnings(client: HttpClient, days: int) -> list:
    rows = []
    errors = 0
    schedule = _business_days(date.today(), max(1, days))
    for day in schedule:
        url = f"https://api.nasdaq.com/api/calendar/earnings?date={day.isoformat()}"
        try:
            payload = client.get_json(url, headers={"Accept": "application/json, text/plain, */*"})
            rows.extend(parse_nasdaq_earnings(payload, day))
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  earnings skip {day.isoformat()}: {exc}", flush=True)
    if errors == len(schedule) and not rows:
        raise RuntimeError("Earnings calendar did not answer.")
    return rows


def _business_days(start: date, count: int) -> list[date]:
    days = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _chain_symbols(quotes: dict, ranked: list[str], config: dict) -> list[str]:
    primary = []
    stretch = []
    seen = set()
    for ticker in ranked:
        equity = quotes.get(ticker)
        if equity is None or ticker in seen:
            continue
        seen.add(ticker)
        price = equity.price
        if config["priceMin"] <= price <= config["priceMax"]:
            primary.append(ticker)
        elif config.get("allowHigherPriceIfCheapLeap") and config["priceMax"] < price <= config["higherPriceMax"]:
            stretch.append(ticker)
    limit = int(config["maxChainTickers"])
    chosen = primary[:limit]
    room = limit - len(chosen)
    if room > 0:
        chosen.extend(stretch[:room])
    return chosen


def _apply_earnings(quotes: dict, earnings: list, today: date) -> None:
    upcoming: dict[str, date] = {}
    for row in earnings or []:
        if row.when >= today and row.symbol not in upcoming:
            upcoming[row.symbol] = row.when
    for symbol, equity in quotes.items():
        if symbol in upcoming:
            equity.earnings_date = upcoming[symbol]
        elif equity.earnings_date is not None and equity.earnings_date < today:
            equity.earnings_date = None


def _attach_tickers(items: list[NewsItem], index) -> None:
    for item in items:
        if item.tickers:
            continue
        item.tickers = match_tickers(strip_publisher(item.title), index)


def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
    seen = set()
    kept = []
    for item in items:
        key = " ".join(item.title.lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept
