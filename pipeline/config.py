"""Job settings. The website can download a replacement for this file."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

FEATURE_KEYS = (
    "news",
    "policy",
    "sentiment",
    "chart",
    "options",
    "risk",
    "devil",
    "head",
    "calendar",
    "cheap",
    "payoff",
    "flow",
    "squeeze",
    "underpriced",
    "priceCheck",
    "sizing",
    "scorecard",
    "mood",
    "review",
)

DEFAULT_CONFIG: dict = {
    "account": 800,
    "minSpend": 40,
    "maxSpend": 80,
    "maxOpen": 5,
    "maxPremium": 0.80,
    "minOpenInterest": 50,
    "priceMin": 5,
    "priceMax": 40,
    "allowHigherPriceIfCheapLeap": True,
    "higherPriceMax": 80,
    "maxCandidateTickers": 36,
    "maxChainTickers": 18,
    "headlineBatch": 15,
    "requestPauseSeconds": 0.4,
    "earningsDays": 6,
    "priceFirst": True,
    "priceScanTickers": 160,
    "acceptProbableNews": True,
    "earningsBackupTickers": 20,
    "markHistoryMax": 120,
    "features": {key: True for key in FEATURE_KEYS},
}


def feature_on(config: dict, key: str) -> bool:
    features = config.get("features") or {}
    if key not in features:
        return True
    return bool(features[key])


def load_config(path: str | Path) -> dict:
    cfg = deepcopy(DEFAULT_CONFIG)
    file_path = Path(path)
    if file_path.exists():
        loaded = json.loads(file_path.read_text(encoding="utf-8"))
        _merge(cfg, loaded)
    cfg["features"] = {key: bool((cfg.get("features") or {}).get(key, True)) for key in FEATURE_KEYS}
    cfg["account"] = float(cfg["account"])
    cfg["minSpend"] = float(cfg["minSpend"])
    cfg["maxSpend"] = float(cfg["maxSpend"])
    cfg["maxOpen"] = int(cfg["maxOpen"])
    cfg["maxPremium"] = float(cfg["maxPremium"])
    cfg["minOpenInterest"] = int(cfg["minOpenInterest"])
    cfg["priceMin"] = float(cfg["priceMin"])
    cfg["priceMax"] = float(cfg["priceMax"])
    cfg["higherPriceMax"] = float(cfg["higherPriceMax"])
    cfg["maxCandidateTickers"] = int(cfg["maxCandidateTickers"])
    cfg["maxChainTickers"] = int(cfg["maxChainTickers"])
    cfg["headlineBatch"] = int(cfg["headlineBatch"])
    cfg["requestPauseSeconds"] = float(cfg["requestPauseSeconds"])
    cfg["earningsDays"] = int(cfg["earningsDays"])
    cfg["priceFirst"] = bool(cfg["priceFirst"])
    cfg["priceScanTickers"] = int(cfg["priceScanTickers"])
    cfg["acceptProbableNews"] = bool(cfg["acceptProbableNews"])
    cfg["earningsBackupTickers"] = int(cfg["earningsBackupTickers"])
    cfg["markHistoryMax"] = int(cfg["markHistoryMax"])
    return cfg


def _merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key == "features" and isinstance(value, dict):
            base["features"].update(value)
        else:
            base[key] = value
