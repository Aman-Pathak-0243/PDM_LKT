"""CONTROLLER / COMPUTE health scoring — per compute node.

health = clamp(100 - Σ capped_penalties, 0, 100). Penalties on CPU utilization%:

  saturation     — utilization% above a fleet-normal floor (the core signal; healthy headroom below it).
  sustained_high — consecutive recent runs with utilization% >= sustained_high_pct (store-driven
                   persistence — a controller pinned near saturation run-after-run is a crash/throttle
                   precursor, not a transient spike).

The feed is a current-state snapshot with no in-feed trend, so RUL is time/store-based: cold-start uses
a coarse band by tier; trend (>=5 runs) fits the node's health trajectory over accumulated runs and
projects when it crosses the critical line. A saturated controller starves the WES, so the RCA raises a
system-wide 'meta' cross-flag at warn+ (the hook for the meta-module).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.controller.rca import build_rca
from modules.controller.spec import thresholds

log = get_logger("controller.health")

CRITICAL_SCORE = 40.0


def _capped(value: float, weight: float, cap: float) -> float:
    return float(min(max(value, 0.0) * weight, cap))


def _tier(score: float, t: Dict[str, float]) -> str:
    if score >= t.get("ok", 85):
        return "ok"
    if score >= t.get("watch", 65):
        return "watch"
    if score >= t.get("warn", 40):
        return "warn"
    return "critical"


def _trend(hist: List[Dict[str, Any]], score: float, min_runs: int):
    pts = []
    for row in hist:
        try:
            ts = _dt.datetime.fromisoformat(row["created_at"]).timestamp() / 3600.0
            pts.append((ts, float(row["health_score"])))
        except (TypeError, ValueError, KeyError):
            continue
    if len(pts) < min_runs:
        return None, False
    xs = np.array([q[0] for q in pts]); ys = np.array([q[1] for q in pts])
    if float(np.ptp(xs)) < 1e-9:            # degenerate x (shared timestamps) -> can't project RUL
        return (0.0 if score <= CRITICAL_SCORE else None), True
    slope = np.polyfit(xs - xs.min(), ys, 1)[0]  # health per hour
    if slope < -1e-4 and score > CRITICAL_SCORE:
        return min(float((score - CRITICAL_SCORE) / (-slope)), 24 * 365.0), True
    if score <= CRITICAL_SCORE:
        return 0.0, True
    return None, True


def _consecutive_high(feat: Dict[str, Any], hist: List[Dict[str, Any]], high_pct: float) -> int:
    """Consecutive most-recent runs (incl. now) with utilization% >= high_pct."""
    if float(feat.get("utilization_pct", 0.0)) < high_pct:
        return 0
    consec = 1
    for h in hist:
        try:
            if float((h.get("metrics_json") or {}).get("utilization_pct") or 0.0) >= high_pct:
                consec += 1
            else:
                break
        except (TypeError, ValueError):
            break
    return consec


def score(features: Dict[str, Dict[str, Any]], history: HistoryReader) -> List[ComponentHealth]:
    t = thresholds()
    p = t["penalties"]
    tiers = t["tiers"]
    conf_cfg = t["confidence"]
    bands = t.get("ttm_bands_hours", {"critical": 24, "warn": 96, "watch": 336})
    min_runs = int(t.get("history_min_runs_for_trend", 5))
    floor = float(t.get("saturation_floor_pct", 60.0))
    high_pct = float(t.get("sustained_high_pct", 80.0))
    sql_dominant = float(t.get("sql_dominant_share", 0.85))
    meta_tier = str(t.get("meta_flag_tier", "warn"))

    out: List[ComponentHealth] = []
    for cid, feat in features.items():
        hist = history.component_history("controller", cid, limit=400)
        util = float(feat.get("utilization_pct", 0.0))
        consec_high = _consecutive_high(feat, hist, high_pct)

        penalties = {
            "saturation": _capped(util - floor, **p["saturation"]),
            "sustained_high": _capped(max(consec_high - 1, 0), **p["sustained_high"]),
        }
        total_pen = sum(penalties.values())
        health = max(0.0, 100.0 - total_pen)
        tier = _tier(health, tiers)

        ttm, used_trend = _trend(hist, health, min_runs)
        if used_trend:
            regime = "trend"
            conf = min(0.97, conf_cfg["trend_base"] + 0.2 * min(1.0, len(hist) / (3 * min_runs)))
        else:
            regime = "coldstart"
            ttm = bands.get(tier)
            conf = min(0.9, conf_cfg["coldstart_base"] + 0.25 * min(1.0, util / 100.0) + (0.1 if hist else 0.0))

        primary, rca = build_rca(feat, penalties, consec_high, tier,
                                 sql_dominant_share=sql_dominant, meta_tier=meta_tier)
        metrics = dict(feat)
        metrics.update({
            "runs_observed": len(hist),
            "consecutive_high": consec_high,
            "penalties": {k: round(v, 2) for k, v in penalties.items()},
            "penalty_total": round(total_pen, 2),
        })
        out.append(ComponentHealth(
            component_id=cid, component_type="compute_node", health_score=health, risk_tier=tier,
            predicted_ttm_hours=ttm, confidence=conf, prediction_regime=regime,
            primary_cause=primary, rca=rca, metrics=metrics,
        ))

    out.sort(key=lambda c: c.health_score)
    log.info("controller health scored",
             extra={"nodes": len(out), "worst": out[0].component_id if out else None,
                    "worst_score": out[0].health_score if out else None,
                    "flagged": sum(1 for c in out if c.risk_tier != "ok")})
    return out
