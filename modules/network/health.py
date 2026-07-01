"""NETWORK / COMMS health scoring — single-entity penalty model (the per-shuttle comms link).

health = clamp(100 - Σ capped_penalties, 0, 100). Penalties on the per-shuttle network downtime%:

  downtime_abs    — downtime% above a fleet-normal floor (the core comms signal).
  downtime_peer_z — robust z of downtime% vs the fleet, gated by a minimum absolute downtime (so a
                    fleet-median link is never flagged just for tiny deviations).
  recent_spike    — today's downtime% above a floor AND worse than the window average (degrading NOW).
  recurrence      — prior runs whose downtime% was elevated (store-driven, downtime-specific).

No cycle counter, so RUL is time/recurrence-based: cold-start uses a coarse band by tier; trend
(>=5 runs) fits the link's health trajectory over accumulated runs. An aisle-clustering post-pass adds
an aisle-level comms/AP/controller cross-flag when downtime clusters on one aisle. Shared tiering + trend
+ RUL machinery keeps the methodology consistent (methodology.md).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.network.rca import aisle_cluster_flags, build_rca
from modules.network.spec import thresholds

log = get_logger("network.health")

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


def _recurrence(hist: List[Dict[str, Any]], min_downtime_pct: float) -> int:
    """Prior runs whose downtime% was elevated — downtime-specific, so peer-z/recency artifacts do
    not self-reinforce into a compounding recurrence penalty."""
    n = 0
    for h in hist:
        m = h.get("metrics_json") or {}
        try:
            if float(m.get("downtime_pct") or 0.0) >= min_downtime_pct:
                n += 1
        except (TypeError, ValueError):
            continue
    return n


def _score_link(feat, hist, t, tiers, conf_cfg, bands, min_runs) -> ComponentHealth:
    p = t["penalties"]
    floor = float(t.get("downtime_abs_floor_pct", 3.0))
    peer_z_min = float(t.get("peer_z_min_downtime_pct", 4.0))
    recent_floor = float(t.get("recent_spike_floor_pct", 5.0))
    recur_min = float(t.get("recur_min_downtime_pct", 6.0))

    downtime = float(feat.get("downtime_pct", 0.0))
    today_dt = feat.get("today_downtime_pct")
    today_delta = feat.get("today_delta_pct")
    recurrence = _recurrence(hist, recur_min)

    # peer_z only bites when the link has a materially-elevated downtime (not just above a tight median).
    peer_z_eff = feat.get("downtime_peer_z", 0.0) if downtime >= peer_z_min else 0.0
    # recent spike only when TODAY is both elevated AND worse than the window average (accelerating).
    recent_val = 0.0
    if today_dt is not None and today_delta is not None and today_delta > 0:
        recent_val = float(today_dt) - recent_floor

    penalties = {
        "downtime_abs": _capped(downtime - floor, **p["downtime_abs"]),
        "downtime_peer_z": _capped(peer_z_eff, **p["downtime_peer_z"]),
        "recent_spike": _capped(recent_val, **p["recent_spike"]),
        "recurrence": _capped(recurrence, **p["recurrence"]),
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
        conf = min(0.92, conf_cfg["coldstart_base"] + 0.25 * min(1.0, downtime / 10.0)
                   + (0.1 if feat.get("today_disclosed") else 0.0) + (0.1 if hist else 0.0))

    primary, rca = build_rca(feat, penalties, recurrence, tier)
    metrics = dict(feat)
    metrics.update({
        "runs_observed": len(hist),
        "recurrence_runs": recurrence,
        "penalties": {k: round(v, 2) for k, v in penalties.items()},
        "penalty_total": round(total_pen, 2),
    })
    return ComponentHealth(
        component_id=feat["component_id"], component_type="network_link", health_score=health,
        risk_tier=tier, predicted_ttm_hours=ttm, confidence=conf,
        prediction_regime=regime, primary_cause=primary, rca=rca, metrics=metrics,
    )


def score(features: Dict[str, Dict[str, Any]], history: HistoryReader) -> List[ComponentHealth]:
    t = thresholds()
    tiers = t["tiers"]
    conf_cfg = t["confidence"]
    bands = t.get("ttm_bands_hours", {"critical": 48, "warn": 240, "watch": 720})
    min_runs = int(t.get("history_min_runs_for_trend", 5))

    out: List[ComponentHealth] = []
    for cid, feat in features.items():
        hist = history.component_history("network", cid, limit=400)
        out.append(_score_link(feat, hist, t, tiers, conf_cfg, bands, min_runs))

    # aisle-clustering post-pass: flag an aisle-level comms/AP/controller common cause.
    aisle_cluster_flags(out, features,
                        aisle_downtime_pct=float(t.get("aisle_cluster_downtime_pct", 6.0)),
                        min_links=int(t.get("aisle_cluster_min_links", 2)))

    out.sort(key=lambda c: c.health_score)
    log.info("network health scored",
             extra={"links": len(out), "worst": out[0].component_id if out else None,
                    "worst_score": out[0].health_score if out else None,
                    "flagged": sum(1 for c in out if c.risk_tier != "ok")})
    return out
