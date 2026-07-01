"""GATE health scoring — per-gate score, tier, TTM, confidence, regime.

Penalty model (start 100, subtract capped penalties). Gate is a current-state +
latency + recurrence module (no cycle counter, no discrete fault log). The leading
signals are: how long a gate is stuck non-closed right now (response latency), whether
it is caught mid-actuation (OPEN REQUEST INITIATED), and — from the longitudinal store —
how persistently/often it is non-closed or stuck versus its own past and versus peer
gates. Cold-start leans on the within-snapshot signals; as runs accrue, persistence,
recurrence and peer deviation sharpen the verdict and a trend-based RUL becomes possible.
"""

from __future__ import annotations

import datetime as _dt
from statistics import median
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.gate.rca import build_rca
from modules.gate.spec import thresholds

log = get_logger("gate.health")

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


def _prior_stats(feat: Dict[str, Any], hist: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Longitudinal stats from prior component_health rows (newest-first)."""
    runs = len(hist)
    prior_non_closed = 0
    prior_stuck = 0
    for h in hist:
        m = h.get("metrics_json") or {}
        if bool(m.get("is_non_closed")):
            prior_non_closed += 1
        if float(m.get("stuck_excess_minutes") or 0.0) > 0.0:
            prior_stuck += 1
    # Consecutive runs non-closed INCLUDING the current snapshot (persistence).
    consec = 0
    if feat.get("is_non_closed"):
        consec = 1
        for h in hist:  # newest first
            if bool((h.get("metrics_json") or {}).get("is_non_closed")):
                consec += 1
            else:
                break
    return {
        "runs_observed": runs,
        "prior_non_closed": prior_non_closed,
        "prior_stuck": prior_stuck,
        "non_closed_rate": round(prior_non_closed / runs, 4) if runs else 0.0,
        # Fraction of observed runs the gate was stuck (a RATE, so it decays as the
        # gate recovers — a raw count would hold a recovered gate down forever).
        "stuck_rate": round(prior_stuck / runs, 4) if runs else 0.0,
        "consecutive_non_closed": consec,
    }


def _penalties(feat: Dict[str, Any], prior: Dict[str, Any], p: Dict[str, Any], apply_rate: bool) -> Dict[str, float]:
    return {
        "stuck_latency": _capped(feat.get("stuck_excess_minutes", 0.0), **p["stuck_latency"]),
        "open_request": _capped(1.0 if feat.get("is_open_request") else 0.0, **p["open_request"]),
        "persistence": _capped(max(prior["consecutive_non_closed"] - 1, 0), **p["persistence"]),
        "stuck_recurrence": _capped(prior["stuck_rate"] if apply_rate else 0.0, **p["stuck_recurrence"]),
        "non_closed_rate": _capped(prior["non_closed_rate"] if apply_rate else 0.0, **p["non_closed_rate"]),
        "peer_z": _capped(prior.get("peer_z", 0.0) if apply_rate else 0.0, **p["peer_z"]),
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
    min_runs_trend = int(t.get("history_min_runs_for_trend", 5))
    min_runs_rate = int(t.get("history_min_runs_for_rate", 3))

    # ---- pass 1: prior stats per gate (needed before peer deviation) ------
    priors: Dict[str, Dict[str, Any]] = {}
    hists: Dict[str, List[Dict[str, Any]]] = {}
    for cid, feat in features.items():
        hist = history.component_history("gate", cid, limit=400)
        hists[cid] = hist
        priors[cid] = _prior_stats(feat, hist)

    # Peer baseline of non_closed_rate over gates with enough history.
    rate_pool = [pr["non_closed_rate"] for cid, pr in priors.items()
                 if pr["runs_observed"] >= min_runs_rate]
    for cid, pr in priors.items():
        pr["peer_z"] = round(_robust_z(pr["non_closed_rate"], rate_pool), 3) if len(rate_pool) >= 2 else 0.0

    # ---- pass 2: penalties -> health -> tier -> TTM -> RCA ----------------
    out: List[ComponentHealth] = []
    for cid, feat in features.items():
        prior = priors[cid]
        hist = hists[cid]
        apply_rate = prior["runs_observed"] >= min_runs_rate

        penalties = _penalties(feat, prior, pen_cfg, apply_rate)
        total = sum(penalties.values())
        health = max(0.0, 100.0 - total)
        tier = _tier(health, tiers)

        ttm, used_trend = _trend(hist, health, min_runs_trend)
        if used_trend:
            regime = "trend"
            conf = min(0.97, conf_cfg["trend_base"] + 0.2 * min(1.0, len(hist) / (3 * min_runs_trend)))
        else:
            regime = "coldstart"
            ttm = bands.get(tier)
            # Confidence tracks DATA SUFFICIENCY (prior runs supporting the verdict),
            # NOT the magnitude of the current reading — a loud single snapshot on no
            # history must stay low-confidence (methodology §8).
            depth = min(1.0, prior["runs_observed"] / max(min_runs_rate, 1))
            conf = min(0.85, conf_cfg["coldstart_base"] + 0.33 * depth + (0.05 if hist else 0.0))

        primary, rca = build_rca(feat, prior, penalties)
        metrics = dict(feat)
        metrics.update({
            "runs_observed": prior["runs_observed"],
            "non_closed_rate": prior["non_closed_rate"],
            "prior_stuck_runs": prior["prior_stuck"],
            "consecutive_non_closed": prior["consecutive_non_closed"],
            "non_closed_rate_peer_z": prior["peer_z"],
            "penalties": {k: round(v, 2) for k, v in penalties.items()},
            "penalty_total": round(total, 2),
        })

        out.append(ComponentHealth(
            component_id=cid, component_type="gate", health_score=health,
            risk_tier=tier, predicted_ttm_hours=ttm, confidence=conf,
            prediction_regime=regime, primary_cause=primary, rca=rca, metrics=metrics,
        ))

    out.sort(key=lambda c: c.health_score)
    log.info("gate health scored",
             extra={"gates": len(out), "worst": out[0].component_id if out else None,
                    "worst_score": out[0].health_score if out else None,
                    "flagged": sum(1 for c in out if c.risk_tier != "ok")})
    return out
