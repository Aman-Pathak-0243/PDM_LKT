"""BIN / TOTE-MECHANICAL health scoring — per bin-location score, tier, TTM, confidence, regime.

Penalty model (start 100, subtract capped penalties). A currently-blocked slot is a mild
base concern; the risk escalates with how long the block has stayed unresolved (block-age),
how many totes are blocked there now (cluster), the slot's frozen historical block frequency
(chronic slot), and — the strongest live signal as it accrues — how many prior PdM runs
flagged the same slot (cross-run recurrence from our store). A one-off, freshly-blocked slot
stays near ok; recurring/persistent/chronic slots drive warn/critical ("recurring blocks at
the same location → slot/rail degradation, not random").
"""

from __future__ import annotations

import datetime as _dt
from statistics import median
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.bin_mech.rca import build_rca
from modules.bin_mech.spec import thresholds

log = get_logger("bin_mech.health")

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


def _robust_z(value: float, values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    med = median(values)
    mad = median([abs(v - med) for v in values])
    scale = 1.4826 * mad
    if scale >= 1e-9:
        return (value - med) / scale
    mean = sum(values) / len(values)
    std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    return (value - mean) / std if std >= 1e-9 else 0.0


def _grace_excess(age_hours: float, grace: float) -> float:
    return max(float(age_hours) - grace, 0.0)


def _penalties(f: Dict[str, Any], p: Dict[str, Any], recurrence_runs: int, age_excess: float, peer_z: float) -> Dict[str, float]:
    return {
        "blocked_base": _capped(1.0 if f.get("blocked_now") else 0.0, **p["blocked_base"]),
        "block_age": _capped(age_excess, **p["block_age"]),
        "cluster": _capped(f.get("current_block_count", 1) - 1, **p["cluster"]),
        "historical": _capped(f.get("historical_block_count", 0), **p["historical"]),
        "recurrence": _capped(recurrence_runs, **p["recurrence"]),
        "peer_z": _capped(peer_z, **p["peer_z"]),
    }


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
    if float(np.ptp(xs)) < 1e-9:      # identical timestamps -> polyfit would raise
        return (0.0 if score <= CRITICAL_SCORE else None), True
    try:
        slope = np.polyfit(xs - xs.min(), ys, 1)[0]
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
    grace = float(t.get("block_age_grace_hours", 2))
    peer_z_min_age = float(t.get("peer_z_min_age_hours", 6))
    min_runs = int(t.get("history_min_runs_for_trend", 5))

    # peer baseline of block-age across the currently-blocked slots.
    ages = [float(f.get("block_age_hours", 0.0)) for f in features.values()]

    out: List[ComponentHealth] = []
    for cid, f in features.items():
        hist = history.component_history("bin_mech", cid, limit=400)
        recurrence_runs = len(hist)  # prior runs this slot appeared blocked (longitudinal)
        age_h = float(f.get("block_age_hours", 0.0))
        age_excess = _grace_excess(age_h, grace)
        peer_z = _robust_z(age_h, ages)
        # Gate peer deviation by absolute severity: only let "older than peers" count
        # once the block itself is meaningfully stuck, so a trivially-fresh block that
        # is merely the oldest of a fresh batch is not pushed to watch, while a
        # uniformly old-but-stuck set is still caught by the absolute block_age penalty.
        if age_h < peer_z_min_age:
            peer_z = 0.0

        penalties = _penalties(f, pen_cfg, recurrence_runs, age_excess, peer_z)
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
            evidence = min(1.0, f.get("block_age_hours", 0.0) / 12.0
                           + min(f.get("historical_block_count", 0), 50) / 100.0
                           + (0.2 if recurrence_runs else 0.0))
            conf = min(0.85, conf_cfg["coldstart_base"] + 0.3 * evidence + (0.12 if hist else 0.0))

        primary, rca = build_rca(f, penalties, recurrence_runs)
        metrics = dict(f)
        metrics.update({
            "recurrence_runs": recurrence_runs,
            "block_age_excess_hours": round(age_excess, 2),
            "block_age_peer_z": round(peer_z, 3),
            "penalties": {k: round(v, 2) for k, v in penalties.items()},
            "penalty_total": round(total, 2),
        })

        out.append(ComponentHealth(
            component_id=cid, component_type="bin_location", health_score=health,
            risk_tier=tier, predicted_ttm_hours=ttm, confidence=conf,
            prediction_regime=regime, primary_cause=primary, rca=rca, metrics=metrics,
        ))

    out.sort(key=lambda c: c.health_score)
    log.info("bin_mech health scored",
             extra={"blocked_locations": len(out), "worst": out[0].component_id if out else None,
                    "worst_score": out[0].health_score if out else None,
                    "flagged": sum(1 for c in out if c.risk_tier != "ok")})
    return out
