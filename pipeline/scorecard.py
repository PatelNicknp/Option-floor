"""Paper trades only. Nothing here is a broker order."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from pipeline.agents import AGENT_NAMES

AGENT_IDS = ("news", "policy", "sentiment", "chart", "options", "risk", "devil", "head")


def empty_scorecard() -> dict:
    return {"trades": [], "agentStats": {}, "setupStats": {}, "reviews": []}


def ensure_stats(scorecard: dict) -> dict:
    stats = scorecard.setdefault("agentStats", {})
    for agent_id in AGENT_IDS:
        stats.setdefault(agent_id, {"wins": 0, "losses": 0, "weight": 1.0})
    scorecard.setdefault("setupStats", {})
    scorecard.setdefault("trades", [])
    scorecard.setdefault("reviews", [])
    return scorecard


def _weight(row: dict) -> float:
    graded = int(row.get("wins", 0)) + int(row.get("losses", 0))
    if graded < 4:
        return 1.0
    win_rate = row["wins"] / graded
    return max(0.7, min(1.3, 0.75 + 0.5 * win_rate))


def refresh_weights(scorecard: dict) -> dict:
    for row in scorecard.get("agentStats", {}).values():
        row["weight"] = round(_weight(row), 3)
    return scorecard


def weights(scorecard: dict) -> dict[str, float]:
    ensure_stats(scorecard)
    refresh_weights(scorecard)
    return {agent_id: float(scorecard["agentStats"][agent_id]["weight"]) for agent_id in AGENT_IDS}


def open_trades(scorecard: dict) -> list[dict]:
    return [
        trade
        for trade in scorecard.get("trades", [])
        if trade.get("status") == "open" and int(trade.get("remainingContracts") or 0) > 0
    ]


def ensure_history(trade: dict) -> list[dict]:
    """Make sure a trade has a price history.

    Older trades were stored before the job kept a history. For those, start the
    history with the two prices that really were stored: the entry and the last
    check. Nothing in between is made up.
    """
    history = trade.get("markHistory")
    if isinstance(history, list) and history:
        return history
    history = []
    entry = trade.get("entry")
    opened = str(trade.get("openedAt") or "")
    if entry is not None and opened:
        history.append({"at": opened, "mark": round(float(entry), 4), "stock": _num(trade.get("stockAtEntry"))})
    last = trade.get("lastMark")
    checked = str(trade.get("lastChecked") or "")
    if last is not None and checked and checked[:10] > opened[:10]:
        history.append({"at": checked, "mark": round(float(last), 4), "stock": None})
    trade["markHistory"] = history
    return history


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if number > 0 else None


def mark_trades(
    scorecard: dict,
    marks: dict[str, float],
    today: date,
    stocks: dict[str, float] | None = None,
    at: str | None = None,
    history_max: int = 120,
) -> list[dict]:
    """Update open paper trades from the latest option mid. Returns newly closed trades."""
    ensure_stats(scorecard)
    stocks = stocks or {}
    stamp = at or today.isoformat()
    closed: list[dict] = []
    for trade in scorecard["trades"]:
        if trade.get("status") != "open":
            continue
        history = ensure_history(trade)
        stock_now = _num(stocks.get(trade.get("ticker") or ""))
        if stock_now is not None:
            trade["lastStock"] = stock_now
            trade["lastStockAt"] = stamp
        symbol = trade.get("contractSymbol") or ""
        if symbol not in marks:
            trade["checkNote"] = "Could not check the option price this run."
            continue
        mid = float(marks[symbol])
        if mid <= 0:
            trade["checkNote"] = "Could not check the option price this run."
            continue
        trade["lastMark"] = round(mid, 4)
        trade["lastChecked"] = today.isoformat()
        trade["checkNote"] = ""
        if not history or history[-1].get("at") != stamp:
            history.append({"at": stamp, "mark": round(mid, 4), "stock": stock_now})
        if history_max > 2 and len(history) > history_max:
            # Keep the entry point, drop the oldest checks after it.
            trade["markHistory"] = [history[0]] + history[-(history_max - 1) :]
        entry = float(trade["entry"])
        remaining = int(trade["remainingContracts"])
        exit_on = date.fromisoformat(trade["lastExitDate"])
        expiry = date.fromisoformat(trade["expiry"])
        notes = trade.setdefault("notes", [])

        def close(outcome: str) -> None:
            nonlocal remaining
            trade["realizedPnl"] = round(float(trade.get("realizedPnl") or 0) + (mid - entry) * remaining * 100, 2)
            trade["remainingContracts"] = 0
            trade["status"] = "closed"
            trade["outcome"] = outcome
            trade["closedAt"] = today.isoformat()
            closed.append(trade)

        if today >= expiry or today >= exit_on:
            close("target" if mid >= entry * 2 - 1e-9 else "time")
            continue
        if mid <= entry * 0.5 + 1e-9:
            close("stop")
            continue
        if mid >= entry * 2 - 1e-9:
            if remaining >= 2 and not trade.get("halfClosed"):
                sold = remaining // 2
                trade["realizedPnl"] = round(float(trade.get("realizedPnl") or 0) + (mid - entry) * sold * 100, 2)
                trade["remainingContracts"] = remaining - sold
                trade["halfClosed"] = True
                notes.append(f"Sold half at about ${mid:.2f}.")
            elif remaining == 1:
                close("target")
    for trade in closed:
        _grade(scorecard, trade)
    refresh_weights(scorecard)
    return closed


def _grade(scorecard: dict, trade: dict) -> None:
    win = float(trade.get("realizedPnl") or 0) > 0
    for agent_id, vote in (trade.get("agentVotes") or {}).items():
        if vote != "yes":
            continue
        row = scorecard["agentStats"].setdefault(agent_id, {"wins": 0, "losses": 0, "weight": 1.0})
        if win:
            row["wins"] += 1
        else:
            row["losses"] += 1
    for tag in trade.get("tags") or []:
        row = scorecard["setupStats"].setdefault(tag, {"wins": 0, "losses": 0})
        if win:
            row["wins"] += 1
        else:
            row["losses"] += 1


def record_ideas(scorecard: dict, ideas: list[dict], opened_at: str) -> None:
    ensure_stats(scorecard)
    existing = {trade["id"] for trade in scorecard["trades"]}
    for idea in ideas:
        if idea["action"] not in {"BUY CALL", "BUY PUT"}:
            continue
        if idea["id"] in existing:
            continue
        scorecard["trades"].append(
            {
                "id": idea["id"],
                "openedAt": opened_at,
                "ticker": idea["ticker"],
                "company": idea["company"],
                "action": idea["action"],
                "contractSymbol": idea["contract"]["symbol"],
                "expiry": idea["contract"]["expiry"],
                "strike": idea["contract"]["strike"],
                "side": idea["side"],
                "entry": idea["entry"]["mid"],
                "contracts": idea["contracts"],
                "halfClosed": False,
                "remainingContracts": idea["contracts"],
                "status": "open",
                "lastMark": idea["entry"]["mid"],
                "stockAtEntry": idea.get("price"),
                "markHistory": [{"at": opened_at, "mark": idea["entry"]["mid"], "stock": idea.get("price")}],
                "realizedPnl": 0,
                "agentVotes": {vote["id"]: vote["vote"] for vote in idea["agents"]},
                "tags": idea.get("tags") or [],
                "lastExitDate": idea["lastExitDate"],
                "reason": idea["reason"],
                "newsUrl": (idea.get("news") or {}).get("url") or "",
                "confidence": idea["confidence"],
                "probableNews": bool(idea.get("probableNews")),
                "notes": [],
                "outcome": "",
                "closedAt": "",
                "checkNote": "",
                "lastChecked": opened_at[:10],
            }
        )


def public_scorecard(scorecard: dict, account: float) -> dict:
    ensure_stats(scorecard)
    refresh_weights(scorecard)
    opens = open_trades(scorecard)
    closed = [trade for trade in scorecard["trades"] if trade.get("status") == "closed"]
    closed_view = list(reversed(closed[-12:]))
    realized = round(sum(float(trade.get("realizedPnl") or 0) for trade in closed), 2)
    open_risk = round(sum(float(trade["entry"]) * int(trade["remainingContracts"]) * 100 for trade in opens), 2)

    def plain_weight(row: dict) -> str:
        graded = int(row["wins"]) + int(row["losses"])
        if graded < 4:
            return "Even weight until this scout has a yes vote on at least 4 finished ideas."
        return f"Right on {row['wins']} of {graded} finished ideas it voted yes on."

    agents = []
    for agent_id in AGENT_IDS:
        row = scorecard["agentStats"][agent_id]
        agents.append(
            {
                "id": agent_id,
                "name": AGENT_NAMES[agent_id],
                "wins": row["wins"],
                "losses": row["losses"],
                "weight": row["weight"],
                "plain": plain_weight(row),
            }
        )
    return {
        "account": account,
        "openCount": len(opens),
        "openRisk": open_risk,
        "realizedPnl": realized,
        "open": [_public_trade(trade) for trade in opens],
        "closed": [_public_trade(trade) for trade in closed_view],
        "agents": agents,
        "setupStats": scorecard.get("setupStats") or {},
        "summary": _summary(len(opens), realized, open_risk, account),
    }


def _public_trade(trade: dict) -> dict:
    return {
        "id": trade["id"],
        "ticker": trade["ticker"],
        "action": trade["action"],
        "contractSymbol": trade.get("contractSymbol"),
        "strike": trade.get("strike"),
        "expiry": trade.get("expiry"),
        "entry": trade.get("entry"),
        "lastMark": trade.get("lastMark"),
        "contracts": trade.get("contracts"),
        "remainingContracts": trade.get("remainingContracts"),
        "status": trade.get("status"),
        "outcome": trade.get("outcome") or "",
        "realizedPnl": trade.get("realizedPnl") or 0,
        "openedAt": trade.get("openedAt"),
        "closedAt": trade.get("closedAt") or "",
        "lastExitDate": trade.get("lastExitDate"),
        "halfClosed": bool(trade.get("halfClosed")),
        "checkNote": trade.get("checkNote") or "",
        "reason": trade.get("reason") or "",
        "newsUrl": trade.get("newsUrl") or "",
        "confidence": trade.get("confidence") or "",
        "side": trade.get("side") or ("call" if "CALL" in str(trade.get("action") or "") else "put"),
        "stockAtEntry": _num(trade.get("stockAtEntry")),
        "lastStock": _num(trade.get("lastStock")),
        "lastStockAt": trade.get("lastStockAt") or "",
        "lastChecked": trade.get("lastChecked") or "",
        "markHistory": [
            {"at": point.get("at"), "mark": point.get("mark"), "stock": point.get("stock")}
            for point in (trade.get("markHistory") or ensure_history(dict(trade)))
        ],
        "probableNews": bool(trade.get("probableNews")),
    }


def _summary(open_count: int, realized: float, open_risk: float, account: float) -> str:
    direction = "up" if realized > 0 else "down" if realized < 0 else "flat"
    return (
        f"Paper account starts at ${account:.0f}. Finished ideas are {direction} ${abs(realized):.0f}. "
        f"{open_count} open idea(s) are using about ${open_risk:.0f}. Open ideas are not counted as profit until they finish."
    )


def compose_review(scorecard: dict, regime: dict, today: date) -> str:
    start = today - timedelta(days=7)
    opened = []
    closed = []
    for trade in scorecard.get("trades", []):
        opened_on = str(trade.get("openedAt") or "")[:10]
        if opened_on and opened_on >= start.isoformat():
            opened.append(trade)
        closed_on = str(trade.get("closedAt") or "")
        if trade.get("status") == "closed" and closed_on >= start.isoformat():
            closed.append(trade)
    wins = [trade for trade in closed if float(trade.get("realizedPnl") or 0) > 0]
    losses = [trade for trade in closed if float(trade.get("realizedPnl") or 0) <= 0]
    dollars = round(sum(float(trade.get("realizedPnl") or 0) for trade in closed), 2)
    if not opened and not closed:
        week = "No paper ideas opened or finished in the last seven days. That is allowed. The desk would rather wait than invent a trade."
    else:
        week = (
            f"In the last seven days the desk opened {len(opened)} paper idea(s) and finished {len(closed)}. "
            f"{len(wins)} finished ahead and {len(losses)} did not. Finished ideas are "
            f"{'up' if dollars > 0 else 'down' if dollars < 0 else 'flat'} ${abs(dollars):.0f}."
        )
    agent_line = "Scout weights are still even because there are not enough finished ideas yet."
    graded = []
    for agent_id, row in (scorecard.get("agentStats") or {}).items():
        total = int(row.get("wins", 0)) + int(row.get("losses", 0))
        if total >= 4:
            graded.append((row["wins"] / total, AGENT_NAMES.get(agent_id, agent_id), row["wins"], total))
    if graded:
        graded.sort(reverse=True)
        _rate, name, wins_n, total = graded[0]
        agent_line = f"{name} has the best paper record so far, right on {wins_n} of {total} finished ideas it liked."
    squeeze = (scorecard.get("setupStats") or {}).get("squeeze") or {}
    squeeze_n = int(squeeze.get("wins", 0)) + int(squeeze.get("losses", 0))
    squeeze_line = ""
    if squeeze_n >= 4 and squeeze["wins"] / squeeze_n < 0.4:
        squeeze_line = " Squeeze setups have not been paying off on paper, so they count less until that changes."
    mood = regime.get("title") or "Market mood is unclear"
    return (
        f"{week} {agent_line} Market mood: {mood}. {regime.get('summary', '')} "
        "Next week, keep each idea inside the small-bet band and skip headlines that are not clearly good or bad news."
        f"{squeeze_line}"
    )


def maybe_review(scorecard: dict, regime: dict, now: datetime, enabled: bool) -> dict:
    ensure_stats(scorecard)
    today = now.astimezone(_zone(now)).date() if now.tzinfo else now.date()
    if not enabled:
        if scorecard["reviews"]:
            last = dict(scorecard["reviews"][-1])
            last["paused"] = True
            return last
        return {
            "weekOf": today.isoformat(),
            "note": "Weekly review is turned off. Nothing new will be written until you turn it on.",
            "paused": True,
        }
    need = not scorecard["reviews"]
    if scorecard["reviews"]:
        last_day = date.fromisoformat(scorecard["reviews"][-1]["weekOf"])
        if (today - last_day).days >= 7 or (today.weekday() == 4 and last_day != today):
            need = True
    if not need:
        return scorecard["reviews"][-1]
    note = compose_review(scorecard, regime, today)
    entry = {"weekOf": today.isoformat(), "note": note, "paused": False}
    scorecard["reviews"].append(entry)
    scorecard["reviews"] = scorecard["reviews"][-12:]
    return entry


def _zone(now: datetime):
    return now.tzinfo
