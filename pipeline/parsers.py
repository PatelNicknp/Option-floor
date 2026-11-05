"""Turn raw downloads into symbols, headlines, candles, and option quotes."""

from __future__ import annotations

import email.utils
import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from pipeline.models import EarningsRow, Equity, NewsItem, OptionContract, SymbolInfo
from pipeline.textutil import infer_kind, strip_html

ET_ZONE = None


def _zone():
    global ET_ZONE
    if ET_ZONE is None:
        from zoneinfo import ZoneInfo

        ET_ZONE = ZoneInfo("America/New_York")
    return ET_ZONE


def yahoo_symbol(symbol: str) -> str:
    return symbol.upper().replace(".", "-")


def _keep_name(name: str) -> bool:
    lowered = f" {name.lower()} "
    if any(word in lowered for word in ("warrant", "preferred", "rights", "debenture", "notes due")):
        return False
    if re.search(r"\b(etf|etn|fund|funds)\b", lowered):
        return False
    if "exchange traded" in lowered or "exchange-traded" in lowered or "commodity index" in lowered:
        return False
    return True


def parse_nasdaq_listed(text: str) -> dict[str, SymbolInfo]:
    out: dict[str, SymbolInfo] = {}
    for line in text.splitlines()[1:]:
        if not line or line.startswith("File Creation"):
            continue
        parts = line.split("|")
        if len(parts) < 7:
            continue
        symbol, name, _category, test_issue, status, _lot, etf = parts[:7]
        symbol = symbol.strip().upper()
        if test_issue.strip() == "Y" or etf.strip() == "Y":
            continue
        if status.strip() not in {"N", ""}:
            continue
        if not re.fullmatch(r"[A-Z]{1,5}", symbol) or not _keep_name(name):
            continue
        out[symbol] = SymbolInfo(symbol=symbol, name=name.strip(), yahoo=yahoo_symbol(symbol))
    return out


def parse_other_listed(text: str) -> dict[str, SymbolInfo]:
    out: dict[str, SymbolInfo] = {}
    for line in text.splitlines()[1:]:
        if not line or line.startswith("File Creation"):
            continue
        parts = line.split("|")
        if len(parts) < 7:
            continue
        symbol, name, _exchange, _cqs, etf, _lot, test_issue = parts[:7]
        symbol = symbol.strip().upper()
        if etf.strip() == "Y" or test_issue.strip() == "Y":
            continue
        if not re.fullmatch(r"[A-Z][A-Z.]{0,5}", symbol) or not _keep_name(name):
            continue
        out[symbol] = SymbolInfo(symbol=symbol, name=name.strip(), yahoo=yahoo_symbol(symbol))
    return out


def parse_sec_tickers(payload: dict) -> dict[str, SymbolInfo]:
    out: dict[str, SymbolInfo] = {}
    rows = payload.values() if isinstance(payload, dict) else payload
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("ticker") or "").upper().strip()
        name = str(row.get("title") or "").strip()
        if not re.fullmatch(r"[A-Z.]{1,6}", symbol) or not name or not _keep_name(name):
            continue
        out[symbol] = SymbolInfo(symbol=symbol, name=name, yahoo=yahoo_symbol(symbol))
    return out


def parse_finra_short_volume(text: str) -> dict[str, float]:
    totals: dict[str, list[float]] = {}
    for line in text.splitlines()[1:]:
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 5:
            continue
        symbol = parts[1].upper()
        try:
            short_volume = float(parts[2])
            total_volume = float(parts[4])
        except ValueError:
            continue
        if total_volume <= 0 or not symbol:
            continue
        bucket = totals.setdefault(symbol, [0.0, 0.0])
        bucket[0] += short_volume
        bucket[1] += total_volume
    return {symbol: values[0] / values[1] for symbol, values in totals.items() if values[1] > 0}


def _text(node, name: str) -> str:
    child = node.find(name)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError, IndexError):
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def parse_feed(content: bytes, source: str, limit: int = 30) -> list[NewsItem]:
    root = ET.fromstring(content)
    items: list[NewsItem] = []
    atom = "{http://www.w3.org/2005/Atom}"
    entries = root.findall(".//item")
    atom_entries = root.findall(f".//{atom}entry")
    for node in entries:
        title = strip_html(_text(node, "title"))
        link = _text(node, "link")
        summary = strip_html(_text(node, "description"))
        published = _parse_date(_text(node, "pubDate") or _text(node, "date"))
        if not title:
            continue
        items.append(
            NewsItem(
                title=title,
                url=link,
                source=source,
                published=published,
                summary=summary[:500],
                kind=infer_kind(source, f"{title} {summary}"),
            )
        )
        if len(items) >= limit:
            return items
    for node in atom_entries:
        title = strip_html(_child_text(node, f"{atom}title"))
        link = ""
        for link_node in node.findall(f"{atom}link"):
            href = link_node.attrib.get("href") or ""
            rel = link_node.attrib.get("rel") or "alternate"
            if rel == "alternate" and href:
                link = href
                break
        summary = strip_html(_child_text(node, f"{atom}summary") or _child_text(node, f"{atom}content"))
        published = _parse_date(_child_text(node, f"{atom}updated") or _child_text(node, f"{atom}published"))
        if not title:
            continue
        items.append(
            NewsItem(
                title=title,
                url=link,
                source=source,
                published=published,
                summary=summary[:500],
                kind=infer_kind(source, f"{title} {summary}"),
            )
        )
        if len(items) >= limit:
            break
    return items


