"""Daily-chart math, position size, and expiration payoff. No intraday data."""

from __future__ import annotations

import math
from datetime import date, timedelta

from pipeline.models import OptionContract


def sma(values: list[float], window: int) -> float | None:
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def realized_vol(closes: list[float], window: int = 20) -> float | None:
    """Annualized realized volatility from daily log returns."""
    if len(closes) < window + 1:
        return None
    tail = closes[-(window + 1) :]
    rets: list[float] = []
    for earlier, later in zip(tail, tail[1:]):
        if earlier <= 0 or later <= 0:
            return None
        rets.append(math.log(later / earlier))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((item - mean) ** 2 for item in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def trend_label(closes: list[float]) -> tuple[str, str]:
    price = closes[-1] if closes else None
    ma10 = sma(closes, 10)
    ma20 = sma(closes, 20)
    ma50 = sma(closes, 50)
    if price is None or ma10 is None or ma20 is None or ma50 is None:
        return "incomplete", "There is not enough daily history to read the averages."
    if price > ma10 > ma20 and price > ma50:
        return "up", "The daily trend points up."
    if price < ma10 < ma20 and price < ma50:
        return "down", "The daily trend points down."
    if price > ma50 and ma10 > ma20:
        return "lean_up", "The daily trend leans up."
    if price < ma50 and ma10 < ma20:
        return "lean_down", "The daily trend leans down."
    return "mixed", "The daily chart is mixed."


def chart_points(bars: list[tuple[date, float]], limit: int = 80) -> list[dict]:
    closes = [close for _, close in bars]
    points: list[dict] = []
    for index in range(len(closes)):
        window = closes[: index + 1]

        def avg(window_size: int) -> float | None:
            if len(window) < window_size:
                return None
            return round(sum(window[-window_size:]) / window_size, 2)

        points.append(
            {
                "c": round(closes[index], 2),
                "ma10": avg(10),
                "ma20": avg(20),
                "ma50": avg(50),
                "ma150": avg(150),
                "ma200": avg(200),
            }
        )
    return points[-limit:]


def market_mood(spy_closes: list[float] | None, vix: float | None) -> dict:
    if not spy_closes or len(spy_closes) < 60:
        return {
            "mood": "unclear",
            "prefer": "wait",
            "title": "Market mood is unclear",
            "summary": "The S&P 500 daily history did not load, so the desk will not lean toward calls or puts.",
            "vix": vix,
            "spyPrice": round(spy_closes[-1], 2) if spy_closes else None,
        }
    price = spy_closes[-1]
    ma10 = sma(spy_closes, 10)
    ma50 = sma(spy_closes, 50)
    ma200 = sma(spy_closes, 200)
    calm = (
        ma10 is not None
        and ma50 is not None
        and ma200 is not None
        and price > ma10
        and price > ma50
        and price > ma200
        and vix is not None
        and vix < 18
    )
    fear = (vix is not None and vix >= 25) or (
        ma10 is not None and ma200 is not None and price < ma10 and price < ma200
    )
    base = {
        "vix": None if vix is None else round(vix, 2),
        "spyPrice": round(price, 2),
        "spyAbove50": bool(ma50 is not None and price > ma50),
        "spyAbove200": bool(ma200 is not None and price > ma200),
    }
    if calm and not fear:
        return {
            **base,
            "mood": "calm-uptrend",
            "prefer": "call",
            "title": "Calm uptrend",
            "summary": "The S&P 500 is above its 10, 50, and 200 day averages and the VIX is under 18. The desk prefers calls.",
        }
    if fear and not calm:
        return {
            **base,
            "mood": "fear",
            "prefer": "put",
            "title": "Fearful market",
            "summary": "The VIX is elevated or the S&P 500 is under its longer averages. The desk prefers puts.",
        }
    if vix is None:
        summary = "The S&P 500 loaded, but the VIX did not, so the desk will not lean toward calls or puts."
    else:
        summary = "The market is not a clear calm uptrend or a clear fearful tape. The desk would rather wait than force a side."
    return {
        **base,
        "mood": "unclear",
        "prefer": "wait",
        "title": "Market mood is unclear",
        "summary": summary,
    }


def size_trade(mid: float, account: float, min_spend: float, max_spend: float) -> int | None:
    """How many contracts fit the spend band and 10% of the account."""
    if mid <= 0 or account <= 0 or max_spend <= 0:
        return None
    cost = mid * 100.0
    cap = min(float(max_spend), float(account) * 0.10)
    floor = float(min_spend)
    if cap <= 0:
        return None
    if floor > cap:
        floor = cap
    if cost > cap + 1e-9:
        return None
    target = (floor + cap) / 2.0
    best_n: int | None = None
    best_dist: float | None = None
    contracts = 1
    while contracts <= 20 and contracts * cost <= cap + 1e-6:
        spend = contracts * cost
        if spend + 1e-9 >= floor:
            dist = abs(spend - target)
            if best_dist is None or dist < best_dist - 1e-9:
                best_dist = dist
                best_n = contracts
        contracts += 1
    return best_n


def payoff_rows(side: str, strike: float, premium: float, contracts: int, spot: float, moves: list[float] | None = None) -> list[dict]:
    """Value at expiration. Time value before expiration is usually higher than this."""
    moves = moves if moves is not None else [-0.20, -0.10, -0.05, 0.05, 0.10, 0.20]
    cost = premium * 100 * contracts
    rows = []
    for move in moves:
        future = spot * (1 + move)
        if side == "call":
            intrinsic = max(0.0, future - strike)
        else:
            intrinsic = max(0.0, strike - future)
        value = intrinsic * 100 * contracts
        rows.append(
            {
                "pct": int(round(move * 100)),
                "stock": round(future, 2),
                "value": round(value, 2),
                "pnl": round(value - cost, 2),
            }
        )
    return rows


def last_exit_date(expiry: date, today: date) -> date:
    days = (expiry - today).days
    if days > 180:
        exit_on = min(expiry - timedelta(days=21), today + timedelta(days=120))
    elif days > 45:
        exit_on = expiry - timedelta(days=14)
    else:
        exit_on = expiry - timedelta(days=2)
    if exit_on <= today:
        exit_on = today + timedelta(days=1)
    if exit_on >= expiry:
        exit_on = expiry - timedelta(days=1)
    if exit_on <= today:
        exit_on = today
    return exit_on


def tradable_contract(contract: OptionContract, max_premium: float) -> bool:
    if contract.bid <= 0 or contract.ask <= 0:
        return False
    if contract.ask > max_premium + 1e-9:
        return False
    if contract.spread > 0.40:
        return False
    if contract.spread_pct > 0.85:
        return False
    if contract.oi < 10:
        return False
    return True


def pick_option(
    chain: list[OptionContract],
    spot: float,
    side: str,
    max_premium: float,
    today: date,
    leaps_only: bool = False,
) -> OptionContract | None:
    best: OptionContract | None = None
    best_score = -10**9
    for contract in chain:
        if contract.side != side:
            continue
        if not tradable_contract(contract, max_premium):
            continue
        dte = (contract.expiry - today).days
        if dte < 5:
            continue
        if leaps_only and dte < 270:
            continue
        if side == "call":
            distance = (contract.strike - spot) / spot
        else:
            distance = (spot - contract.strike) / spot
        if distance < -0.12 or distance > 0.40:
            continue
        mid = contract.mid
        score = max(0.0, 30 - abs(mid - 0.55) * 80)
        score += max(0.0, 18 - contract.spread_pct * 30)
        if contract.oi >= 500:
            score += 16
        elif contract.oi >= 100:
            score += 10
        elif contract.oi >= 50:
            score += 6
        else:
            score -= 8
        if contract.volume >= 200:
            score += 4
        if dte >= 270 and mid <= max_premium:
            score += 12
        elif 14 <= dte <= 90:
            score += 6
        if 0.03 <= distance <= 0.20:
            score += 8
        elif distance < 0:
            score += 3
        if score > best_score:
            best_score = score
            best = contract
    return best


def setup_bonus(stats: dict, tag: str, default: float) -> float:
    row = stats.get(tag) or {}
    graded = int(row.get("wins", 0)) + int(row.get("losses", 0))
    if graded < 4:
        return default
    win_rate = row["wins"] / graded
    if win_rate < 0.40:
        return 0.0
    if win_rate > 0.65:
        return default + 3
    return default
