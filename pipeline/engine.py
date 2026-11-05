"""Turn a downloaded bundle into trade cards. No network calls in here."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from pipeline.agents import (
    AGENT_NAMES,
    chart_vote,
    confidence_for,
    devil_vote,
    iv_label,
    ma_snapshot,
    news_vote,
    options_vote,
    policy_vote,
    risk_vote,
    score_votes,
    sentiment_vote,
)
from pipeline.config import feature_on
from pipeline.market_math import (
    chart_points,
    last_exit_date,
    market_mood,
    payoff_rows,
    pick_option,
    setup_bonus,
    size_trade,
)
from pipeline.models import Bundle, Equity, NewsItem, Vote
from pipeline.price_check import build_price_checks
from pipeline.scorecard import (
    ensure_stats,
    mark_trades,
    maybe_review,
    open_trades,
    public_scorecard,
    record_ideas,
    weights as scorecard_weights,
)
from pipeline.textutil import best_headline, catalyst_scores, propose_direction, sentiment_counts

ET = ZoneInfo("America/New_York")
DISCLAIMER = (
    "Options Floor is not a broker and not advice. It never places trades, "
    "never connects to a brokerage, and does not send alerts. "
    "Options can expire worthless. You can lose the whole premium."
)


def run_from_bundle(bundle: Bundle, config: dict, scorecard: dict | None) -> tuple[dict, dict]:
    book = ensure_stats(deepcopy(scorecard) if scorecard else {"trades": [], "agentStats": {}, "setupStats": {}, "reviews": []})
    now = bundle.now.astimezone(ET) if bundle.now.tzinfo else bundle.now.replace(tzinfo=ET)
    today = now.date()
    tracking = feature_on(config, "scorecard")
    marks = _collect_marks(bundle)
    if tracking:
        mark_trades(book, marks, today)
    agent_weights = scorecard_weights(book) if tracking else {key: 1.0 for key in AGENT_NAMES}
    regime = market_mood(bundle.spy_closes, bundle.vix)
    regime["applied"] = feature_on(config, "mood")
    if not regime["applied"]:
        regime = {
            **regime,
            "prefer": "wait",
            "summary": regime["summary"] + " Market mood is turned off, so it did not change today's decisions.",
        }

    ranked = _candidate_order(bundle)
    ideas: list[dict] = []
    skipped: list[dict] = []
    used_tickers: set[str] = set()
    for ticker, _score in ranked:
        if ticker in used_tickers:
            continue
        equity = bundle.quotes.get(ticker)
        if equity is None:
            continue
        used_tickers.add(ticker)
        result, reason = _consider(ticker, equity, bundle, config, regime, agent_weights, book, today)
        if result is None:
            if reason:
                skipped.append({"ticker": ticker, "reason": reason})
            continue
        ideas.append(result)

    ideas.sort(key=lambda idea: (-idea["score"], idea["ticker"]))
    threshold = 68 if feature_on(config, "mood") and regime.get("prefer") == "wait" else 60
    open_now = open_trades(book) if tracking else []
    known_ids = {trade["id"] for trade in book.get("trades", [])}
    open_symbols = {trade["ticker"] for trade in open_now}
    slots = max(0, int(config["maxOpen"]) - len(open_now))
    chosen: list[dict] = []
    watches: list[dict] = []
    for idea in ideas:
        if idea["ticker"] in open_symbols:
            skipped.append({"ticker": idea["ticker"], "reason": "This ticker already has an open paper idea."})
            continue
        if idea["id"] in known_ids:
            skipped.append({"ticker": idea["ticker"], "reason": "This exact contract is already on the paper scorecard."})
            continue
        if idea["score"] < threshold:
            skipped.append({"ticker": idea["ticker"], "reason": "The desk score was too low after every vote."})
            continue
        if not feature_on(config, "head"):
            idea["action"] = "WATCH"
            idea["confidence"] = "Off"
            idea["instruction"] = "Head Trader is off, so this is research only, not a buy instruction."
            watches.append(idea)
            continue
        if len(chosen) >= slots:
            skipped.append({"ticker": idea["ticker"], "reason": "The account already has the maximum number of open paper ideas."})
            continue
        chosen.append(idea)

    if tracking and chosen:
        record_ideas(book, chosen, now.isoformat())
    review = maybe_review(book, regime, now, feature_on(config, "review"))
    catalysts = _catalysts(bundle, used_tickers, today) if feature_on(config, "calendar") else []
    flow = _flow(bundle) if feature_on(config, "flow") else []
    squeezes = _squeezes(bundle, ranked) if feature_on(config, "squeeze") else []
    price_checks = build_price_checks(bundle, today) if feature_on(config, "priceCheck") else []
    report = {
        "version": 1,
        "generatedAt": now.isoformat(),
        "runLabel": _run_label(now),
        "disclaimer": DISCLAIMER,
        "banner": _banner(bundle, chosen),
        "stale": False,
        "sourceHealth": bundle.source_health,
        "regime": regime,
        "configEcho": {
            "account": config["account"],
            "minSpend": config["minSpend"],
            "maxSpend": config["maxSpend"],
            "maxOpen": config["maxOpen"],
            "maxPremium": config["maxPremium"],
            "minOpenInterest": config["minOpenInterest"],
            "priceMin": config["priceMin"],
            "priceMax": config["priceMax"],
            "features": config.get("features") or {},
        },
        "universe": {
            "candidates": len(ranked),
            "priced": len(bundle.quotes),
            "chains": len(bundle.chains),
        },
        "ideas": chosen,
        "watch": watches[:5],
        "skipped": skipped[:15],
        "catalysts": catalysts,
        "flow": flow,
        "squeezes": squeezes,
        "priceChecks": price_checks,
        "scorecard": public_scorecard(book, float(config["account"])) if tracking else _paused_scorecard(config),
        "weeklyReview": review,
        "xPosts": "X posts are skipped. There is no stable way to read them without a login.",
    }
    return report, book


def _consider(ticker, equity: Equity, bundle: Bundle, config, regime, agent_weights, book, today):
    price = equity.price
    in_band = config["priceMin"] <= price <= config["priceMax"]
    stretch = bool(config.get("allowHigherPriceIfCheapLeap")) and config["priceMax"] < price <= config["higherPriceMax"]
    if not in_band and not stretch:
        return None, f"The stock is ${price:.2f}, outside the ${config['priceMin']:.0f} to ${config['priceMax']:.0f} range."
    items = [item for item in bundle.items if ticker in item.tickers]
    if not items:
        return None, "No headline stayed attached to this ticker."
    text = " ".join(f"{item.title} {item.summary}" for item in items)
    bull, bear = catalyst_scores(text)
    positive, negative = sentiment_counts(text)
    direction = propose_direction(bull, bear, positive, negative)
    if direction is None:
        return None, "The news does not clearly point to a call or a put."
    catalyst_ok = (direction == "call" and bull >= 2 and bull > bear) or (direction == "put" and bear >= 2 and bear > bull)
    if not catalyst_ok:
        return None, "There is no strong company catalyst."
    if not feature_on(config, "options"):
        return None, "Options Picker is turned off, so no exact contract is named."
    chain = bundle.chains.get(ticker) or []
    if not chain:
        return None, "The option chain did not load."
    max_premium = float(config["maxPremium"]) if feature_on(config, "cheap") else min(5.0, float(config["maxSpend"]) / 100)
    contract = pick_option(chain, price, direction, max_premium, today, leaps_only=stretch)
    if contract is None:
        return None, "No cheap, tradable contract matched the rules."
    if stretch and (contract.expiry - today).days < 270:
        return None, "This stock is above the usual price range and it does not have a cheap LEAPS contract."

    votes: list[Vote] = []
    if feature_on(config, "news"):
        headline = best_headline(items, direction)
        votes.append(news_vote(direction, bull, bear, headline.title if headline else items[0].title))
    if feature_on(config, "policy"):
        votes.append(policy_vote(direction, equity.name, items))
    if feature_on(config, "sentiment"):
        votes.append(sentiment_vote(direction, positive, negative))
    trend = "incomplete"
    phrase = "The daily chart was not used."
    if feature_on(config, "chart"):
        chart, trend, phrase = chart_vote(direction, equity)
        votes.append(chart)
    else:
        trend, phrase = "incomplete", "The daily chart was not used."
    if feature_on(config, "options"):
        votes.append(options_vote(contract))
    flags: list[str] = []
    if feature_on(config, "risk"):
        risk, flags = risk_vote(contract, equity, today, int(config["minOpenInterest"]))
        votes.append(risk)
        if risk.vote == "no":
            return None, risk.reason
    if feature_on(config, "devil"):
        devil, block = devil_vote(direction, equity, contract, items, trend, regime.get("prefer") if regime.get("applied") else "wait", today)
        votes.append(devil)
        if block:
            return None, devil.reason
    if feature_on(config, "options") and any(vote.id == "options" and vote.vote == "no" for vote in votes):
        return None, "Options Picker said no."

    score = score_votes(votes, agent_weights)
    prefer = regime.get("prefer") if feature_on(config, "mood") else "wait"
    if prefer in {"call", "put"} and prefer == direction:
        score += 4
    elif prefer in {"call", "put"} and prefer != direction:
        score -= 8
    tags: list[str] = []
    dte = (contract.expiry - today).days
    is_leap = dte >= 270
    if feature_on(config, "cheap"):
        tags.append("cheap")
    if is_leap:
        tags.append("leap")
    short_ratio = bundle.short_ratios.get(ticker)
    if (
        feature_on(config, "squeeze")
        and direction == "call"
        and short_ratio is not None
        and short_ratio >= 0.45
        and bull >= 2
    ):
        tags.append("squeeze")
        score += setup_bonus(book.get("setupStats") or {}, "squeeze", 4)
    vol_label, vol_sentence, hv = iv_label(contract, equity)
    if feature_on(config, "underpriced") and vol_label == "underpriced":
        tags.append("underpriced")
        score += setup_bonus(book.get("setupStats") or {}, "underpriced", 3)
    if equity.earnings_date is not None and 0 <= (equity.earnings_date - today).days <= 7:
        score -= 6
        tags.append("earnings-soon")
    if any(item.kind == "filing" for item in items):
        tags.append("filing")
    if any(item.kind in {"policy", "fed", "fda"} for item in items):
        tags.append("policy")

    if feature_on(config, "sizing"):
        contracts = size_trade(contract.mid, config["account"], config["minSpend"], config["maxSpend"])
    else:
        contracts = 1 if contract.mid * 100 <= float(config["account"]) else None
    if not contracts:
        return None, "One contract does not fit the account size rules."

    for vote in votes:
        vote.weight = float(agent_weights.get(vote.id, 1.0))
    score_value = int(round(score))
    confidence = confidence_for(score_value, votes)
    if prefer in {"call", "put"} and prefer != direction and confidence == "High":
        confidence = "Medium"
    action = "BUY CALL" if direction == "call" else "BUY PUT"
    headline = best_headline(items, direction) or items[0]
    company = _pretty_company(equity.name, ticker)
    reason = _one_liner(company, price, headline.title, direction, contract.strike, contract.expiry, contract.mid, phrase if feature_on(config, "chart") else "")
    head_reason = f"{confidence} confidence. {reason}"
    if feature_on(config, "head"):
        votes.append(Vote("head", AGENT_NAMES["head"], "yes", head_reason, weight=float(agent_weights.get("head", 1))))
    exit_on = last_exit_date(contract.expiry, today)
    spend = round(contracts * contract.mid * 100, 2)
    idea = {
        "id": f"{ticker}-{direction}-{contract.strike:g}-{contract.expiry.isoformat()}",
        "ticker": ticker,
        "company": company,
        "price": round(price, 2),
        "changePct": None if equity.change_pct is None else round(equity.change_pct, 2),
        "action": action,
        "side": direction,
        "confidence": confidence,
        "score": score_value,
        "contract": {
            "symbol": contract.symbol,
            "strike": contract.strike,
            "expiry": contract.expiry.isoformat(),
            "type": contract.side,
            "dte": dte,
            "isLeap": is_leap,
        },
        "entry": {"low": round(contract.bid, 2), "high": round(contract.ask, 2), "mid": round(contract.mid, 4)},
        "bid": round(contract.bid, 2),
        "ask": round(contract.ask, 2),
        "spreadPct": round(contract.spread_pct, 3),
        "oi": int(contract.oi),
        "volume": int(contract.volume),
        "iv": None if contract.iv is None else round(contract.iv, 4),
        "hv": None if hv is None else round(hv, 4),
        "ivLabel": vol_label,
        "ivSentence": vol_sentence,
        "spend": spend,
        "contracts": contracts,
        "multiplier": 100,
        "takeProfit": _take_profit(contract.mid, contracts),
        "stopLoss": _stop(contract.mid, contracts),
        "lastExitDate": exit_on.isoformat(),
        "lastExitPlain": (
            f"Leave the trade by {exit_on.strftime('%B %d, %Y').replace(' 0', ' ')} "
            "even if neither the target nor the stop has hit. Do not hold into the final days without a fresh look."
        ),
        "reason": reason,
        "news": {
            "title": headline.title,
            "url": headline.url,
            "source": headline.source,
            "published": headline.published.isoformat() if headline.published else None,
        },
        "agents": [vote.as_dict() for vote in votes],
        "payoff": {
            "rows": payoff_rows(direction, contract.strike, contract.mid, contracts, price),
            "note": "These dollars assume you hold to expiration. Before that, a contract with time left is often worth more than this table.",
        },
        "chart": {
            "points": chart_points(equity.bars),
            "averages": ma_snapshot(equity.closes),
            "trend": trend,
        },
        "tags": tags,
        "earningsDate": equity.earnings_date.isoformat() if equity.earnings_date else None,
        "riskFlags": flags,
        "shortRatio": None if short_ratio is None else round(short_ratio, 3),
        "instruction": _steps(ticker, contract, contracts, spend),
    }
    return idea, ""


def _candidate_order(bundle: Bundle) -> list[tuple[str, int]]:
    from pipeline.textutil import rank_tickers

    return rank_tickers(bundle.items, now_ts=bundle.now.timestamp())


def _collect_marks(bundle: Bundle) -> dict[str, float]:
    marks: dict[str, float] = {}
    for contracts in bundle.chains.values():
        for contract in contracts:
            if contract.symbol and contract.mid > 0:
                marks[contract.symbol] = contract.mid
    for symbol, mid in bundle.marks.items():
        if mid and mid > 0:
            marks[symbol] = float(mid)
    return marks


def _pretty_company(name: str, ticker: str) -> str:
    cleaned = name
    suffixes = (
        " Common Stock",
        " Ordinary Shares",
        " Class A",
        " Class B",
        " Class C",
        ", Inc.",
        " Inc.",
        " Corp.",
        " Corporation",
        " Incorporated",
        " Holdings",
        " Limited",
        " Ltd.",
    )
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip(" ,")
                changed = True
    return cleaned or ticker


def _one_liner(company, price, headline, side, strike, expiry, mid, trend_phrase) -> str:
    kind = "call" if side == "call" else "put"
    when = expiry.strftime("%B %d, %Y").replace(" 0", " ")
    head = " ".join(headline.split()).rstrip(".")
    if len(head) > 110:
        head = head[:107].rstrip() + "..."
    trend = f" {trend_phrase}" if trend_phrase else ""
    return (
        f"{company} is about ${price:.2f}. {head}.{trend} "
        f"The {when} ${strike:g} {kind} is about ${mid:.2f}."
    )


def _take_profit(mid: float, contracts: int) -> dict:
    doubled = round(mid * 2, 2)
    if contracts >= 2:
        half = contracts // 2
        dollars = round(half * doubled * 100, 2)
        plain = (
            f"You have {contracts} contracts, so sell half ({half}) if the option doubles to about ${doubled:.2f}. "
            f"That half returns about ${dollars:.0f}. Keep the rest until the stop or the last exit date."
        )
    else:
        dollars = round(doubled * 100, 2)
        plain = (
            f"You only have 1 contract, and you cannot sell half of one contract. "
            f"Sell the whole contract if it doubles to about ${doubled:.2f} (about ${dollars:.0f} back)."
        )
    return {"multiple": 2, "price": doubled, "dollars": dollars, "plain": plain}


def _stop(mid: float, contracts: int) -> dict:
    price = round(mid * 0.5, 2)
    left = round(price * 100 * contracts, 2)
    return {
        "multiple": 0.5,
        "price": price,
        "dollars": left,
        "plain": f"Sell everything if the option loses half its value, near ${price:.2f} (about ${left:.0f} left).",
    }


def _steps(ticker: str, contract, contracts: int, spend: float) -> list[str]:
    kind = "call" if contract.side == "call" else "put"
    when = contract.expiry.strftime("%B %d, %Y").replace(" 0", " ")
    return [
        f"At your own broker, search for {ticker}. This page cannot place the order.",
        "Open the option chain.",
        f"Find the {when} ${contract.strike:g} {kind}.",
        f"Use a limit order between ${contract.bid:.2f} and ${contract.ask:.2f}.",
        f"Buy {contracts} contract(s), about ${spend:.0f}.",
        "Write down the double target, the half-loss stop, and the last exit date before you walk away.",
    ]


def _catalysts(bundle: Bundle, tickers: set[str], today) -> list[dict]:
    rows = []
    seen = set()
    for row in bundle.earnings:
        if row.symbol not in tickers and row.symbol not in bundle.quotes:
            continue
        days = (row.when - today).days
        if days < 0 or days > 21:
            continue
        key = ("earnings", row.symbol, row.when.isoformat())
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "date": row.when.isoformat(),
                "kind": "earnings",
                "title": f"{row.symbol} reports earnings",
                "url": "",
                "tickers": [row.symbol],
                "plain": f"{row.name} is scheduled to report on {row.when.strftime('%B %d, %Y').replace(' 0', ' ')}.",
            }
        )
    for item in bundle.items:
        if item.kind not in {"fda", "fed", "policy", "court", "filing"}:
            continue
        if item.published is None:
            continue
        published_day = item.published.astimezone(ET).date()
        age = (today - published_day).days
        if age > 5:
            continue
        title_key = item.title.strip().lower()
        if title_key in seen:
            continue
        seen.add(title_key)
        when = published_day.isoformat()
        rows.append(
            {
                "date": when,
                "kind": item.kind,
                "title": item.title,
                "url": item.url,
                "tickers": item.tickers[:4],
                "plain": item.summary or item.title,
            }
        )
    rows.sort(key=lambda row: (row["date"], row["title"]))
    return rows[:40]


def _flow(bundle: Bundle) -> list[dict]:
    rows = []
    for ticker, contracts in bundle.chains.items():
        for contract in contracts:
            if contract.oi <= 0 or contract.volume < 500:
                continue
            ratio = contract.volume / contract.oi
            if ratio < 5 and not (contract.volume >= 1000 and ratio >= 3):
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "contract": contract.symbol,
                    "side": contract.side,
                    "strike": contract.strike,
                    "expiry": contract.expiry.isoformat(),
                    "volume": int(contract.volume),
                    "oi": int(contract.oi),
                    "ratio": round(ratio, 2),
                    "note": (
                        f"{ticker} {contract.side} ${contract.strike:g} expiring {contract.expiry.isoformat()} "
                        f"traded {int(contract.volume)} contracts versus {int(contract.oi)} open. "
                        "That is a jump, not a reason by itself to copy the trade."
                    ),
                }
            )
    rows.sort(key=lambda row: row["ratio"], reverse=True)
    return rows[:20]


def _squeezes(bundle: Bundle, ranked: list[tuple[str, int]]) -> list[dict]:
    wanted = {ticker for ticker, _score in ranked} | set(bundle.quotes)
    rows = []
    for ticker in wanted:
        ratio = bundle.short_ratios.get(ticker)
        if ratio is None or ratio < 0.45:
            continue
        items = [item for item in bundle.items if ticker in item.tickers]
        bull, bear = catalyst_scores(" ".join(item.title for item in items))
        if bull < 2 or bull <= bear:
            continue
        headline = best_headline(items, "call") if items else None
        rows.append(
            {
                "ticker": ticker,
                "shortRatio": round(ratio, 3),
                "headline": headline.title if headline else "",
                "url": headline.url if headline else "",
                "note": (
                    f"About {ratio * 100:.0f}% of today's reported volume was short sales, and the news is positive. "
                    "A squeeze is only a guess. Short volume is not the same as short interest as a percent of the whole company."
                ),
            }
        )
    rows.sort(key=lambda row: row["shortRatio"], reverse=True)
    return rows[:12]


def _run_label(now: datetime) -> str:
    minutes = now.hour * 60 + now.minute
    if 9 * 60 + 45 <= minutes <= 11 * 60 + 30:
        return "Morning check"
    if 17 * 60 + 30 <= minutes <= 20 * 60 + 30:
        return "After the close"
    return "Manual check"


def _banner(bundle: Bundle, ideas: list[dict]) -> str:
    failed = [row["label"] for row in bundle.source_health if not row.get("ok")]
    if not ideas and failed:
        return "Some data sources did not answer, and nothing passed the rules. " + ", ".join(failed[:4]) + "."
    if failed:
        return "Some sources did not answer, so today's ideas only use the wires that did. " + ", ".join(failed[:4]) + "."
    if not ideas:
        return "Every source that was checked answered, and no idea passed the rules. Waiting is a result."
    return ""


def _paused_scorecard(config: dict) -> dict:
    return {
        "account": config["account"],
        "openCount": 0,
        "openRisk": 0,
        "realizedPnl": 0,
        "open": [],
        "closed": [],
        "agents": [],
        "setupStats": {},
        "summary": "The scorecard is turned off, so this run did not record paper trades.",
        "paused": True,
    }


def keep_last_good(report: dict, previous: dict | None, now: datetime) -> dict:
    """If this run found nothing and most wires failed, keep the last ideas and say so."""
    if report.get("ideas") or not previous or not previous.get("ideas"):
        return report
    failed = sum(1 for row in report.get("sourceHealth") or [] if not row.get("ok"))
    total = len(report.get("sourceHealth") or [])
    if total == 0 or failed < max(3, total // 2):
        return report
    generated = previous.get("generatedAt")
    if not generated:
        return report
    try:
        old = datetime.fromisoformat(generated)
        if old.tzinfo is None:
            old = old.replace(tzinfo=ET)
        age_days = (now.astimezone(ET) - old.astimezone(ET)).days
    except ValueError:
        return report
    if age_days > 5:
        return report
    report["ideas"] = previous["ideas"]
    if not report.get("priceChecks") and previous.get("priceChecks"):
        report["priceChecks"] = previous["priceChecks"]
    report["stale"] = True
    report["staleFrom"] = generated
    report["banner"] = (
        "This run had trouble reaching the data sources, so the ideas below are from the last good run. "
        "Do not treat them as fresh."
    )
    return report
