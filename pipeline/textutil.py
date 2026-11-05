"""Headline matching, tone, and catalyst words. No paid news API."""

from __future__ import annotations

import html
import re
from collections import defaultdict

from pipeline.models import NewsItem, SymbolInfo

GENERIC_NAME_TOKENS = {
    "common", "stock", "stocks", "shares", "share", "ordinary", "american", "depositary",
    "ads", "adr", "class", "series", "incorporated", "inc", "corp", "corporation",
    "company", "companies", "co", "ltd", "plc", "holdings", "holding", "group", "the",
    "and", "of", "limited", "trust", "fund", "funds", "etf", "warrant", "warrants",
    "unit", "units", "preferred", "preference", "acquisition", "reit", "sa", "nv", "ag",
    "lp", "llc", "com", "new", "without", "par", "value", "american",
}

# First words that are too generic to identify a company by themselves.
STOP_FIRST = {
    "states", "united", "industrial", "national", "general", "first", "american",
    "global", "capital", "financial", "energy", "health", "power", "digital",
    "international", "pacific", "western", "southern", "northern", "eastern",
    "advanced", "technology", "technologies", "resources", "partners", "properties",
    "services", "solutions", "systems", "industries", "materials", "products",
    "group", "royal", "standard", "universal", "world", "community", "public",
    "federal", "central", "commercial", "investment", "investors", "income",
    "equity", "market",     "water", "oil", "gas", "steel", "bank", "banks", "new",
    "asia", "europe", "africa", "india", "china", "japan", "korea", "canada",
    "mexico", "latin", "once", "third", "quarter", "weekly", "generic", "therapy",
    "surgery", "coast", "farm", "upon", "array", "partners", "partner", "update",
    "results", "financial", "shares", "cancer", "women", "patch", "hormone",
    "finance", "change", "daily", "following", "could", "agents",
    "children", "therapeutics", "fair", "value", "heart", "valve",
    "quantum", "computing",
}

GENERIC_BIGRAMS = {
    "quantum computing",
    "artificial intelligence",
    "machine learning",
    "real estate",
    "electric vehicle",
}

# Common words that are also real company names. A hint word must sit in the same headline.
BRANDS = {"apple", "ford", "visa"}

ACRONYMS = {
    "FDA", "SEC", "FED", "FOMC", "NYSE", "NASDAQ", "CEO", "CFO", "EPS", "ETF", "IPO",
    "USA", "GDP", "CPI", "IRS", "DOJ", "OTC", "LLC", "INC", "LTD", "PLC", "USD", "AI",
    "US", "UK", "EU", "DD", "PR", "AM", "PM", "ET", "EST", "EDT", "YTD", "ATH",
    "Q1", "Q2", "Q3", "Q4", "IPO", "DNA", "RNA", "HIV", "HPV", "RRP", "NIH",
    "CDC", "WHO", "IRA", "FDA",
}

DENY_SINGLE = {
    "target", "national", "first", "general", "american", "united", "capital",
    "energy", "bank", "global", "financial", "health", "power", "digital",
}

COMMON = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "at", "by", "with",
    "from", "as", "is", "are", "was", "were", "be", "been", "being", "it", "this",
    "that", "these", "those", "not", "no", "never", "but", "if", "then", "so", "than",
    "too", "very", "just", "new", "old", "high", "low", "big", "small", "first", "last",
    "next", "week", "day", "today", "tomorrow", "stock", "stocks", "share", "shares",
    "market", "markets", "price", "prices", "trade", "trading", "trader", "earnings",
    "news", "report", "reports", "company", "companies", "group", "fund", "funds", "up",
    "down", "over", "under", "after", "before", "above", "into", "about", "says", "said",
    "say", "will", "would", "can", "could", "may", "might", "all", "are", "now", "on",
    "it", "for", "you", "your", "our", "their", "his", "her", "its", "out", "has", "have",
    "had", "who", "what", "when", "where", "why", "how", "more", "most", "some", "any",
    "apple", "target", "ford", "visa", "key", "block", "snap", "gap", "best", "good",
    "real", "live", "play", "national", "federal", "reserve", "white", "house",
    "congress", "senate", "court", "indian", "chinese", "american", "european",
    "british", "japanese", "global", "pacific", "general", "first", "united", "capital",
    "financial", "digital", "health", "energy", "power", "water", "gold", "silver",
    "oil", "bank", "true", "ever", "life", "hope", "main", "post", "cash", "rate",
    "bill", "act", "law", "call", "put", "buy", "sell", "open", "close", "well", "fast",
    "next", "work", "love", "grow", "nice", "big", "see", "two", "can", "top", "run",
    "save", "talk", "wall", "street", "reuters", "associated", "press", "bloomberg",
    "shares", "futures", "higher", "lower", "rise", "fall", "today", "yesterday",
}

