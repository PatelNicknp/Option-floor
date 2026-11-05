"""Each desk member returns a yes, no, or pass, plus one plain sentence."""

from __future__ import annotations

from datetime import date

from pipeline.market_math import realized_vol, sma, tradable_contract, trend_label
from pipeline.models import Equity, NewsItem, OptionContract, Vote
from pipeline.textutil import catalyst_scores, policy_view, sentiment_counts

AGENT_NAMES = {
    "news": "News Scout",
    "policy": "Policy & Politics Scout",
    "sentiment": "Sentiment Scout",
    "chart": "Chart Reader",
    "options": "Options Picker",
    "risk": "Risk Checker",
    "devil": "Devil's Advocate",
    "head": "Head Trader",
}


def news_vote(direction: str, bull: int, bear: int, headline: str) -> Vote:
    short = _clip(headline)
    if direction == "call" and bull >= 2 and bull > bear:
        reason = f"The headline supports a call: {short}"
        vote = "yes"
    elif direction == "put" and bear >= 2 and bear > bull:
        reason = f"The headline supports a put: {short}"
        vote = "yes"
    elif direction == "call" and bear > bull:
        reason = "The news looks bad for the company, which fights a call."
        vote = "no"
    elif direction == "put" and bull > bear:
        reason = "The news looks good for the company, which fights a put."
        vote = "no"
    else:
        reason = "The news does not clearly say the company is doing better or worse."
        vote = "pass"
    return Vote("news", AGENT_NAMES["news"], vote, reason)


def policy_vote(direction: str, company_name: str, items: list[NewsItem]) -> Vote:
    bias, sector_reason, direct_net = policy_view(company_name, items)
    if direct_net >= 2 and direction == "call":
        return Vote("policy", AGENT_NAMES["policy"], "yes", "A policy or filing headline about this company supports a call.")
    if direct_net <= -2 and direction == "put":
        return Vote("policy", AGENT_NAMES["policy"], "yes", "A policy or filing headline about this company supports a put.")
    if direct_net >= 2 and direction == "put":
        return Vote("policy", AGENT_NAMES["policy"], "no", "Policy news about this company looks positive, which fights a put.")
    if direct_net <= -2 and direction == "call":
        return Vote("policy", AGENT_NAMES["policy"], "no", "Policy news about this company looks negative, which fights a call.")
    if bias > 0 and direction == "call":
        return Vote("policy", AGENT_NAMES["policy"], "yes", sector_reason)
    if bias < 0 and direction == "put":
        return Vote("policy", AGENT_NAMES["policy"], "yes", sector_reason)
    if bias > 0 and direction == "put":
        return Vote("policy", AGENT_NAMES["policy"], "no", sector_reason + " That fights a put.")
    if bias < 0 and direction == "call":
        return Vote("policy", AGENT_NAMES["policy"], "no", sector_reason + " That fights a call.")
    return Vote("policy", AGENT_NAMES["policy"], "pass", "No policy or political item lines up clearly with this company.")


def sentiment_vote(direction: str, positive: int, negative: int) -> Vote:
    if positive == 0 and negative == 0:
        return Vote("sentiment", AGENT_NAMES["sentiment"], "pass", "The headlines are flat. No clear happy or grim tone.")
    if direction == "call" and positive > negative:
        return Vote(
            "sentiment",
            AGENT_NAMES["sentiment"],
            "yes",
            f"The headlines lean positive ({positive} upbeat, {negative} grim).",
        )
    if direction == "put" and negative > positive:
        return Vote(
            "sentiment",
            AGENT_NAMES["sentiment"],
            "yes",
            f"The headlines lean grim ({negative} grim, {positive} upbeat).",
        )
    if direction == "call" and negative > positive:
        return Vote("sentiment", AGENT_NAMES["sentiment"], "no", "The tone of the headlines is grim, which fights a call.")
    if direction == "put" and positive > negative:
        return Vote("sentiment", AGENT_NAMES["sentiment"], "no", "The tone of the headlines is positive, which fights a put.")
    return Vote("sentiment", AGENT_NAMES["sentiment"], "pass", "The tone is mixed, so it does not push the idea either way.")


def chart_vote(direction: str, equity: Equity) -> tuple[Vote, str, str]:
    label, phrase = trend_label(equity.closes)
    if label == "incomplete":
        vote = "pass"
        reason = phrase
    elif direction == "call" and label in {"up", "lean_up"}:
        vote = "yes"
        reason = phrase
    elif direction == "put" and label in {"down", "lean_down"}:
        vote = "yes"
        reason = phrase
    elif label == "mixed":
        vote = "pass"
        reason = phrase
    elif direction == "call":
        vote = "no"
        reason = phrase + " That fights a call."
    else:
        vote = "no"
        reason = phrase + " That fights a put."
    return Vote("chart", AGENT_NAMES["chart"], vote, reason), label, phrase


def options_vote(contract: OptionContract) -> Vote:
    kind = "call" if contract.side == "call" else "put"
    when = contract.expiry.strftime("%B %d, %Y").replace(" 0", " ")
    reason = (
        f"Use the {when} ${contract.strike:g} {kind}. "
        f"Try to pay ${contract.bid:.2f} to ${contract.ask:.2f}."
    )
    return Vote("options", AGENT_NAMES["options"], "yes", reason)


