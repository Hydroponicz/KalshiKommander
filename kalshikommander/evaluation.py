"""Forward-test evaluation: timestamped predictions vs separately recorded settlements.

Only decisions recorded BEFORE the market's close time are scored (one per ticker: the last
such decision), so information from after the close cannot leak in. There is no historical
backtest: this app has no point-in-time archive of past quotes/forecasts, and reconstructing
them from later data would be look-ahead.
"""

from __future__ import annotations

import json
import math

from .contracts import parse_contract
from .storage import Store
from .timeutil import parse_ts

MIN_MEANINGFUL_N = 100


def scored_predictions(store: Store) -> list[dict]:
    rows = store.all(
        "SELECT d.*, s.result, s.recorded_at settled_at, m.market_json, m.event_json, m.series_json "
        "FROM decisions d JOIN settlements s ON s.ticker = d.ticker "
        "JOIN market_snapshots m ON m.id = d.market_snapshot_id "
        "WHERE d.p_yes IS NOT NULL ORDER BY d.created_at, d.id")
    best: dict[str, dict] = {}
    for r in rows:
        c = parse_contract(json.loads(r["market_json"]), json.loads(r["event_json"] or "{}"),
                           json.loads(r["series_json"] or "{}"))
        created = parse_ts(r["created_at"])
        if c.close_time is None or created >= c.close_time:
            continue  # not a genuine pre-close prediction
        best[r["ticker"]] = {"ticker": r["ticker"], "created_at": r["created_at"], "p_yes": r["p_yes"],
                             "market_mid_yes": r["market_mid_yes"], "y": 1 if r["result"] == "yes" else 0,
                             "action": r["action"], "is_sample": r["is_sample"]}
    return list(best.values())


def brier(ps: list[float], ys: list[int]) -> float | None:
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps) if ps else None


def log_loss(ps: list[float], ys: list[int], eps: float = 1e-6) -> float | None:
    if not ps:
        return None
    return -sum(y * math.log(max(eps, p)) + (1 - y) * math.log(max(eps, 1 - p)) for p, y in zip(ps, ys)) / len(ps)


def calibration_bins(ps: list[float], ys: list[int], n_bins: int = 10) -> list[dict]:
    bins = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        idx = [j for j, p in enumerate(ps) if lo <= p < hi or (i == n_bins - 1 and p == 1.0)]
        if idx:
            bins.append({"range": f"{lo:.1f}-{hi:.1f}", "n": len(idx),
                         "mean_pred": sum(ps[j] for j in idx) / len(idx),
                         "observed": sum(ys[j] for j in idx) / len(idx)})
    return bins


def evaluate(store: Store) -> dict:
    preds = scored_predictions(store)
    ps = [p["p_yes"] for p in preds]
    ys = [p["y"] for p in preds]
    with_mid = [p for p in preds if p["market_mid_yes"] is not None]
    res = {
        "n": len(preds),
        "model_brier": brier(ps, ys),
        "model_log_loss": log_loss(ps, ys),
        "n_with_market_mid": len(with_mid),
        "model_brier_on_mid_subset": brier([p["p_yes"] for p in with_mid], [p["y"] for p in with_mid]),
        "market_mid_brier": brier([p["market_mid_yes"] for p in with_mid], [p["y"] for p in with_mid]),
        "calibration": calibration_bins(ps, ys),
        "predictions": preds,
        "warnings": [],
    }
    if len(preds) < MIN_MEANINGFUL_N:
        res["warnings"].append(f"Only {len(preds)} settled predictions; fewer than {MIN_MEANINGFUL_N} is far too few "
                               "to claim calibration or an edge.")
    if any(p["is_sample"] for p in preds):
        res["warnings"].append("Includes SAMPLE (fictional) data - not evidence of anything.")
    res["warnings"].append("Historical backtest not possible: no point-in-time archive of past quotes/forecasts "
                           "exists here, and rebuilding one from later data would leak future information.")
    return res
