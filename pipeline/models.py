"""Plain data the research job passes between steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class SymbolInfo:
    symbol: str
    name: str
    yahoo: str


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: datetime | None = None
    summary: str = ""
    tickers: list[str] = field(default_factory=list)
    kind: str = "news"


@dataclass
class OptionContract:
    symbol: str
    side: str
    strike: float
    expiry: date
    bid: float
    ask: float
    last: float
    volume: float
    oi: float
    iv: float | None

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last or self.ask or self.bid

    @property
    def spread(self) -> float:
        return max(0.0, self.ask - self.bid)

    @property
    def spread_pct(self) -> float:
        mid = self.mid
        if mid <= 0:
            return 1.0
        return self.spread / mid


@dataclass
class Equity:
    symbol: str
    name: str
    price: float
    bars: list[tuple[date, float]]
    earnings_date: date | None = None

    @property
    def closes(self) -> list[float]:
        return [close for _, close in self.bars]

    @property
    def change_pct(self) -> float | None:
        closes = self.closes
        if len(closes) < 2 or closes[-2] <= 0:
            return None
        return (closes[-1] / closes[-2] - 1) * 100


@dataclass
class EarningsRow:
    symbol: str
    name: str
    when: date
    market_cap: float | None = None


@dataclass
class Vote:
    id: str
    name: str
    vote: str
    reason: str
    weight: float = 1.0

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "vote": self.vote,
            "reason": self.reason,
            "weight": round(self.weight, 3),
        }


@dataclass
class Bundle:
    now: datetime
    items: list[NewsItem]
    symbols: dict[str, SymbolInfo]
    quotes: dict[str, Equity]
    chains: dict[str, list[OptionContract]]
    short_ratios: dict[str, float]
    earnings: list[EarningsRow]
    spy_closes: list[float] | None = None
    vix: float | None = None
    source_health: list[dict] = field(default_factory=list)
    marks: dict[str, float] = field(default_factory=dict)
