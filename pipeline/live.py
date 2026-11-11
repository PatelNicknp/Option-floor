"""Download free, no-login sources and hand a bundle to the engine."""

from __future__ import annotations

import re
import urllib.parse
from datetime import date, datetime, timedelta, timezone

from pipeline.http_client import SEC_UA, HttpClient, attempt
from pipeline.models import Bundle, EarningsRow, Equity, NewsItem
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


# Nasdaq's API refuses requests that do not look like they come from its own web page.
NASDAQ_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/market-activity/earnings",
}

FDA_RSS = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml"
FDA_GOOGLE = "site:fda.gov (approves OR approval OR warning OR recall OR authorizes OR clears) when:7d"

# Free press-release wires. Small companies publish here first, often with "(NASDAQ: ABC)" in the text.
WIRE_FEEDS = [
    ("prnewswire", "PR Newswire", [
        "https://www.prnewswire.com/rss/news-releases-list.rss",
        "https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss",
        "https://www.prnewswire.com/rss/health-latest-news/health-latest-news-list.rss",
    ], "site:prnewswire.com when:1d"),
    ("globenewswire", "GlobeNewswire", [
        "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies",
    ], "site:globenewswire.com when:1d"),
    ("businesswire", "Business Wire", [
        "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEF9YXA==",
    ], "site:businesswire.com when:1d"),
]
FEED_HEADERS = {"Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}


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
    open_tickers = sorted({str(trade.get("ticker")) for trade in (open_trades or []) if trade.get("ticker")})
    quick: dict[str, float] = {}
    if config.get("priceFirst", True):
        quick = _quick_prices(client, ranked[: int(config["priceScanTickers"])] + open_tickers, symbols, health)
    extra = _yahoo_headlines(client, _headline_targets(ranked, quick, config), health)
    if extra:
        _attach_tickers(extra, index)
        items.extend(extra)
        items = [item for item in _dedupe(items) if not is_noise_headline(item.title)]
        ranked = [ticker for ticker, _score in rank_tickers(items, now_ts=now.timestamp())]
        if config.get("priceFirst", True):
            missing = [ticker for ticker in ranked[: int(config["priceScanTickers"])] if ticker not in quick]
            if missing:
                quick.update(_quick_prices(client, missing, symbols, None))

    earnings = attempt(health, "nasdaq_earnings", "Nasdaq earnings calendar", lambda: _earnings(client, int(config["earningsDays"])), [])
    short_ratios = attempt(health, "finra_short", "FINRA short volume", lambda: _finra(client), {})
    spy = attempt(health, "spy", "S&P 500 daily prices", lambda: _chart(client, "SPY"), None)
    vix_equity = attempt(health, "vix", "VIX", lambda: _chart(client, "^VIX"), None)

    price_skips: dict[str, float] = {}
    if quick:
        quote_list, price_skips = price_first_list(ranked, quick, config)
    else:
        quote_list = [ticker for ticker in ranked if ticker in symbols][: int(config["maxCandidateTickers"])]
        # A matched ticker should already be in the symbol map. Keep unknowns only if Yahoo can price them.
        if len(quote_list) < min(8, len(ranked)):
            for ticker in ranked:
                if ticker not in quote_list:
                    quote_list.append(ticker)
                if len(quote_list) >= int(config["maxCandidateTickers"]):
                    break
    quotes = _quotes(client, quote_list, symbols, health)
    if not earnings and int(config.get("earningsBackupTickers") or 0) > 0:
        earnings = _earnings_backup(client, quotes, symbols, config, now.date(), health)
    _apply_earnings(quotes, earnings, now.date())
    chain_symbols = _chain_symbols(quotes, ranked, config)
    print("Option chains for: " + (", ".join(chain_symbols) if chain_symbols else "(none)"), flush=True)
    chains = _chains(client, chain_symbols, symbols, quotes, now.date(), health)
    stock_marks = {ticker: quick[ticker] for ticker in open_tickers if ticker in quick}
    marks = _marks(client, open_trades or [], chains, symbols, health, stock_marks)
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
        stock_marks=stock_marks,
        price_skips=price_skips,
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

    items.extend(_fda(client, health))
    items.extend(_wires(client, health))

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


def _marks(
    client: HttpClient,
    trades: list[dict],
    chains: dict,
    symbols: dict,
    health: list[dict],
    stock_marks: dict[str, float] | None = None,
) -> dict[str, float]:
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
            mid, stock = _mark_one(client, yahoo, symbol, trade.get("expiry"))
            if stock and stock_marks is not None and trade["ticker"] not in stock_marks:
                stock_marks[trade["ticker"]] = stock
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


def _mark_one(client: HttpClient, yahoo_symbol: str, contract_symbol: str, expiry: str | None) -> tuple[float | None, float | None]:
    safe = urllib.parse.quote(yahoo_symbol, safe="")
    base = f"https://query1.finance.yahoo.com/v7/finance/options/{safe}"
    urls = [base]
    if expiry:
        when = date.fromisoformat(expiry)
        stamp = int(datetime(when.year, when.month, when.day, tzinfo=timezone.utc).timestamp())
        urls.append(f"{base}?date={stamp}")
    stock: float | None = None
    for url in urls:
        _expirations, contracts, quote = parse_yahoo_options(client.yahoo_json(url))
        if stock is None:
            stock = _positive((quote or {}).get("regularMarketPrice"))
        found = _find_contract(contracts, contract_symbol)
        if found is not None and found.mid > 0:
            return found.mid, stock
    return None, stock


def _positive(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


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
            payload = client.get_json(url, headers=NASDAQ_HEADERS)
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
            # Exchange tags from a press release are kept only when the symbol list knows them.
            item.tickers = [ticker for ticker in item.tickers if ticker in index.symbols]
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


def _google_feed(client: HttpClient, query: str, source: str, limit: int) -> list[NewsItem]:
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en"
    _, body = client.get(url)
    return parse_feed(body, source, limit=limit)


def _fda(client: HttpClient, health: list[dict]) -> list[NewsItem]:
    """FDA press releases. The official feed first, then FDA pages found through Google News."""
    try:
        _, body = client.get(FDA_RSS, headers=FEED_HEADERS)
        found = parse_feed(body, "fda", limit=25)
        if found:
            health.append({"id": "fda", "label": "FDA", "ok": True, "detail": f"{len(found)} items from the FDA press-release feed"})
            return found
        direct_error = "the feed was empty"
    except Exception as exc:  # noqa: BLE001
        direct_error = str(exc)
    try:
        found = _google_feed(client, FDA_GOOGLE, "fda", 30)
        for item in found:
            item.kind = "fda"
        health.append(
            {
                "id": "fda",
                "label": "FDA",
                "ok": bool(found),
                "detail": (f"{len(found)} fda.gov items through Google News. The FDA feed itself did not answer ({direct_error})."[:300]),
            }
        )
        return found
    except Exception as exc:  # noqa: BLE001
        health.append({"id": "fda", "label": "FDA", "ok": False, "detail": f"Skipped. FDA feed: {direct_error}. Backup: {exc}"[:300]})
        return []


def _wires(client: HttpClient, health: list[dict]) -> list[NewsItem]:
    items: list[NewsItem] = []
    for source_id, label, urls, google_query in WIRE_FEEDS:
        found: list[NewsItem] = []
        errors: list[str] = []
        for url in urls:
            try:
                _, body = client.get(url, headers=FEED_HEADERS)
                found.extend(parse_feed(body, source_id, limit=60))
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        via = "direct"
        if not found:
            try:
                found = _google_feed(client, google_query, source_id, 60)
                via = "google"
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Google News backup: {exc}")
        found = [item for item in _dedupe(found) if not is_noise_headline(item.title)]
        for item in found:
            item.tickers = wire_tickers(item.summary)
        if found:
            detail = f"{len(found)} releases"
            if via == "google":
                detail += " through Google News (the wire's own feed did not answer)"
        else:
            detail = "Skipped. " + ("; ".join(errors) or "No releases.")
        health.append({"id": source_id, "label": label, "ok": bool(found), "detail": detail[:300]})
        items.extend(found)
    return items


_EXCHANGE_TAG = re.compile(
    r"\((?:NASDAQ|Nasdaq|NYSE|Nyse|NYSE American|NYSE MKT|NYSE Arca|Cboe|CBOE|AMEX|Amex)(?:\s*(?:GS|GM|CM|Global Select|Global Market|Capital Market))?\s*[:\-]\s*([A-Za-z]{1,5}(?:[.\-][A-Za-z])?)\b"
)


def wire_tickers(text: str) -> list[str]:
    """Exchange tags in a press release body, like "(NASDAQ: ABC)". Title matching still runs after."""
    found: list[str] = []
    for match in _EXCHANGE_TAG.finditer(text or ""):
        symbol = match.group(1).upper().replace("-", ".")
        if symbol not in found:
            found.append(symbol)
    return found[:3]


def _quick_prices(client: HttpClient, tickers: list[str], symbols: dict, health: list[dict] | None) -> dict[str, float]:
    """One cheap Yahoo call per 20 tickers, so the job knows which names are in range before pulling charts."""
    wanted: list[str] = []
    for ticker in tickers:
        if ticker and ticker not in wanted:
            wanted.append(ticker)
    prices: dict[str, float] = {}
    errors = 0
    for start in range(0, len(wanted), 20):
        batch = wanted[start : start + 20]
        lookup = {(symbols[ticker].yahoo if ticker in symbols else ticker.replace(".", "-")): ticker for ticker in batch}
        url = (
            "https://query1.finance.yahoo.com/v8/finance/spark?symbols="
            + ",".join(urllib.parse.quote(symbol, safe="^-") for symbol in lookup)
            + "&range=1d&interval=1d"
        )
        try:
            payload = client.get_json(url)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  quick price skip: {exc}", flush=True)
            continue
        prices.update(parse_spark(payload, lookup))
    if health is not None:
        batches = (len(wanted) + 19) // 20
        health.append(
            {
                "id": "yahoo_quick_prices",
                "label": "Quick price check",
                "ok": bool(prices) or not wanted,
                "detail": f"Priced {len(prices)} of {len(wanted)} news names before pulling charts."
                + (f" {errors} of {batches} batches did not answer." if errors else ""),
            }
        )
    return prices


def parse_spark(payload: dict, lookup: dict[str, str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    if not isinstance(payload, dict):
        return prices
    for yahoo_symbol, row in payload.items():
        if not isinstance(row, dict):
            continue
        closes = [value for value in (row.get("close") or []) if isinstance(value, (int, float)) and value > 0]
        price = closes[-1] if closes else _positive(row.get("chartPreviousClose"))
        if price:
            prices[lookup.get(yahoo_symbol, yahoo_symbol)] = float(price)
    return prices


def price_first_list(ranked: list[str], quick: dict[str, float], config: dict) -> tuple[list[str], dict[str, float]]:
    """Order daily-chart pulls: in range first, then cheap-LEAPS stretch names, in news-rank order.

    Names priced outside both bands are left out and reported. Names with no quick price
    are kept at the end so a gap in the quick check does not hide them.
    """
    limit = int(config["maxCandidateTickers"])
    low, high = float(config["priceMin"]), float(config["priceMax"])
    stretch_on = bool(config.get("allowHigherPriceIfCheapLeap"))
    stretch_high = float(config.get("higherPriceMax") or high)
    in_band: list[str] = []
    stretch: list[str] = []
    unknown: list[str] = []
    skips: dict[str, float] = {}
    for ticker in ranked:
        price = quick.get(ticker)
        if price is None:
            unknown.append(ticker)
        elif low <= price <= high:
            in_band.append(ticker)
        elif stretch_on and high < price <= stretch_high:
            stretch.append(ticker)
        else:
            skips[ticker] = price
    chosen = (in_band + stretch + unknown)[:limit]
    return chosen, skips


def _headline_targets(ranked: list[str], quick: dict[str, float], config: dict) -> list[str]:
    """Spend the Yahoo headline lookups on names that can actually become ideas."""
    batch = int(config["headlineBatch"])
    if not quick:
        return ranked[:batch]
    chosen, _skips = price_first_list(ranked, quick, {**config, "maxCandidateTickers": batch})
    return chosen


def _earnings_backup(client: HttpClient, quotes: dict, symbols: dict, config: dict, today: date, health: list[dict]) -> list:
    """When the Nasdaq calendar is blocked, read each in-range name's next earnings date from Yahoo."""
    low, high = float(config["priceMin"]), float(config["priceMax"])
    wanted = [ticker for ticker, equity in quotes.items() if low <= equity.price <= high][: int(config["earningsBackupTickers"])]
    rows = []
    errors = 0
    for ticker in wanted:
        yahoo = symbols[ticker].yahoo if ticker in symbols else ticker.replace(".", "-")
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(yahoo, safe='')}?modules=calendarEvents"
        try:
            payload = client.yahoo_json(url)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  earnings backup skip {ticker}: {exc}", flush=True)
            continue
        when = parse_calendar_events(payload)
        if when is not None and when >= today:
            name = symbols[ticker].name if ticker in symbols else ticker
            rows.append(EarningsRow(symbol=ticker, name=name, when=when))
    ok = bool(wanted) and errors < len(wanted)
    health.append(
        {
            "id": "earnings_backup",
            "label": "Earnings dates (Yahoo backup)",
            "ok": ok or not wanted,
            "detail": (
                f"Checked {len(wanted) - errors} of {len(wanted)} in-range names. {len(rows)} have an upcoming date."
                if wanted
                else "No in-range names to check."
            ),
        }
    )
    return rows


def parse_calendar_events(payload: dict) -> date | None:
    try:
        result = (payload.get("quoteSummary") or {}).get("result") or []
        dates = ((result[0].get("calendarEvents") or {}).get("earnings") or {}).get("earningsDate") or []
    except (AttributeError, IndexError, TypeError):
        return None
    found = []
    for row in dates:
        raw = row.get("raw") if isinstance(row, dict) else None
        if isinstance(raw, (int, float)):
            found.append(datetime.fromtimestamp(int(raw), tz=timezone.utc).date())
    return min(found) if found else None
