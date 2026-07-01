"""TRACKER health scoring — per grid-location score, tier, TTM, confidence, regime.

Penalty model on the bad-tracker cluster (start 100, subtract capped penalties).
This is an anomaly/recurrence module: there is no cycle counter and the Bad Tracker
panel is current-state, so the leading signal is how many totes a position currently
mislocates, how recent they are, and — crucially — how often the position RECURS
across PdM runs. Recurrence/persistence come from the longitudinal store, so the
prediction sharpens from coarse cold-start bands to a trend-based RUL as runs accrue.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.tracker.rca import build_rca
from modules.tracker.spec import thresholds

log = get_logger("tracker.health")

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


def _penalties(f: Dict[str, Any], p: Dict[str, Any], recurrence_runs: int) -> Dict[str, float]:
    return {
        # Disjoint stale vs recent so the SAME tote is not penalised twice: cluster
        # scores the older (stale) stuck totes, recent_cluster scores active ones.
        # peer_z (a deviation signal, capped modestly) then layers on top rather than
        # re-counting the cluster a third time.
        "cluster": _capped(f.get("bad_count", 0) - f.get("recent_bad_count", 0), **p["cluster"]),
        "recent_cluster": _capped(f.get("recent_bad_count", 0), **p["recent_cluster"]),
        "recurrence": _capped(recurrence_runs, **p["recurrence"]),
        "multi_shuttle": _capped(f.get("distinct_shuttles", 0) - 1, **p["multi_shuttle"]),
        "lift_involved": _capped(f.get("lift_error_count", 0), **p["lift_involved"]),
        "peer_z": _capped(f.get("bad_count_peer_z", 0.0), **p["peer_z"]),
    }


def _trend(history: List[Dict[str, Any]], score: float, min_runs: int):
    pts = []
    for row in history:
        try:
            t = _dt.datetime.fromisoformat(row["created_at"]).timestamp() / 3600.0
            pts.append((t, float(row["health_score"])))
        except (TypeError, ValueError, KeyError):
            continue
    if len(pts) < min_runs:
        return None, False
    xs = np.array([p[0] for p in pts]); ys = np.array([p[1] for p in pts])
    if float(np.ptp(xs)) < 1e-9:      # identical timestamps -> polyfit would raise
        return (0.0 if score <= CRITICAL_SCORE else None), True
    try:
        slope = np.polyfit(xs - xs.min(), ys, 1)[0]  # health per hour
    except (np.linalg.LinAlgError, ValueError):
        return (0.0 if score <= CRITICAL_SCORE else None), True
    if slope < -1e-4 and score > CRITICAL_SCORE:
        return min(float((score - CRITICAL_SCORE) / (-slope)), 24 * 365.0), True
    if score <= CRITICAL_SCORE:
        return 0.0, True
    return None, True


def score(features: Dict[str, Dict[str, Any]], history: HistoryReader) -> List[ComponentHealth]:
    t = thresholds()
    pen_cfg = t["penalties"]
    tiers = t["tiers"]
    conf_cfg = t["confidence"]
    bands = t.get("ttm_bands_hours", {"critical": 48, "warn": 240, "watch": 720})
    min_runs = int(t.get("history_min_runs_for_trend", 5))

    out: List[ComponentHealth] = []
    for cid, f in features.items():
        hist = history.component_history("tracker", cid, limit=300)
        recurrence_runs = len(hist)  # prior runs this position appeared bad (longitudinal)

        penalties = _penalties(f, pen_cfg, recurrence_runs)
        total = sum(penalties.values())
        health = max(0.0, 100.0 - total)
        tier = _tier(health, tiers)

        ttm, used_trend = _trend(hist, health, min_runs)
        if used_trend:
            regime = "trend"
            conf = min(0.97, conf_cfg["trend_base"] + 0.2 * min(1.0, len(hist) / (3 * min_runs)))
        else:
            regime = "coldstart"
            ttm = bands.get(tier)
            # confidence rises with cluster size (more evidence) + any history.
            evidence = min(1.0, f.get("bad_count", 0) / 4.0)
            conf = min(0.85, conf_cfg["coldstart_base"] + 0.3 * evidence + (0.12 if hist else 0.0))

        primary, rca = build_rca(f, penalties, recurrence_runs)
        metrics = dict(f)
        metrics["recurrence_runs"] = recurrence_runs
        metrics["penalties"] = {k: round(v, 2) for k, v in penalties.items()}
        metrics["penalty_total"] = round(total, 2)

        out.append(ComponentHealth(
            component_id=cid, component_type="position_sensor", health_score=health,
            risk_tier=tier, predicted_ttm_hours=ttm, confidence=conf,
            prediction_regime=regime, primary_cause=primary, rca=rca, metrics=metrics,
        ))

    out.sort(key=lambda c: c.health_score)
    log.info("tracker health scored",
             extra={"locations": len(out), "worst": out[0].component_id if out else None,
                    "worst_score": out[0].health_score if out else None})
    return out
