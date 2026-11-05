"""Saved inputs for the Option Price Checker.

Yahoo's option chain cannot be read from the website. The chain call needs a
cookie and a crumb, and Yahoo does not allow a browser on another site to
fetch it. The job already downloads chains for the names it studies. This
module trims those chains so the page can price a strike without a new request.

A true IV rank needs a year of this option's old prices. Free data does not
include that. The percentile here is where today's implied volatility sits
among the stock's own 20-day swings over the past year.
"""

from __future__ import annotations

from datetime import date

from pipeline.market_math import realized_vol
from pipeline.models import Bundle, OptionContract

STRIKES_PER_SIDE = 15
MIN_HISTORY = 30


def percentile_below(samples: list[float], value: float | None) -> int | None:
    """Percent of samples strictly below value, from 0 to 100."""
    if value is None or value <= 0 or len(samples) < MIN_HISTORY:
        return None
    below = sum(1 for item in samples if item < value)
    return int(round(100 * below / len(samples)))


def hv_history(closes: list[float], window: int = 20) -> list[float]:
    vols: list[float] = []
    for end in range(window + 1, len(closes) + 1):
        vol = realized_vol(closes[:end], window)
        if vol is not None and vol > 0:
            vols.append(vol)
    return vols[-252:]


def build_price_checks(bundle: Bundle, today: date) -> list[dict]:
    rows = []
    for ticker in sorted(bundle.chains):
        equity = bundle.quotes.get(ticker)
        contracts = bundle.chains.get(ticker) or []
        if equity is None or equity.price <= 0 or not contracts:
            continue
        history = hv_history(equity.closes, 20)
        hv20 = realized_vol(equity.closes, 20)
        hv60 = realized_vol(equity.closes, 60)
        grouped: dict[date, list[OptionContract]] = {}
        for contract in contracts:
            if contract.expiry is None:
                continue
            grouped.setdefault(contract.expiry, []).append(contract)
        expirations = []
        for expiry in sorted(grouped):
            if (expiry - today).days < 1:
                continue
            calls = _side(grouped[expiry], "call", equity.price, history)
            puts = _side(grouped[expiry], "put", equity.price, history)
            if not calls and not puts:
                continue
            expirations.append({"expiry": expiry.isoformat(), "calls": calls, "puts": puts})
        if not expirations:
            continue
        earnings = None
        if equity.earnings_date is not None and equity.earnings_date >= today:
            earnings = equity.earnings_date.isoformat()
        rows.append(
            {
                "ticker": ticker,
                "company": equity.name,
                "price": round(float(equity.price), 2),
                "hv20": None if hv20 is None else round(hv20, 4),
                "hv60": None if hv60 is None else round(hv60, 4),
                "earningsDate": earnings,
                "expirations": expirations,
            }
        )
    return rows


def _side(contracts: list[OptionContract], side: str, spot: float, history: list[float]) -> list[dict]:
    best: dict[float, OptionContract] = {}
    for contract in contracts:
        if contract.side != side or not _quoted(contract):
            continue
        previous = best.get(contract.strike)
        if previous is None or contract.oi > previous.oi:
            best[contract.strike] = contract
    pool = list(best.values())
    pool.sort(key=lambda contract: (abs(contract.strike - spot), contract.strike))
    kept = pool[:STRIKES_PER_SIDE]
    kept.sort(key=lambda contract: contract.strike)
    rows = []
    for contract in kept:
        rows.append(
            {
                "strike": contract.strike,
                "bid": round(contract.bid, 2),
                "ask": round(contract.ask, 2),
                "oi": int(contract.oi),
                "iv": round(float(contract.iv or 0), 4),
                "ivPercentile": percentile_below(history, contract.iv),
            }
        )
    return rows


def _quoted(contract: OptionContract) -> bool:
    if contract.iv is None or contract.iv <= 0:
        return False
    if contract.bid <= 0 or contract.ask <= 0 or contract.ask < contract.bid:
        return False
    return True