def _child_text(node, path: str) -> str:
    child = node.find(path)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def parse_federal_register(payload: dict, limit: int = 20) -> list[NewsItem]:
    keywords = (
        "securit", "bank", "fda", "drug", "energy", "tariff", "interest rate",
        "federal reserve", "commission", "market", "oil", "defense", "defence",
    )
    items: list[NewsItem] = []
    for row in payload.get("results") or []:
        title = strip_html(str(row.get("title") or ""))
        abstract = strip_html(str(row.get("abstract") or ""))
        blob = f"{title} {abstract}".lower()
        if not any(word in blob for word in keywords):
            continue
        published = _parse_date(str(row.get("publication_date") or "") + "T12:00:00+00:00")
        items.append(
            NewsItem(
                title=title,
                url=str(row.get("html_url") or ""),
                source="federal_register",
                published=published,
                summary=abstract[:500],
                kind="policy",
            )
        )
        if len(items) >= limit:
            break
    return items


def parse_fomc_dates(html_text: str, year: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }
    year_at = [(match.start(), int(match.group(1))) for match in re.finditer(r"(20\d{2})", html_text)]
    for match in re.finditer(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})",
        html_text,
        re.I,
    ):
        month = months[match.group(1).lower()]
        day = int(match.group(2))
        year_for_date = year
        for position, found_year in year_at:
            if position < match.start():
                year_for_date = found_year
            else:
                break
        try:
            when = date(year_for_date, month, day)
        except ValueError:
            continue
        items.append(
            NewsItem(
                title=f"FOMC meeting around {when.isoformat()}",
                url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                source="fed",
                published=datetime(when.year, when.month, when.day, 18, tzinfo=timezone.utc),
                summary="Scheduled Federal Reserve meeting. Rates and the tone of the statement can move the whole market.",
                kind="fed",
            )
        )
    unique: list[NewsItem] = []
    seen: set[str] = set()
    for item in items:
        if item.title in seen:
            continue
        seen.add(item.title)
        unique.append(item)
    return unique[:30]


_EXPIRY_RE = re.compile(r"(\d{6})[CP]\d{8}$")


def expiry_from_symbol(symbol: str) -> date | None:
    match = _EXPIRY_RE.search(symbol or "")
    if not match:
        return None
    return datetime.strptime(match.group(1), "%y%m%d").date()


def parse_yahoo_chart(payload: dict, fallback_symbol: str = "") -> Equity | None:
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return None
    row = result[0]
    meta = row.get("meta") or {}
    instrument = str(meta.get("instrumentType") or "EQUITY").upper()
    if instrument not in {"EQUITY", "ETF", "INDEX"}:
        return None
    timestamps = row.get("timestamp") or []
    indicators = row.get("indicators") or {}
    quote = (indicators.get("quote") or [{}])[0]
    adj = (indicators.get("adjclose") or [{}])[0].get("adjclose")
    closes = adj or quote.get("close") or []
    bars_map: dict[date, float] = {}
    zone = _zone()
    for stamp, close in zip(timestamps, closes):
        if close is None:
            continue
        when = datetime.fromtimestamp(int(stamp), tz=timezone.utc).astimezone(zone).date()
        bars_map[when] = float(close)
    bars = sorted(bars_map.items())
    if not bars:
        return None
    price = meta.get("regularMarketPrice")
    price_value = float(price) if price not in (None, "") else bars[-1][1]
    if price_value <= 0:
        return None
    symbol = str(meta.get("symbol") or fallback_symbol)
    name = str(meta.get("shortName") or meta.get("longName") or symbol)
    return Equity(symbol=symbol, name=name, price=price_value, bars=bars)


def parse_yahoo_options(payload: dict) -> tuple[list[int], list[OptionContract], dict]:
    result = (payload.get("optionChain") or {}).get("result") or []
    if not result:
        error = (payload.get("optionChain") or {}).get("error")
        raise RuntimeError(error or "Empty option chain")
    row = result[0]
    expirations = [int(item) for item in row.get("expirationDates") or []]
    quote = row.get("quote") or {}
    contracts: list[OptionContract] = []
    for block in row.get("options") or []:
        for side, key in (("call", "calls"), ("put", "puts")):
            for raw in block.get(key) or []:
                symbol = str(raw.get("contractSymbol") or "")
                expiry = expiry_from_symbol(symbol)
                if expiry is None and raw.get("expiration"):
                    expiry = datetime.fromtimestamp(int(raw["expiration"]), tz=timezone.utc).date()
                if expiry is None or "strike" not in raw:
                    continue
                contracts.append(
                    OptionContract(
                        symbol=symbol,
                        side=side,
                        strike=float(raw["strike"]),
                        expiry=expiry,
                        bid=float(raw.get("bid") or 0),
                        ask=float(raw.get("ask") or 0),
                        last=float(raw.get("lastPrice") or 0),
                        volume=float(raw.get("volume") or 0),
                        oi=float(raw.get("openInterest") or 0),
                        iv=float(raw["impliedVolatility"]) if raw.get("impliedVolatility") not in (None, "") else None,
                    )
                )
    return expirations, contracts, quote


def earnings_date_from_quote(quote: dict) -> date | None:
    stamp = quote.get("earningsTimestamp") or quote.get("earningsTimestampStart")
    if not stamp:
        return None
    try:
        return datetime.fromtimestamp(int(stamp), tz=_zone()).date()
    except (TypeError, ValueError, OSError):
        return None


def parse_nasdaq_earnings(payload: dict, when: date) -> list[EarningsRow]:
    data = payload.get("data") or {}
    rows = data.get("rows") or []
    out: list[EarningsRow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        cap = _money(row.get("marketCap"))
        out.append(EarningsRow(symbol=symbol, name=str(row.get("name") or symbol), when=when, market_cap=cap))
    return out


def _money(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    text = str(value).replace("$", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_json_bytes(content: bytes) -> dict:
    return json.loads(content.decode("utf-8", "replace"))
