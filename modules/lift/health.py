"""LIFT health scoring — per-lift score, risk tier, TTM, confidence, regime.

Penalty model (methodology.md §2): start at 100 and subtract weighted, capped
penalties for each unhealthy signal. The tier follows the score; time-to-maintenance
uses a coarse tier band in the cold-start regime and a fitted health-trajectory
slope once enough run history exists.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.lift.rca import build_rca
from modules.lift.spec import spec, thresholds

log = get_logger("lift.health")

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


def _penalties(feat: Dict[str, Any], p: Dict[str, Any], vgate: float) -> Dict[str, float]:
    # Volume-gate the intensity RATIOS (severity, mechanical share) by a saturating
    # factor of the fault count, so a single stale event (share=1.0) cannot alone
    # drive a lift to WARN; a lift needs a few faults before its severity/mechanical
    # mix is trusted at full weight. (Rate signals are already volume-aware.)
    n = float(feat.get("error_count", 0) or 0)
    vf = min(1.0, n / vgate) if vgate > 0 else 1.0
    return {
        "rate_peer_z": _capped(feat.get("rate_peer_z", 0.0), **p["rate_peer_z"]),
        "abs_rate": _capped(feat.get("error_rate_per_day", 0.0), **p["abs_rate"]),
        "severity": _capped(feat.get("severity_mean", 0.0) * vf, **p["severity"]),
        "mechanical": _capped(feat.get("mechanical_share", 0.0) * vf, **p["mechanical"]),
        "recurrence": _capped(max(feat.get("recurrence_max", 0) - 2, 0), **p["recurrence"]),
        "diversity": _capped(max(feat.get("distinct_codes", 0) - 2, 0), **p["diversity"]),
        "current_error": _capped(1.0 if feat.get("current_error_status") else 0.0, **p["current_error"]),
    }


def _ttm_and_confidence(
    feat: Dict[str, Any],
    score: float,
    tier: str,
    history: List[Dict[str, Any]],
    conf_cfg: Dict[str, Any],
    min_runs_trend: int,
) -> tuple:
    """Return (predicted_ttm_hours, confidence, regime)."""
    n_hist = len(history)
    data_factor = min(1.0, feat.get("error_count", 0) / max(conf_cfg["min_errors_full"], 1))

    # Trend regime: enough history AND a usable declining slope.
    if n_hist >= min_runs_trend:
        pts = []
        for row in history:
            try:
                t = _dt.datetime.fromisoformat(row["created_at"]).timestamp() / 3600.0
                pts.append((t, float(row["health_score"])))
            except (TypeError, ValueError, KeyError):
                continue
        if len(pts) >= min_runs_trend:
            xs = np.array([p[0] for p in pts])
            ys = np.array([p[1] for p in pts])
            slope = None
            # Guard the fit: identical timestamps (e.g. a same-second backfill) give
            # zero x-spread and np.polyfit raises LinAlgError; fall through to
            # cold-start rather than crashing the whole run.
            if float(np.ptp(xs)) >= 1e-9:
                try:
                    slope = np.polyfit(xs - xs.min(), ys, 1)[0]  # points per hour
                except (np.linalg.LinAlgError, ValueError):
                    slope = None
            if slope is not None:
                if slope < -1e-4 and score > CRITICAL_SCORE:
                    ttm = float((score - CRITICAL_SCORE) / (-slope))
                    ttm = min(ttm, 24 * 365.0)  # cap at one year
                elif score <= CRITICAL_SCORE:
                    ttm = 0.0
                else:
                    ttm = None  # stable/improving
                # Confidence rises with history depth + data sufficiency.
                conf = conf_cfg["trend_base"] + 0.2 * min(1.0, n_hist / (3 * min_runs_trend))
                conf = min(0.97, conf * (0.6 + 0.4 * data_factor))
                return ttm, conf, "trend"

    # Cold-start regime: coarse tier band, low confidence.
    band = {"critical": 24.0, "warn": 96.0, "watch": 336.0, "ok": None}[tier]
    conf = conf_cfg["coldstart_base"] + 0.35 * data_factor + (0.1 if n_hist else 0.0)
    return band, min(0.85, conf), "coldstart"


def score(features: Dict[str, Dict[str, Any]], history: HistoryReader) -> List[ComponentHealth]:
    s = spec()
    t = thresholds()
    pen_cfg = t["penalties"]
    tiers = t["tiers"]
    conf_cfg = t["confidence"]
    min_runs_trend = int(t.get("history_min_runs_for_trend", 5))
    vgate = float(t.get("intensity_volume_gate_errors", 5))

    out: List[ComponentHealth] = []
    for lid, feat in features.items():
        penalties = _penalties(feat, pen_cfg, vgate)
        total = sum(penalties.values())
        health = max(0.0, 100.0 - total)
        tier = _tier(health, tiers)

        hist = history.component_history("lift", lid, limit=300)
        ttm, conf, regime = _ttm_and_confidence(
            feat, health, tier, hist, conf_cfg, min_runs_trend
        )
        primary, rca = build_rca(feat, penalties)
        # Store the penalty breakdown alongside the features for transparency.
        metrics = dict(feat)
        metrics["penalties"] = {k: round(v, 2) for k, v in penalties.items()}
        metrics["penalty_total"] = round(total, 2)

        out.append(
            ComponentHealth(
                component_id=lid,
                component_type="lift",
                health_score=health,
                risk_tier=tier,
                predicted_ttm_hours=ttm,
                confidence=conf,
                prediction_regime=regime,
                primary_cause=primary,
                rca=rca,
                metrics=metrics,
            )
        )

    out.sort(key=lambda c: c.health_score)
    log.info(
        "lift health scored",
        extra={"lifts": len(out), "worst": out[0].component_id if out else None,
               "worst_score": out[0].health_score if out else None},
    )
    return out
