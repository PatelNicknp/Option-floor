"""Build the Options Floor idea file. This never places a trade."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline.config import feature_on, load_config
from pipeline.engine import run_from_bundle, keep_last_good
from pipeline.http_client import HttpClient
from pipeline.live import build_bundle
from pipeline.scorecard import empty_scorecard, open_trades

ET = ZoneInfo("America/New_York")


def main() -> None:
    parser = argparse.ArgumentParser(description="Options Floor research run. Signals only.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--max-chains", type=int, default=None)
    parser.add_argument("--pause", type=float, default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    if args.max_chains is not None:
        config["maxChainTickers"] = args.max_chains
    if args.pause is not None:
        config["requestPauseSeconds"] = args.pause

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    previous = _read_json(data_dir / "latest.json")
    scorecard = _read_json(data_dir / "scorecard.json") or empty_scorecard()
    now = datetime.now(ET)
    client = HttpClient(pause=float(config["requestPauseSeconds"]))
    print(f"Options Floor run at {now.isoformat()}", flush=True)
    try:
        bundle = build_bundle(client, config, now, open_trades=open_trades(scorecard))
        report, updated = run_from_bundle(bundle, config, scorecard)
        report = keep_last_good(report, previous, now)
    except Exception as exc:  # noqa: BLE001 - last resort so the site still updates
        print(f"Run failed: {exc}", flush=True)
        report = _failure_report(now, exc, previous)
        updated = scorecard
        report = keep_last_good(report, previous, now)

    _write_json(data_dir / "latest.json", report)
    if feature_on(config, "scorecard"):
        _write_json(data_dir / "scorecard.json", updated)
    public = Path("web/public/data")
    public.mkdir(parents=True, exist_ok=True)
    _write_json(public / "latest.json", report)
    if feature_on(config, "scorecard"):
        _write_json(public / "scorecard.json", updated)
    ideas = report.get("ideas") or []
    print(
        f"Done. {len(ideas)} idea(s). "
        + ", ".join(f"{idea['ticker']} {idea['action']}" for idea in ideas[:8]),
        flush=True,
    )
    failed = [row["label"] for row in report.get("sourceHealth") or [] if not row.get("ok")]
    if failed:
        print("Sources skipped: " + ", ".join(failed), flush=True)


def _failure_report(now: datetime, exc: Exception, previous: dict | None) -> dict:
    return {
        "version": 1,
        "generatedAt": now.isoformat(),
        "runLabel": "Manual check",
        "disclaimer": "Options Floor is not a broker and not advice. It never places trades.",
        "banner": f"The research run stopped early ({exc}). No new ideas were built.",
        "stale": False,
        "sourceHealth": [{"id": "run", "label": "Research run", "ok": False, "detail": str(exc)[:300]}],
        "regime": {
            "mood": "unclear",
            "prefer": "wait",
            "title": "Market mood is unclear",
            "summary": "The run stopped before the market check finished.",
            "applied": False,
        },
        "configEcho": {},
        "universe": {"candidates": 0, "priced": 0, "chains": 0},
        "ideas": [],
        "watch": [],
        "skipped": [],
        "catalysts": [],
        "flow": [],
        "squeezes": [],
        "scorecard": (previous or {}).get("scorecard") or {"summary": "No scorecard yet.", "open": [], "closed": [], "agents": []},
        "weeklyReview": {"weekOf": now.date().isoformat(), "note": "The run stopped early, so there is no new weekly note.", "paused": True},
        "xPosts": "X posts are skipped. There is no stable way to read them without a login.",
    }


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    main()
