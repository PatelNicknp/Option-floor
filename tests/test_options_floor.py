"""Offline tests. No network."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from pipeline.config import load_config
from pipeline.engine import keep_last_good, run_from_bundle
from pipeline.http_client import attempt
from pipeline.market_math import payoff_rows, pick_option, realized_vol, size_trade, sma, trend_label
from pipeline.models import Bundle, Equity, NewsItem, OptionContract, SymbolInfo
from pipeline.price_check import build_price_checks, percentile_below
from pipeline.parsers import parse_finra_short_volume, parse_fomc_dates, parse_nasdaq_listed, parse_feed
from pipeline.scorecard import empty_scorecard, mark_trades, record_ideas
from pipeline.textutil import build_index, catalyst_scores, match_tickers, sentiment_counts, strip_publisher
from pipeline.agents import devil_vote

TODAY = date(2026, 11, 5)
NOW = datetime(2026, 11, 5, 23, 30, tzinfo=timezone.utc)  # 6:30 p.m. Eastern in November


def test_sma_and_trend_and_vol():
    closes = [10 + index * 0.05 for index in range(220)]
    assert sma(closes, 10) is not None
    assert sma(closes, 500) is None
    label, phrase = trend_label(closes)
    assert label == "up"
    assert "up" in phrase.lower()
    down = list(reversed(closes))
    assert trend_label(down)[0] == "down"
    assert realized_vol(closes, 20) is not None


def test_size_trade_band():
    assert size_trade(0.50, 800, 40, 80) == 1
    assert size_trade(0.20, 800, 40, 80) == 3
    assert size_trade(0.85, 800, 40, 80) is None
    assert size_trade(0.60, 500, 40, 80) is None
    assert size_trade(0, 800, 40, 80) is None


def test_payoff_call_and_put():
    rows = {row["pct"]: row for row in payoff_rows("call", 20, 0.50, 1, 20)}
    assert rows[20]["stock"] == 24
    assert rows[20]["value"] == 400
    assert rows[20]["pnl"] == 350
    assert rows[-20]["pnl"] == -50
    put_rows = {row["pct"]: row for row in payoff_rows("put", 20, 0.50, 1, 20)}
    assert put_rows[-20]["value"] == 400
    assert put_rows[20]["value"] == 0


def test_catalyst_and_sentiment_word_boundaries():
    bull, bear = catalyst_scores("Acme raises guidance after a strong quarter")
    assert bull >= 3
    assert bear == 0
    bull, bear = catalyst_scores("The mission statement is on the site")
    assert bear == 0
    positive, negative = sentiment_counts("This was not a strong quarter")
    assert negative >= 1
    assert positive == 0


def test_ticker_match_prefers_company_and_skips_price_target():
    symbols = {
        "SOFI": SymbolInfo("SOFI", "SoFi Technologies, Inc. Common Stock", "SOFI"),
        "TGT": SymbolInfo("TGT", "Target Corporation", "TGT"),
        "F": SymbolInfo("F", "Ford Motor Company Common Stock", "F"),
        "AAPL": SymbolInfo("AAPL", "Apple Inc. Common Stock", "AAPL"),
        "XYZ": SymbolInfo("XYZ", "Xyzzy Holdings Inc.", "XYZ"),
    }
    index = build_index(symbols)
    assert match_tickers("SoFi raises guidance for 2026", index) == ["SOFI"]
    assert match_tickers("Analyst lifts price target after the sector rally", index) == []
    assert match_tickers("Ford recalls trucks after a fire", index) == ["F"]
    assert match_tickers("Apple beats estimates", index) == ["AAPL"]
    assert match_tickers("Nothing to see at $XYZ today", index) == ["XYZ"]


def test_generic_words_do_not_attach_a_policy_headline_to_a_fund():
    symbols = {
        "CPER": SymbolInfo("CPER", "United States Commodity Index Funds Trust", "CPER"),
        "AWR": SymbolInfo("AWR", "American States Water Company Common Stock", "AWR"),
        "ILPT": SymbolInfo("ILPT", "Industrial Logistics Properties Trust Common Shares", "ILPT"),
        "UAMY": SymbolInfo("UAMY", "United States Antimony Corporation Common Stock", "UAMY"),
    }
    index = build_index(symbols)
    headline = "ADJUSTING IMPORTS OF ROBOTICS, INDUSTRIAL MACHINERY, AND THEIR PARTS AND COMPONENTS INTO THE UNITED STATES"
    assert match_tickers(headline, index) == []
    assert match_tickers("Industrial Logistics raises guidance", index) == ["ILPT"]


def test_ordinary_english_does_not_become_a_ticker():
    symbols = {
        "BEAT": SymbolInfo("BEAT", "HeartBeam, Inc.", "BEAT"),
        "APWC": SymbolInfo("APWC", "Asia Pacific Wire & Cable Corporation Limited Common shares", "APWC"),
        "OFRM": SymbolInfo("OFRM", "Once Upon a Farm, PBC Common Stock", "OFRM"),
        "TCBX": SymbolInfo("TCBX", "Third Coast Bancshares, Inc. Common Stock", "TCBX"),
        "SGRY": SymbolInfo("SGRY", "Surgery Partners, Inc. Common Stock", "SGRY"),
        "ARRY": SymbolInfo("ARRY", "Array Technologies, Inc. Common Stock", "ARRY"),
        "INO": SymbolInfo("INO", "Inovio Pharmaceuticals, Inc. Common Stock", "INO"),
    }
    index = build_index(symbols)
    assert match_tickers("Nifty Bounces Back to Beat All of Asia on Foreign Flows, Earnings", index) == []
    assert match_tickers("FDA Approves Once-Weekly Generic Hormone Therapy Patch for Women", index) == []
    assert match_tickers("Patients with Rectal Cancer to Avoid Surgery", index) == []
    assert match_tickers("ARRAY Technologies Reports Financial Results for the Third Quarter 2026", index) == ["ARRY"]
    assert match_tickers("Inovio shares surge after an FDA approval", index) == ["INO"]


def test_publisher_suffix_and_scientific_words_are_not_companies():
    symbols = {
        "FOA": SymbolInfo("FOA", "Finance of America Companies Inc. Class A Common Stock", "FOA"),
        "INO": SymbolInfo("INO", "Inovio Pharmaceuticals, Inc. Common Stock", "INO"),
        "DNA": SymbolInfo("DNA", "Ginkgo Bioworks Holdings, Inc. Class A Common Stock", "DNA"),
        "CHGA": SymbolInfo("CHGA", "Change Agents Corporation Common Stock", "CHGA"),
    }
    index = build_index(symbols)
    title = strip_publisher(
        "Update: Inovio Shares Surge After an Upgrade Following FDA Approval - Yahoo! Finance Canada"
    )
    assert match_tickers(title, index) == ["INO"]
    assert match_tickers("FDA Approves First Plasmid DNA-Based Immunotherapy", index) == []
    assert match_tickers("The bull case could change following an FDA approval", index) == []


def test_short_title_case_words_and_law_firm_ads():
    from pipeline.textutil import is_noise_headline

    symbols = {
        "FICO": SymbolInfo("FICO", "Fair Isaac Corporation Common Stock", "FICO"),
        "PLCE": SymbolInfo("PLCE", "The Children's Place, Inc. Common Stock", "PLCE"),
        "SOFI": SymbolInfo("SOFI", "SoFi Technologies, Inc. Common Stock", "SOFI"),
    }
    index = build_index(symbols)
    assert match_tickers("Is the stock still below Fair Value?", index) == []
    assert match_tickers("FDA Approves a Heart Valve Designed to Grow with Children", index) == []
    assert match_tickers("SoFi raises guidance", index) == ["SOFI"]
    assert is_noise_headline("BAC Investors Have Opportunity to Lead Bank of America Corporation Securities Fraud Lawsuit")
    assert is_noise_headline(
        "DraftKings Investigation Notice: Levi & Korsinsky Notifies Investors of Pending Investigation Into DraftKings (DKNG)"
    )
    names = {
        "QUBT": SymbolInfo("QUBT", "Quantum Computing Inc. Common Stock", "QUBT"),
        "IONQ": SymbolInfo("IONQ", "IonQ, Inc. Common Stock", "IONQ"),
    }
    quantum = build_index(names)
    assert match_tickers("IonQ Partners with QuantumCT to Expand Quantum Computing Access Across Connecticut", quantum) == ["IONQ"]
    assert match_tickers("Quantum Computing Inc raises guidance", quantum) == ["QUBT"]


def test_nasdaq_and_finra_and_rss_parsers():
    listed = parse_nasdaq_listed(
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "AAAP|Pacer Something ETF|G|N|N|100|Y|N\n"
        "SOFI|SoFi Technologies, Inc. Common Stock|Q|N|N|100|N|N\n"
        "TEST|Test Issue|G|Y|N|100|N|N\n"
        "BAD|Bad Co Warrant|G|N|N|100|N|N\n"
    )
    assert list(listed) == ["SOFI"]
    ratios = parse_finra_short_volume(
        "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market\n"
        "20261104|SOFI|40|0|100|Q\n"
        "20261104|SOFI|10|0|100|N\n"
    )
    assert round(ratios["SOFI"], 2) == 0.25
    feed = parse_feed(
        b"""<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>SoFi raises guidance</title><link>https://example.com/sofi</link>
        <pubDate>Wed, 04 Nov 2026 15:00:00 GMT</pubDate><description>Beat &amp; raise</description></item>
        </channel></rss>""",
        "google",
    )
    assert feed[0].title == "SoFi raises guidance"
    assert feed[0].url == "https://example.com/sofi"
    assert "Beat" in feed[0].summary
    fomc = parse_fomc_dates("2024 January 30-31 meeting. 2026 March 17-18 meeting.", 2026)
    years = {item.published.year for item in fomc if item.published}
    assert years == {2024, 2026}


def test_pick_option_rejects_wide_market_and_can_choose_a_leap():
    today = TODAY
    junk = OptionContract("JUNK", "call", 22, today + timedelta(days=30), 0.10, 0.70, 0.40, 10, 20, 0.9)
    near = OptionContract("NEAR", "call", 22, today + timedelta(days=30), 0.40, 0.46, 0.43, 100, 800, 0.5)
    leap = OptionContract("LEAP", "call", 24, today + timedelta(days=400), 0.52, 0.58, 0.55, 50, 4000, 0.45)
    far = OptionContract("FAR", "call", 40, today + timedelta(days=40), 0.05, 0.08, 0.06, 10, 100, 1.2)
    chosen = pick_option([junk, near, leap, far], 20, "call", 0.80, today)
    assert chosen is not None
    assert chosen.symbol in {"NEAR", "LEAP"}
    assert chosen.ask <= 0.80
    only_leap = pick_option([junk, near, leap], 20, "call", 0.80, today, leaps_only=True)
    assert only_leap is not None and only_leap.symbol == "LEAP"
    assert pick_option([junk, far], 20, "call", 0.80, today) is None


def _equity(price_path: list[float], name: str = "SoFi Technologies, Inc. Common Stock") -> Equity:
    start = TODAY - timedelta(days=len(price_path))
    bars = []
    for index, close in enumerate(price_path):
        bars.append((start + timedelta(days=index), close))
    return Equity(symbol="SOFI", name=name, price=price_path[-1], bars=bars)


def _bundle(equity: Equity, contract: OptionContract, headline: str, vix: float = 15, short: float = 0.2) -> Bundle:
    up = [400 + index * 0.4 for index in range(220)]
    item = NewsItem(title=headline, url="https://news.example/sofi", source="google", published=NOW, tickers=["SOFI"])
    return Bundle(
        now=NOW,
        items=[item],
        symbols={"SOFI": SymbolInfo("SOFI", equity.name, "SOFI")},
        quotes={"SOFI": equity},
        chains={"SOFI": [contract]},
        short_ratios={"SOFI": short},
        earnings=[],
        spy_closes=up,
        vix=vix,
        source_health=[{"id": "google_news", "label": "Google News", "ok": True, "detail": "1 headlines"}],
    )


def test_engine_builds_a_buy_call_and_records_it():
    closes = [10 + index * 0.05 for index in range(220)]
    equity = _equity(closes)
    contract = OptionContract("SOFI261218C00022000", "call", 22, date(2026, 12, 18), 0.48, 0.52, 0.50, 400, 5000, 0.55)
    report, book = run_from_bundle(_bundle(equity, contract, "SoFi raises guidance after a record quarter"), load_config("config.json"), empty_scorecard())
    assert report["ideas"], report["skipped"]
    idea = report["ideas"][0]
    assert idea["action"] == "BUY CALL"
    assert idea["ticker"] == "SOFI"
    assert idea["contract"]["strike"] == 22
    assert idea["contract"]["expiry"] == "2026-12-18"
    assert 40 <= idea["spend"] <= 80
    assert idea["confidence"] in {"High", "Medium", "Low"}
    assert idea["news"]["url"].startswith("https://")
    assert any(vote["id"] == "head" and vote["vote"] == "yes" for vote in idea["agents"])
    assert idea["payoff"]["rows"]
    assert idea["chart"]["points"]
    assert "delta" not in idea["reason"].lower()
    assert book["trades"][0]["status"] == "open"
    assert report["regime"]["mood"] == "calm-uptrend"
    assert report["runLabel"] == "After the close"


def test_engine_skips_when_a_source_style_failure_leaves_no_chain():
    closes = [10 + index * 0.05 for index in range(220)]
    bundle = _bundle(_equity(closes), OptionContract("X", "call", 22, date(2026, 12, 18), 0.48, 0.52, 0.5, 10, 100, 0.4), "SoFi raises guidance")
    bundle.chains = {}
    bundle.source_health.append({"id": "yahoo_options", "label": "Yahoo option chains", "ok": False, "detail": "Skipped. down"})
    report, _book = run_from_bundle(bundle, load_config("config.json"), empty_scorecard())
    assert report["ideas"] == []
    assert any("option chain" in row["reason"].lower() for row in report["skipped"])


def test_earnings_within_two_days_are_rejected():
    closes = [10 + index * 0.05 for index in range(220)]
    equity = _equity(closes)
    equity.earnings_date = TODAY + timedelta(days=1)
    contract = OptionContract("SOFI261218C00022000", "call", 22, date(2026, 12, 18), 0.48, 0.52, 0.50, 400, 5000, 0.55)
    # The bundle clock is Nov 5 UTC, which is still Nov 5 in New York during the evening... 18:30 UTC is 13:30 ET.
    report, _book = run_from_bundle(_bundle(equity, contract, "SoFi raises guidance again"), load_config("config.json"), None)
    assert report["ideas"] == []
    assert any("earnings" in row["reason"].lower() for row in report["skipped"])


def test_put_idea_in_a_fear_tape():
    closes = [30 - index * 0.05 for index in range(220)]
    equity = _equity(closes, "Acme Motors Inc. Common Stock")
    equity.symbol = "ACME"
    contract = OptionContract("ACME261218P00020000", "put", 20, date(2026, 12, 18), 0.40, 0.46, 0.43, 300, 2000, 0.6)
    item_title = "Acme cuts guidance and discloses an SEC charges filing"
    bundle = _bundle(equity, contract, item_title, vix=28, short=0.1)
    bundle.quotes = {"ACME": equity}
    bundle.chains = {"ACME": [contract]}
    bundle.short_ratios = {"ACME": 0.1}
    bundle.items[0].tickers = ["ACME"]
    bundle.symbols = {"ACME": SymbolInfo("ACME", equity.name, "ACME")}
    down = [500 - index * 0.8 for index in range(220)]
    bundle.spy_closes = down
    report, book = run_from_bundle(bundle, load_config("config.json"), empty_scorecard())
    assert report["ideas"], report["skipped"]
    assert report["ideas"][0]["action"] == "BUY PUT"
    assert report["regime"]["mood"] == "fear"
    assert book["trades"]


def test_scorecard_sells_half_at_a_double_then_stops_the_rest():
    book = empty_scorecard()
    idea = {
        "id": "SOFI-call-22-2026-12-18",
        "action": "BUY CALL",
        "ticker": "SOFI",
        "company": "SoFi",
        "contract": {"symbol": "SOFI261218C00022000", "expiry": "2026-12-18", "strike": 22},
        "side": "call",
        "entry": {"mid": 0.30},
        "contracts": 2,
        "agents": [{"id": "news", "vote": "yes"}, {"id": "chart", "vote": "no"}],
        "tags": ["cheap"],
        "lastExitDate": "2026-12-01",
        "reason": "test",
        "news": {"url": "https://example.com"},
        "confidence": "Low",
    }
    # size is 2 only if we force the idea; record_ideas trusts the idea.
    record_ideas(book, [idea], "2026-11-05T18:30:00+00:00")
    mark_trades(book, {"SOFI261218C00022000": 0.60}, date(2026, 11, 6))
    trade = book["trades"][0]
    assert trade["halfClosed"] is True
    assert trade["remainingContracts"] == 1
    assert trade["status"] == "open"
    assert trade["realizedPnl"] == 30
    mark_trades(book, {"SOFI261218C00022000": 0.10}, date(2026, 11, 7))
    assert trade["status"] == "closed"
    assert trade["outcome"] == "stop"
    assert trade["realizedPnl"] == 10
    assert book["agentStats"]["news"]["wins"] == 1
    assert book["agentStats"]["chart"]["wins"] == 0
    assert book["agentStats"]["news"]["weight"] == 1.0  # still under 4 graded votes


def test_one_contract_closes_when_it_doubles():
    book = empty_scorecard()
    idea = {
        "id": "SOFI-call",
        "action": "BUY CALL",
        "ticker": "SOFI",
        "company": "SoFi",
        "contract": {"symbol": "C", "expiry": "2026-12-18", "strike": 22},
        "side": "call",
        "entry": {"mid": 0.40},
        "contracts": 1,
        "agents": [{"id": "news", "vote": "yes"}],
        "tags": [],
        "lastExitDate": "2026-12-01",
        "reason": "test",
        "news": {"url": ""},
        "confidence": "Low",
    }
    record_ideas(book, [idea], "2026-11-05T00:00:00+00:00")
    mark_trades(book, {"C": 0.90}, date(2026, 11, 10))
    assert book["trades"][0]["status"] == "closed"
    assert book["trades"][0]["outcome"] == "target"
    assert book["trades"][0]["realizedPnl"] == 50


def test_failed_sources_do_not_stop_the_next_one_and_stale_ideas_can_remain():
    health = []
    assert attempt(health, "sec", "SEC filings", lambda: (_ for _ in ()).throw(RuntimeError("down")), []) == []
    assert attempt(health, "fed", "Federal Reserve", lambda: ["ok"], []) == ["ok"]
    assert health[0]["ok"] is False
    assert health[1]["ok"] is True
    previous = {
        "generatedAt": "2026-11-04T18:30:00-05:00",
        "ideas": [{"ticker": "SOFI", "action": "BUY CALL"}],
    }
    fresh = {
        "generatedAt": "2026-11-05T18:30:00-05:00",
        "ideas": [],
        "sourceHealth": [
            {"ok": False, "label": "A"},
            {"ok": False, "label": "B"},
            {"ok": False, "label": "C"},
            {"ok": True, "label": "D"},
        ],
        "banner": "",
        "stale": False,
    }
    merged = keep_last_good(fresh, previous, datetime(2026, 11, 5, 23, 30, tzinfo=timezone.utc))
    assert merged["stale"] is True
    assert merged["ideas"][0]["ticker"] == "SOFI"
    assert "last good run" in merged["banner"]


def test_devil_blocks_a_pile_of_problems():
    equity = _equity([20] * 40)
    equity.earnings_date = TODAY + timedelta(days=3)
    equity.bars = [(TODAY - timedelta(days=2), 10), (TODAY - timedelta(days=1), 12), (TODAY, 20)]
    contract = OptionContract("C", "call", 22, TODAY + timedelta(days=20), 0.20, 0.55, 0.3, 5, 12, 2.5)
    vote, block = devil_vote("call", equity, contract, [], "down", "put", TODAY)
    assert block is True
    assert vote.vote == "no"


def test_price_check_keeps_the_nearest_quoted_strikes_and_a_year_rank():
    closes = [20 + ((index % 9) - 4) * 0.15 for index in range(120)]
    equity = _equity(closes)
    equity.price = 10
    equity.earnings_date = TODAY + timedelta(days=9)
    contracts = []
    for strike in range(1, 21):
        contracts.append(OptionContract(f"C{strike}", "call", float(strike), TODAY + timedelta(days=30), 0.40, 0.48, 0.44, 10, 100 + strike, 0.55))
    contracts.append(OptionContract("C10B", "call", 10, TODAY + timedelta(days=30), 0.41, 0.47, 0.44, 10, 5000, 0.55))
    contracts.append(OptionContract("NOBID", "call", 10, TODAY + timedelta(days=30), 0, 0.40, 0.20, 10, 9000, 0.55))
    contracts.append(OptionContract("PUT", "put", 10, TODAY + timedelta(days=30), 0.30, 0.36, 0.33, 10, 80, 0.50))
    board = build_price_checks(_bundle(equity, contracts[0], "SoFi raises guidance"), TODAY)
    # The helper bundle only has the first contract. Build from a chain we control.
    bundle = _bundle(equity, contracts[0], "SoFi raises guidance")
    bundle.chains = {"SOFI": contracts}
    bundle.quotes = {"SOFI": equity}
    saved = build_price_checks(bundle, TODAY)
    assert saved[0]["ticker"] == "SOFI"
    assert saved[0]["earningsDate"] == (TODAY + timedelta(days=9)).isoformat()
    assert saved[0]["hv20"] is not None
    calls = saved[0]["expirations"][0]["calls"]
    assert [row["strike"] for row in calls] == list(range(3, 18))
    ten = next(row for row in calls if row["strike"] == 10)
    assert ten["oi"] == 5000
    assert ten["ivPercentile"] == 100
    assert saved[0]["expirations"][0]["puts"][0]["strike"] == 10
    assert board  # the single quoted contract still produces a board


def test_price_check_drops_past_earnings_and_can_be_turned_off_without_changing_the_idea():
    closes = [10 + index * 0.05 for index in range(220)]
    equity = _equity(closes)
    equity.earnings_date = TODAY - timedelta(days=2)
    contract = OptionContract("SOFI261218C00022000", "call", 22, date(2026, 12, 18), 0.48, 0.52, 0.50, 400, 5000, 0.55)
    bundle = _bundle(equity, contract, "SoFi raises guidance after a record quarter")
    saved = build_price_checks(bundle, TODAY)
    assert saved[0]["earningsDate"] is None
    assert saved[0]["expirations"][0]["calls"][0]["strike"] == 22
    config = load_config("config.json")
    assert config["features"]["priceCheck"] is True
    on_report, _book = run_from_bundle(bundle, config, empty_scorecard())
    assert on_report["ideas"][0]["action"] == "BUY CALL"
    assert on_report["priceChecks"][0]["ticker"] == "SOFI"
    config["features"]["priceCheck"] = False
    off_report, _book = run_from_bundle(bundle, config, empty_scorecard())
    assert off_report["ideas"][0]["action"] == "BUY CALL"
    assert off_report["ideas"][0]["contract"]["strike"] == on_report["ideas"][0]["contract"]["strike"]
    assert off_report["priceChecks"] == []


def test_percentile_below_needs_a_real_history():
    assert percentile_below([0.2] * 40, 0.5) == 100
    assert percentile_below([0.2] * 40, 0.1) == 0
    assert percentile_below([0.2] * 10, 0.5) is None
    assert percentile_below([], 0.5) is None


def test_a_failed_run_keeps_the_last_price_check_with_the_last_ideas():
    previous = {
        "generatedAt": "2026-11-04T18:30:00-05:00",
        "ideas": [{"ticker": "SOFI", "action": "BUY CALL"}],
        "priceChecks": [{"ticker": "SOFI"}],
    }
    fresh = {
        "generatedAt": "2026-11-05T18:30:00-05:00",
        "ideas": [],
        "priceChecks": [],
        "sourceHealth": [{"ok": False, "label": "A"}, {"ok": False, "label": "B"}, {"ok": False, "label": "C"}],
        "banner": "",
        "stale": False,
    }
    merged = keep_last_good(fresh, previous, datetime(2026, 11, 5, 23, 30, tzinfo=timezone.utc))
    assert merged["stale"] is True
    assert merged["priceChecks"] == [{"ticker": "SOFI"}]


def test_news_scout_can_be_turned_off_without_losing_the_idea():
    closes = [10 + index * 0.05 for index in range(220)]
    equity = _equity(closes)
    contract = OptionContract("SOFI261218C00022000", "call", 22, date(2026, 12, 18), 0.48, 0.52, 0.50, 400, 5000, 0.55)
    config = load_config("config.json")
    config["features"]["news"] = False
    report, _book = run_from_bundle(_bundle(equity, contract, "SoFi raises guidance after a record quarter"), config, empty_scorecard())
    assert report["ideas"]
    assert all(vote["id"] != "news" for vote in report["ideas"][0]["agents"])


# --- Open-trade history, price-first, wires, and probable news ---------------------------------

from pipeline.live import parse_calendar_events, parse_spark, price_first_list, wire_tickers  # noqa: E402
from pipeline.scorecard import ensure_history, public_scorecard  # noqa: E402
from pipeline.textutil import infer_kind, lean_direction, propose_direction  # noqa: E402


def _simple_idea(price=21.5):
    return {
        "id": "SOFI-call-22-2026-12-18",
        "action": "BUY CALL",
        "ticker": "SOFI",
        "company": "SoFi",
        "price": price,
        "contract": {"symbol": "SOFI261218C00022000", "expiry": "2026-12-18", "strike": 22},
        "side": "call",
        "entry": {"mid": 0.40},
        "contracts": 1,
        "agents": [{"id": "news", "vote": "yes"}],
        "tags": [],
        "lastExitDate": "2026-12-01",
        "reason": "test",
        "news": {"url": ""},
        "confidence": "Low",
    }


def test_new_trades_store_entry_stock_price_and_a_history_that_grows_each_run():
    book = empty_scorecard()
    record_ideas(book, [_simple_idea()], "2026-11-05T18:30:00-05:00")
    trade = book["trades"][0]
    assert trade["stockAtEntry"] == 21.5
    assert trade["markHistory"] == [{"at": "2026-11-05T18:30:00-05:00", "mark": 0.40, "stock": 21.5}]
    mark_trades(book, {"SOFI261218C00022000": 0.55}, date(2026, 11, 6), stocks={"SOFI": 22.4}, at="2026-11-06T10:15:00-05:00")
    mark_trades(book, {"SOFI261218C00022000": 0.62}, date(2026, 11, 6), stocks={"SOFI": 22.9}, at="2026-11-06T18:30:00-05:00")
    # Same run twice does not add a duplicate point.
    mark_trades(book, {"SOFI261218C00022000": 0.62}, date(2026, 11, 6), stocks={"SOFI": 22.9}, at="2026-11-06T18:30:00-05:00")
    marks = [point["mark"] for point in trade["markHistory"]]
    assert marks == [0.40, 0.55, 0.62]
    assert trade["lastStock"] == 22.9
    public = public_scorecard(book, 800)["open"][0]
    assert public["stockAtEntry"] == 21.5
    assert public["lastStock"] == 22.9
    assert len(public["markHistory"]) == 3
    assert public["side"] == "call"


def test_old_trades_get_a_history_from_stored_prices_only():
    old = {
        "id": "FIS-put-25-2027-01-15",
        "ticker": "FIS",
        "action": "BUY PUT",
        "openedAt": "2026-11-05T16:28:59-05:00",
        "entry": 0.525,
        "lastMark": 0.65,
        "lastChecked": "2026-11-10",
        "status": "open",
    }
    history = ensure_history(old)
    assert history == [
        {"at": "2026-11-05T16:28:59-05:00", "mark": 0.525, "stock": None},
        {"at": "2026-11-10", "mark": 0.65, "stock": None},
    ]
    same_day = {"openedAt": "2026-11-10T10:00:00-05:00", "entry": 0.5, "lastMark": 0.5, "lastChecked": "2026-11-10"}
    assert len(ensure_history(same_day)) == 1
    # An unpriced run keeps the history as is, and never stores a stock price that was not fetched.
    book = {"trades": [dict(old, contractSymbol="FIS270115P00025000", remainingContracts=1, expiry="2027-01-15", lastExitDate="2027-01-01")]}
    mark_trades(book, {}, date(2026, 11, 11))
    assert len(book["trades"][0]["markHistory"]) == 2
    assert "lastStock" not in book["trades"][0]


def test_history_is_capped_but_keeps_the_entry_point():
    book = empty_scorecard()
    record_ideas(book, [_simple_idea()], "2026-11-05T18:30:00-05:00")
    for step in range(10):
        mark_trades(book, {"SOFI261218C00022000": 0.41 + step * 0.01}, date(2026, 11, 6), at=f"run-{step}", history_max=5)
    history = book["trades"][0]["markHistory"]
    assert len(history) == 5
    assert history[0]["mark"] == 0.40
    assert history[-1]["at"] == "run-9"


def test_price_first_puts_in_range_names_ahead_of_big_names():
    config = load_config("config.json")
    config["maxCandidateTickers"] = 4
    ranked = ["NVDA", "AMD", "SOFI", "XYZ", "BB", "HOOD", "NEWCO"]
    quick = {"NVDA": 176.0, "AMD": 562.0, "SOFI": 16.4, "XYZ": 3.1, "BB": 9.6, "HOOD": 62.0}
    chosen, skips = price_first_list(ranked, quick, config)
    assert chosen == ["SOFI", "BB", "HOOD", "NEWCO"]
    assert skips == {"NVDA": 176.0, "AMD": 562.0, "XYZ": 3.1}
    config["priceMax"] = 20
    config["allowHigherPriceIfCheapLeap"] = False
    chosen, skips = price_first_list(ranked, quick, config)
    assert "HOOD" not in chosen and "HOOD" in skips


def test_engine_reports_price_first_skips():
    closes = [10 + index * 0.05 for index in range(220)]
    contract = OptionContract("SOFI261218C00022000", "call", 22, date(2026, 12, 18), 0.48, 0.52, 0.50, 400, 5000, 0.55)
    bundle = _bundle(_equity(closes), contract, "SoFi raises guidance after a record quarter")
    bundle.price_skips = {"NVDA": 176.26}
    report, _book = run_from_bundle(bundle, load_config("config.json"), empty_scorecard())
    assert any(row["ticker"] == "NVDA" and "outside" in row["reason"] for row in report["skipped"])
    assert report["universe"]["priceChecked"] == 2


def test_parse_spark_and_calendar_events():
    payload = {
        "BRK-B": {"close": [583.2], "chartPreviousClose": 580.0},
        "BB": {"close": [None, 9.62]},
        "OLD": {"close": [], "chartPreviousClose": 4.5},
        "DEAD": {"close": []},
    }
    prices = parse_spark(payload, {"BRK-B": "BRK.B", "BB": "BB"})
    assert prices == {"BRK.B": 583.2, "BB": 9.62, "OLD": 4.5}
    events = {"quoteSummary": {"result": [{"calendarEvents": {"earnings": {"earningsDate": [{"raw": 1797541200}, {"raw": 1797800000}]}}}]}}
    assert parse_calendar_events(events) == date(2026, 12, 17)
    assert parse_calendar_events({"quoteSummary": {"result": []}}) is None


def test_wire_tickers_read_exchange_tags():
    body = "TORONTO, Nov. 11, 2026 /PRNewswire/ - Kinross Gold Corporation (TSX: K) (NYSE: KGC) and Acme Bio (NASDAQ: ACMB) today said"
    assert wire_tickers(body) == ["KGC", "ACMB"]
    assert wire_tickers("Berkshire (NYSE: BRK.B) and Foo (Nasdaq GS: FOOO)") == ["BRK.B", "FOOO"]
    assert wire_tickers("No tags here") == []
    assert infer_kind("fda", "Family Farmstead Dairy Announces Recall - U.S. Food and Drug Administration") == "fda"


def test_lean_direction_only_fills_in_when_the_strong_check_is_empty():
    # One small positive catalyst: the strong check says no, the lean check says call.
    assert propose_direction(1, 0, 1, 0) is None
    assert lean_direction(1, 0, 1, 0) == "call"
    assert lean_direction(0, 1, 0, 1) == "put"
    assert lean_direction(0, 0, 2, 0) == "call"
    assert lean_direction(0, 0, 0, 3) == "put"
    assert lean_direction(1, 1, 1, 1) is None
    assert lean_direction(1, 0, 0, 2) is None
    assert lean_direction(0, 0, 1, 0) is None


def test_probable_news_idea_is_capped_at_low_and_can_be_switched_off():
    closes = [10 + index * 0.05 for index in range(220)]
    contract = OptionContract("SOFI261218C00022000", "call", 22, date(2026, 12, 18), 0.48, 0.52, 0.50, 400, 5000, 0.55)
    headline = "SoFi announces partnership with a regional bank"
    config = load_config("config.json")
    assert config["acceptProbableNews"] is True
    report, book = run_from_bundle(_bundle(_equity(closes), contract, headline), config, empty_scorecard())
    assert report["ideas"], report["skipped"]
    idea = report["ideas"][0]
    assert idea["confidence"] == "Low"
    assert idea["probableNews"] is True
    assert "probable-news" in idea["tags"]
    assert book["trades"][0]["probableNews"] is True
    config["acceptProbableNews"] = False
    report, _book = run_from_bundle(_bundle(_equity(closes), contract, headline), config, empty_scorecard())
    assert report["ideas"] == []


def test_strong_news_is_not_marked_probable():
    closes = [10 + index * 0.05 for index in range(220)]
    contract = OptionContract("SOFI261218C00022000", "call", 22, date(2026, 12, 18), 0.48, 0.52, 0.50, 400, 5000, 0.55)
    report, _book = run_from_bundle(_bundle(_equity(closes), contract, "SoFi raises guidance after a record quarter"), load_config("config.json"), empty_scorecard())
    assert report["ideas"][0]["probableNews"] is False
    assert "probable-news" not in report["ideas"][0]["tags"]


def test_new_config_keys_have_defaults():
    from pipeline.config import DEFAULT_CONFIG

    for key in ("priceFirst", "priceScanTickers", "acceptProbableNews", "earningsBackupTickers", "markHistoryMax"):
        assert key in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["acceptProbableNews"] is True