HINTS = {
    "beat", "beats", "guidance", "outlook", "upgrade", "downgrade", "approval", "approves",
    "approved", "unveils", "launches", "announces", "reports", "posts", "names", "appoints",
    "agrees", "receives", "wins", "win", "soars", "soar", "surge", "surges", "jumps", "jump",
    "plunges", "plunge", "tumbles", "tumble", "falls", "fall", "rises", "rise", "gains",
    "gain", "rally", "rallies", "sinks", "sink", "recall", "lawsuit", "offering", "buyback",
    "partnership", "merger", "acquisition", "acquires", "acquired", "contract", "awarded",
    "recall", "recalls", "recalled",
    "bankruptcy", "fraud", "subpoena", "miss", "misses", "cuts", "raises", "raised",
}

BULL_PHRASES = [
    (re.compile(r"\braises (its |the |full-year |fy\d{2,4} )?guidance\b", re.I), 3),
    (re.compile(r"\braises (its |the )?outlook\b", re.I), 3),
    (re.compile(r"\bguidance (raise|raised|hike|hiked)\b", re.I), 3),
    (re.compile(r"\bbeats?\b", re.I), 2),
    (re.compile(r"\btops estimates\b", re.I), 2),
    (re.compile(r"\bupgrades?\b|\bupgraded\b", re.I), 2),
    (re.compile(r"\bprice target (raised|hiked|increased|boosted)\b", re.I), 2),
    (re.compile(r"\bfda approves?\b|\bfda approval\b", re.I), 3),
    (re.compile(r"\bbuybacks?\b|\bshare repurchase\b", re.I), 2),
    (re.compile(r"\bpartnership\b|\bpartners with\b", re.I), 1),
    (re.compile(r"\bawarded\b|\bwins contract\b|\bcontract win\b", re.I), 2),
    (re.compile(r"\brecord revenue\b", re.I), 2),
    (re.compile(r"\bsoars?\b|\bsurges?\b|\bjumps?\b", re.I), 1),
    (re.compile(r"\bbreakthrough\b", re.I), 2),
    (re.compile(r"\bacquires?\b|\bacquired\b|\bmerger\b|\bbuyout\b", re.I), 1),
]

BEAR_PHRASES = [
    (re.compile(r"\bcuts guidance\b|\bguidance cut\b|\blowers outlook\b|\bcuts outlook\b", re.I), 3),
    (re.compile(r"\bmiss(?:es|ed)?\b", re.I), 2),
    (re.compile(r"\bdowngrades?\b|\bdowngraded\b", re.I), 2),
    (re.compile(r"\bprice target (cut|lowered|reduced)\b", re.I), 2),
    (re.compile(r"\blawsuit\b|\binvestigation\b|\bprobe\b", re.I), 2),
    (re.compile(r"\bsubpoena\b|\bsec charges\b|\bfraud\b", re.I), 3),
    (re.compile(r"\boffering\b|\bdilution\b|\bregistered direct\b", re.I), 2),
    (re.compile(r"\brecall\b", re.I), 2),
    (re.compile(r"\bbankruptcy\b|\bchapter 11\b", re.I), 3),
    (re.compile(r"\blayoffs?\b", re.I), 2),
    (re.compile(r"\bplunges?\b|\btumbles?\b|\bsinks?\b", re.I), 1),
    (re.compile(r"\bwarning letter\b|\bcomplete response\b", re.I), 2),
    (re.compile(r"\bclinical hold\b", re.I), 3),
    (re.compile(r"\bdelay(?:s|ed)?\b", re.I), 1),
]

