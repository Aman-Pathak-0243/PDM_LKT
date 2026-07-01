"""CONVEYOR health scoring — per-zone score, tier, TTM, confidence, regime.

Penalty model on congestion (start 100, subtract capped penalties). No cycle
counter and no discrete fault events, so RUL is time-based: cold-start uses a
coarse band by tier; the trend regime projects the zone's congestion/health
trajectory over accumulated runs.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.conveyor.rca import build_rca
from modules.conveyor.spec import spec, thresholds

log = get_logger("conveyor.health")

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


def _penalties(f: Dict[str, Any], p: Dict[str, Any], peak_ref: float,
               buffer_normal: float, idle_cfg: Dict[str, float]) -> Dict[str, float]:
    # Stall detection: a seized belt shows ZERO congestion, so congestion penalties
    # miss it entirely. Penalise a zone that sits idle far more than normal — but only
    # when it is anomalous vs peers (idle_peer_z >= gate), so a plant-wide quiet period
    # (all zones idle, z→0) never manufactures a false stall flag.
    idle_normal = float(idle_cfg.get("idle_normal", 0.4))
    idle_z_gate = float(idle_cfg.get("idle_z_gate", 1.0))
    idle_excess = max(f.get("idle_share", 0.0) - idle_normal, 0.0)
    stall_gate = 1.0 if f.get("idle_peer_z", 0.0) >= idle_z_gate else 0.0
    return {
        "congestion_excess": _capped(f.get("congestion_mean", 0.0) - 1.0, **p["congestion_excess"]),
        "severe_saturation": _capped(f.get("severe_saturation_share", 0.0), **p["severe_saturation"]),
        "peak_excess": _capped(f.get("congestion_peak", 0.0) - peak_ref, **p["peak_excess"]),
        "buffer_congestion": _capped(f.get("buffer_congestion_mean", 0.0) - buffer_normal, **p["buffer_congestion"]),
        "congestion_peer_z": _capped(f.get("congestion_peer_z", 0.0), **p["congestion_peer_z"]),
        # Sustained (90th-pct) congestion catches a zone that runs high most of the
        # window even when the mean lands modestly above 1.0.
        "sustained_congestion": _capped(f.get("congestion_p90", 0.0) - 1.0, **p["sustained_congestion"]),
        "stall_idle": _capped(idle_excess * stall_gate, **p["stall_idle"]),
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
    bands = t.get("ttm_bands_hours", {"critical": 24, "warn": 96, "watch": 336})
    peak_ref = float(t.get("peak_ref", 2.0))
    buffer_normal = float(t.get("buffer_normal", 0.3))
    idle_cfg = t.get("idle", {"idle_normal": 0.4, "idle_z_gate": 1.0})
    min_runs = int(t.get("history_min_runs_for_trend", 5))

    out: List[ComponentHealth] = []
    for cid, f in features.items():
        penalties = _penalties(f, pen_cfg, peak_ref, buffer_normal, idle_cfg)
        total = sum(penalties.values())
        health = max(0.0, 100.0 - total)
        tier = _tier(health, tiers)

        hist = history.component_history("conveyor", cid, limit=300)
        data_factor = min(1.0, f.get("samples", 0) / max(conf_cfg["min_samples_full"], 1))
        ttm, used_trend = _trend(hist, health, min_runs)
        if used_trend:
            regime = "trend"
            conf = min(0.97, conf_cfg["trend_base"] + 0.2 * min(1.0, len(hist) / (3 * min_runs)))
            conf = conf * (0.6 + 0.4 * data_factor)
        else:
            regime = "coldstart"
            ttm = bands.get(tier)
            conf = min(0.85, conf_cfg["coldstart_base"] + 0.4 * data_factor + (0.1 if hist else 0.0))

        primary, rca = build_rca(f, penalties, peak_ref)
        metrics = dict(f)
        metrics["penalties"] = {k: round(v, 2) for k, v in penalties.items()}
        metrics["penalty_total"] = round(total, 2)

        out.append(ComponentHealth(
            component_id=cid, component_type="zone", health_score=health, risk_tier=tier,
            predicted_ttm_hours=ttm, confidence=conf, prediction_regime=regime,
            primary_cause=primary, rca=rca, metrics=metrics,
        ))

    out.sort(key=lambda c: c.health_score)
    log.info("conveyor health scored",
             extra={"zones": len(out), "worst": out[0].component_id if out else None,
                    "worst_score": out[0].health_score if out else None})
    return out