def risk_vote(contract: OptionContract, equity: Equity, today: date, min_oi: int) -> tuple[Vote, list[str]]:
    flags: list[str] = []
    earnings = equity.earnings_date
    earnings_days = None if earnings is None else (earnings - today).days
    if earnings_days is not None and 0 <= earnings_days <= 14:
        when = earnings.strftime("%B %d, %Y").replace(" 0", " ") if earnings else ""
        flags.append(f"Earnings are on {when}.")
    if not tradable_contract(contract, max_premium=max(contract.ask, 0.01)) or contract.bid <= 0:
        return Vote("risk", AGENT_NAMES["risk"], "no", "There is no real bid and ask, so skip it."), flags
    if contract.oi < 10:
        return Vote("risk", AGENT_NAMES["risk"], "no", "Almost nobody is in this contract, so it may be hard to sell."), flags
    if earnings_days is not None and 0 <= earnings_days <= 2:
        return (
            Vote(
                "risk",
                AGENT_NAMES["risk"],
                "no",
                "Earnings are in the next two days. The option can collapse right after the announcement, so skip it.",
            ),
            flags,
        )
    soft = False
    if contract.oi < min_oi:
        soft = True
        flags.append("Open interest is on the light side.")
    if contract.spread_pct > 0.45 and contract.spread > 0.10:
        soft = True
        flags.append("The gap between the bid and the ask is wide.")
    if contract.iv is not None and contract.iv > 1.8:
        soft = True
        flags.append("The option price implies very large swings.")
    if soft:
        return (
            Vote("risk", AGENT_NAMES["risk"], "pass", "The market is usable, but there is a caution: " + " ".join(flags)),
            flags,
        )
    return (
        Vote(
            "risk",
            AGENT_NAMES["risk"],
            "yes",
            "The bid and ask are close enough, and there is a real open market in this contract.",
        ),
        flags,
    )


def devil_vote(
    direction: str,
    equity: Equity,
    contract: OptionContract,
    items: list[NewsItem],
    trend: str,
    prefer: str,
    today: date,
) -> tuple[Vote, bool]:
    issues: list[str] = []
    hv = realized_vol(equity.closes)
    if contract.spread_pct > 0.35 and contract.spread > 0.08:
        issues.append("The gap between the bid and the ask is wide, so you may overpay.")
    if contract.oi < 100:
        issues.append("Not many contracts are open, so it may be hard to sell later.")
    if contract.iv is not None and hv is not None and contract.iv > hv * 1.4:
        issues.append("The option is expensive compared with how much the stock has actually been moving.")
    if equity.earnings_date is not None and 0 <= (equity.earnings_date - today).days <= 7:
        issues.append("Earnings are close. The option can lose a lot of value right after, even if the direction is right.")
    if direction == "call" and trend in {"down", "lean_down"}:
        issues.append("The daily chart still points down, so this call fights the trend.")
    if direction == "put" and trend in {"up", "lean_up"}:
        issues.append("The daily chart still points up, so this put fights the trend.")
    change = equity.change_pct
    if change is not None and abs(change) >= 8:
        issues.append("The stock already moved a lot today, so the news may be baked into the price.")
    blob = " ".join(item.title.lower() for item in items)
    if direction == "call" and any(word in blob for word in ("offering", "dilution", "registered direct")):
        issues.append("A headline mentions an offering. New shares can push the stock down.")
    if prefer == "put" and direction == "call":
        issues.append("The broader market looks scared, which works against a new call.")
    if prefer == "call" and direction == "put":
        issues.append("The broader market looks calm and rising, which works against a new put.")
    block = len(issues) >= 3
    if not issues:
        return Vote("devil", AGENT_NAMES["devil"], "yes", "I do not see a fatal hole in this idea."), False
    if len(issues) == 1:
        return Vote("devil", AGENT_NAMES["devil"], "pass", issues[0]), False
    return Vote("devil", AGENT_NAMES["devil"], "no", " ".join(issues)), block


def iv_label(contract: OptionContract, equity: Equity) -> tuple[str, str, float | None]:
    hv = realized_vol(equity.closes)
    if contract.iv is None or hv is None or hv <= 0:
        return "unknown", "There is not enough history to compare the option price with the stock's swings.", hv
    iv_pct = contract.iv * 100
    hv_pct = hv * 100
    if contract.iv < hv * 0.85:
        label = "underpriced"
        sentence = (
            f"The option's implied volatility is {iv_pct:.0f}%. The stock's recent swings are about {hv_pct:.0f}% a year. "
            "The option looks a bit cheap versus those swings. This is a rough check, not a promise."
        )
    elif contract.iv > hv * 1.4:
        label = "expensive"
        sentence = (
            f"The option's implied volatility is {iv_pct:.0f}%. The stock's recent swings are about {hv_pct:.0f}% a year. "
            "The option costs more than those swings would suggest. You may be paying extra for the news."
        )
    else:
        label = "fair"
        sentence = (
            f"The option's implied volatility is {iv_pct:.0f}%, close to the stock's recent {hv_pct:.0f}% swings."
        )
    return label, sentence, hv


def ma_snapshot(closes: list[float]) -> dict:
    def val(window: int) -> float | None:
        value = sma(closes, window)
        return None if value is None else round(value, 2)

    return {"ma10": val(10), "ma20": val(20), "ma50": val(50), "ma150": val(150), "ma200": val(200)}


def _clip(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def score_votes(votes: list[Vote], weights: dict[str, float]) -> float:
    total = 50.0
    for vote in votes:
        if vote.id == "head":
            continue
        weight = float(weights.get(vote.id, 1.0))
        if vote.vote == "yes":
            total += 6 * weight
        elif vote.vote == "no":
            total -= 8 * weight
    return total


def confidence_for(score: float, votes: list[Vote]) -> str:
    by_id = {vote.id: vote for vote in votes}
    risk = by_id.get("risk")
    devil = by_id.get("devil")
    clean = (risk is None or risk.vote == "yes") and (devil is None or devil.vote != "no")
    if score >= 78 and clean:
        return "High"
    if score >= 68:
        return "Medium"
    return "Low"