POS_WORDS = {
    "beat", "beats", "growth", "strong", "record", "upgrade", "upgraded", "approved",
    "approval", "win", "wins", "surge", "soar", "jump", "jumps", "bullish", "optimistic",
    "raises", "raised", "partnership", "buyback", "profit", "profits", "breakthrough",
    "outperform", "boost", "boosts", "soars", "surges",
}
NEG_WORDS = {
    "miss", "misses", "weak", "downgrade", "downgraded", "lawsuit", "fraud", "probe",
    "investigation", "offering", "dilution", "recall", "bankruptcy", "layoff", "layoffs",
    "plunge", "tumble", "warning", "delay", "delays", "bearish", "subpoena", "default",
    "crash", "sinks", "concern", "concerns", "missed", "plunges", "tumbles",
}

POLICY_RULES = [
    (re.compile(r"rate cut|cuts interest rates|lower(?:ing)? rates|dovish", re.I),
     ("bank", "banks", "financial", "mortgage", "homebuilder", "lending", "reit"),
     1,
     "A rate-cut headline often helps lenders and housing-related companies. This is a rough sector guess."),
    (re.compile(r"rate hike|raises interest rates|higher for longer|hawkish", re.I),
     ("bank", "banks", "financial", "mortgage", "homebuilder", "lending", "reit"),
     -1,
     "A higher-rate headline often pressures lenders and housing-related companies. This is a rough sector guess."),
    (re.compile(r"\bfda approves?\b|drug approval|approves the drug", re.I),
     ("therapeutics", "biosciences", "pharma", "biotech", "biopharma", "laboratories"),
     1,
     "An FDA approval headline can help drug makers. This is a rough sector guess."),
    (re.compile(r"complete response|clinical hold|fda reject|rejected the drug", re.I),
     ("therapeutics", "biosciences", "pharma", "biotech", "biopharma", "laboratories"),
     -1,
     "A negative FDA headline can hurt drug makers. This is a rough sector guess."),
    (re.compile(r"\btariffs?\b|trade war", re.I),
     ("manufacturing", "steel", "auto", "semiconductor", "motors"),
     -1,
     "Tariff headlines can raise costs or block sales. This is a rough sector guess."),
    (re.compile(r"\bndaa\b|pentagon|defense bill|defence bill", re.I),
     ("defense", "defence", "aerospace", "missile"),
     1,
     "A defense-bill headline can help aerospace and defense companies. This is a rough sector guess."),
    (re.compile(r"drilling ban|restricts drilling|pipeline blocked", re.I),
     ("petroleum", "energy", "oil", "drilling", "pipeline"),
     -1,
     "Limits on drilling can hurt oil and pipeline companies. This is a rough sector guess."),
    (re.compile(r"drilling permit|approves the pipeline|pipeline approval", re.I),
     ("petroleum", "energy", "oil", "drilling", "pipeline"),
     1,
     "A drilling or pipeline approval can help energy companies. This is a rough sector guess."),
    (re.compile(r"medicare drug|drug price negotiation|drug pricing", re.I),
     ("pharma", "therapeutics", "biosciences", "biotech"),
     -1,
     "Drug-pricing rules can pressure pharma companies. This is a rough sector guess."),
]


def strip_html(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def clean_name_tokens(name: str) -> list[str]:
    return [token for token in tokenize(name) if token not in GENERIC_NAME_TOKENS and not token.isdigit() and len(token) > 1]


class NameIndex:
    def __init__(self) -> None:
        self.by_bigram: dict[str, str] = {}
        self.by_token: dict[str, list[tuple[str, frozenset[str]]]] = defaultdict(list)
        self.symbols: set[str] = set()

    def add(self, symbol: str, name: str) -> None:
        symbol = symbol.upper()
        self.symbols.add(symbol)
        tokens = clean_name_tokens(name)
        if not tokens:
            return
        blob = frozenset(tokens)
        first = tokens[0]
        bucket = self.by_token[first]
        if not any(existing == symbol for existing, _ in bucket):
            bucket.append((symbol, blob))
        if len(tokens) >= 2:
            bigram = f"{tokens[0]} {tokens[1]}"
            current = self.by_bigram.get(bigram)
            if current is None:
                self.by_bigram[bigram] = symbol
            elif current != symbol:
                self.by_bigram[bigram] = ""

    def add_symbol_alias(self, symbol: str) -> None:
        token = symbol.lower().replace("-", "").replace(".", "")
        if len(token) < 3 or token in COMMON:
            return
        bucket = self.by_token.get(token) or []
        if any(existing != symbol for existing, _ in bucket):
            return
        if any(existing == symbol for existing, _ in bucket):
            return
        self.by_token[token].append((symbol, frozenset({token})))


def build_index(symbols: dict[str, SymbolInfo]) -> NameIndex:
    index = NameIndex()
    for info in symbols.values():
        index.add(info.symbol, info.name)
    return index


_NOISE = re.compile(
    r"investors have opportunity|lead plaintiff|class action|shareholder alert|"
    r"reminds investors|encourages investors|law firm investigates|securities fraud lawsuit",
    re.I,
)


def is_noise_headline(title: str) -> bool:
    """Law-firm ads show up every day and are not a company catalyst."""
    return bool(_NOISE.search(title or ""))


def _styled_short_name(text: str, token: str) -> bool:
    """True for names like SoFi. Title-case words such as Fair do not count."""
    if len(token) >= 5:
        return True
    for match in re.finditer(rf"\b({re.escape(token)})\b", text, re.I):
        raw = match.group(1)
        if any(character.isupper() for character in raw[1:]):
            return True
    return False


def strip_publisher(title: str) -> str:
    """Google News appends ' - Publisher'. Keep SEC titles, which contain digits."""
    if " - " not in title:
        return title
    head, tail = title.rsplit(" - ", 1)
    if any(character.isdigit() for character in tail):
        return title
    if 2 <= len(tail) <= 45 and len(head) > 12:
        return head
    return title


def match_tickers(text: str, index: NameIndex) -> list[str]:
    if not text or not index.symbols:
        return []
    tokens = tokenize(text)
    hits: dict[str, int] = defaultdict(int)
    for match in re.finditer(r"\$([A-Za-z]{1,5})\b", text):
        symbol = match.group(1).upper()
        if symbol in index.symbols:
            hits[symbol] += 5
    for match in re.finditer(r"\b([A-Z]{2,5})\b", text):
        symbol = match.group(1)
        lowered = symbol.lower()
        if symbol in ACRONYMS or lowered in COMMON or lowered in HINTS or lowered in STOP_FIRST:
            continue
        if symbol in index.symbols:
            hits[symbol] += 5
    for match in re.finditer(r"\((?:NASDAQ|NYSE|AMEX|Nasdaq|Nyse)\s*[:\-]\s*([A-Za-z.\-]{1,6})\)", text):
        symbol = match.group(1).upper().replace(".", "-")
        if symbol in index.symbols:
            hits[symbol] += 5
    significant = [token for token in tokens if token not in GENERIC_NAME_TOKENS]
    for index_in_tokens, (left, right) in enumerate(zip(significant, significant[1:])):
        if left == "price" and right == "target":
            continue
        if {left, right} <= {"united", "states", "new", "york", "hong", "kong"}:
            continue
        phrase = f"{left} {right}"
        if phrase in GENERIC_BIGRAMS and not re.search(
            r"\b(inc|corp|corporation|incorporated|company|ltd)\b", text, re.I
        ):
            continue
        symbol = index.by_bigram.get(phrase)
        if symbol:
            hits[symbol] += 4
    has_hint = any(token in HINTS for token in tokens)
    for position, token in enumerate(tokens):
        if token == "target" and position > 0 and tokens[position - 1] == "price":
            continue
        if token in STOP_FIRST or token in DENY_SINGLE:
            continue
        candidates = index.by_token.get(token) or []
        if len(candidates) != 1:
            continue
        symbol, _blob = candidates[0]
        if token in COMMON:
            if token in BRANDS and has_hint and len(token) >= 4:
                hits[symbol] += 3
        elif _styled_short_name(text, token):
            hits[symbol] += 3
    ranked = sorted(hits.items(), key=lambda item: (-item[1], item[0]))
    return [symbol for symbol, score in ranked if score >= 3][:3]


def catalyst_scores(text: str) -> tuple[int, int]:
    bull = 0
    bear = 0
    for pattern, weight in BULL_PHRASES:
        if pattern.search(text):
            bull += weight
    for pattern, weight in BEAR_PHRASES:
        if pattern.search(text):
            bear += weight
    return bull, bear


def sentiment_counts(text: str) -> tuple[int, int]:
    tokens = tokenize(text)
    positive = 0
    negative = 0
    for index, token in enumerate(tokens):
        window = tokens[max(0, index - 3) : index]
        negated = any(word in {"not", "no", "never"} or word.endswith("n't") for word in window)
        if token in POS_WORDS:
            if negated:
                negative += 1
            else:
                positive += 1
        elif token in NEG_WORDS:
            if negated:
                positive += 1
            else:
                negative += 1
    return positive, negative


def infer_kind(source: str, text: str) -> str:
    lowered = text.lower()
    if source == "sec":
        return "filing"
    if source == "fed" or "fomc" in lowered or "federal reserve" in lowered:
        return "fed"
    if "fda" in lowered or "advisory committee" in lowered:
        return "fda"
    if source in {"whitehouse", "congress", "federal_register"}:
        return "policy"
    if any(word in lowered for word in ("lawsuit", "hearing", "verdict", "injunction", "court ruling", " in court")):
        return "court"
    return "news"


def policy_view(company_name: str, items: list[NewsItem]) -> tuple[int, str, int]:
    """Return sector bias (-1/0/1), reason, and direct headline net (bull - bear)."""
    name = company_name.lower()
    direct_bull = 0
    direct_bear = 0
    for item in items:
        if item.kind not in {"policy", "fed", "fda", "filing"}:
            continue
        bull, bear = catalyst_scores(f"{item.title} {item.summary}")
        direct_bull += bull
        direct_bear += bear
    direct_net = direct_bull - direct_bear
    blob = " ".join(f"{item.title} {item.summary}" for item in items if item.kind in {"policy", "fed", "fda"})
    for pattern, tokens, bias, reason in POLICY_RULES:
        if pattern.search(blob) and any(token in name for token in tokens):
            return bias, reason, direct_net
    return 0, "", direct_net


def propose_direction(bull: int, bear: int, positive: int, negative: int) -> str | None:
    net = (bull - bear) + (1 if positive > negative else -1 if negative > positive else 0)
    if bull >= 2 and bull > bear and net >= 2:
        return "call"
    if bear >= 2 and bear > bull and net <= -2:
        return "put"
    if bull >= 1 and positive >= 2 and positive > negative and net >= 2:
        return "call"
    if bear >= 1 and negative >= 2 and negative > positive and net <= -2:
        return "put"
    return None


def best_headline(items: list[NewsItem], direction: str) -> NewsItem | None:
    ranked: list[tuple[int, NewsItem]] = []
    for item in items:
        bull, bear = catalyst_scores(f"{item.title} {item.summary}")
        score = bull if direction == "call" else bear
        score += 1 if item.url else 0
        ranked.append((score, item))
    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return ranked[0][1]


def rank_tickers(items: list[NewsItem], now_ts: float | None = None) -> list[tuple[str, int]]:
    scores: dict[str, int] = defaultdict(int)
    for item in items:
        text = f"{item.title} {item.summary}"
        bull, bear = catalyst_scores(text)
        base = max(bull, bear)
        if base == 0 and item.kind in {"filing", "fda", "court"}:
            base = 1
        if item.kind == "filing":
            base += 1
        age_bonus = 0
        if item.published is not None and now_ts is not None:
            hours = (now_ts - item.published.timestamp()) / 3600
            if 0 <= hours <= 18:
                age_bonus = 2
            elif 0 <= hours <= 72:
                age_bonus = 1
        for ticker in item.tickers:
            scores[ticker] += base + age_bonus + 1
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
