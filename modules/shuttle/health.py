"""SHUTTLE health scoring — score, tier, cycles-based RUL, confidence, regime.

Penalty model (start 100, subtract weighted/capped penalties). The shuttle's
distinguishing feature is **cycles-based RUL**: once enough run history has
accumulated, the model fits health vs cumulative cycles to get cycles-to-threshold,
then converts to hours using the recent cycle-accrual rate (Δcycles/Δtime).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.shuttle.rca import build_rca
from modules.shuttle.spec import spec, thresholds

log = get_logger("shuttle.health")

CRITICAL_SCORE = 40.0
COLDSTART_BANDS = {"critical": 48.0, "warn": 240.0, "watch": 720.0, "ok": None}


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


def _penalties(f: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, float]:
    return {
        "epc_peer_z": _capped(f.get("epc_peer_z", 0.0), **p["epc_peer_z"]),
        # epc may be None (shuttle absent from the CYCLES roster) -> 0 here, so a
        # cycle-less shuttle is scored on its other signals, not a fabricated rate.
        "epc_abs": _capped(f.get("errors_per_mcycle") or 0.0, **p["epc_abs"]),
        "severity": _capped(f.get("severity_mean", 0.0), **p["severity"]),
        "mechanical": _capped(f.get("mechanical_share", 0.0), **p["mechanical"]),
        "recurrence": _capped(max(f.get("recurrence_max", 0) - 2, 0), **p["recurrence"]),
        "diversity": _capped(max(f.get("distinct_types", 0) - 2, 0), **p["diversity"]),
        "reshuffle_excess": _capped(f.get("reshuffle_excess", 0.0), **p["reshuffle_excess"]),
        # Current bad-tracker penalises the binary current pick-error STATE (like the
        # Lift module's current_error), not a raw event count.
        "current_badtracker": _capped(1.0 if f.get("current_pick_error") else 0.0, **p["current_badtracker"]),
        "current_alert": _capped(1.0 if f.get("current_alert") else 0.0, **p["current_alert"]),
        # Only the EXCESS of today's errors over the window count (avoids double-
        # counting errors already scored by epc/severity/recurrence).
        "current_daily": _capped(f.get("current_daily_excess", 0), **p["current_daily"]),
    }


def _trend_rul(history: List[Dict[str, Any]], score: float, min_runs: int):
    """Return (ttm_hours, ttm_cycles, ok) using health-vs-cumulative-cycles."""
    pts = []  # (cumulative_cycles, health, time_hours)
    for row in history:
        try:
            cyc = float((row.get("metrics_json") or {}).get("total_cycles"))
            h = float(row["health_score"])
            t = _dt.datetime.fromisoformat(row["created_at"]).timestamp() / 3600.0
            pts.append((cyc, h, t))
        except (TypeError, ValueError, KeyError):
            continue
    if len(pts) < min_runs:
        return None, None, False
    cyc = np.array([p[0] for p in pts])
    hl = np.array([p[1] for p in pts])
    tm = np.array([p[2] for p in pts])

    def _slope(x, y):
        """Least-squares slope, guarded: None if x has no spread or the fit fails."""
        if float(np.ptp(x)) < 1e-9:
            return None
        try:
            return float(np.polyfit(x - x.min(), y, 1)[0])
        except (np.linalg.LinAlgError, ValueError):
            return None

    # Preferred: health vs CUMULATIVE CYCLES (usage-based RUL).
    slope_hc = _slope(cyc, hl)
    if slope_hc is not None:
        if slope_hc >= -1e-9 or score <= CRITICAL_SCORE:
            return (0.0 if score <= CRITICAL_SCORE else None), None, True
        cycles_to_crit = (score - CRITICAL_SCORE) / (-slope_hc)
        accrual = _slope(tm, cyc)                          # cycles per hour
        ttm_hours = float(cycles_to_crit / accrual) if (accrual and accrual > 1e-9) else None
        if ttm_hours is not None:
            ttm_hours = min(ttm_hours, 24 * 365.0)
        return ttm_hours, float(cycles_to_crit), True

    # Fallback: cumulative cycles are static across snapshots (e.g. a frozen source)
    # but health has a time trajectory -> time-based slope, like the time-only modules,
    # so the trend regime still activates instead of being stuck in cold-start.
    slope_ht = _slope(tm, hl)
    if slope_ht is not None:
        if slope_ht < -1e-4 and score > CRITICAL_SCORE:
            return min(float((score - CRITICAL_SCORE) / (-slope_ht)), 24 * 365.0), None, True
        if score <= CRITICAL_SCORE:
            return 0.0, None, True
        return None, None, True

    # No usable spread in either cycles or time -> stay cold-start.
    return None, None, False


def score(features: Dict[str, Dict[str, Any]], history: HistoryReader) -> List[ComponentHealth]:
    s = spec()
    t = thresholds()
    pen_cfg = t["penalties"]
    tiers = t["tiers"]
    conf_cfg = t["confidence"]
    min_runs = int(t.get("history_min_runs_for_trend", 5))

    out: List[ComponentHealth] = []
    for sid, f in features.items():
        penalties = _penalties(f, pen_cfg)
        total = sum(penalties.values())
        health = max(0.0, 100.0 - total)
        tier = _tier(health, tiers)

        hist = history.component_history("shuttle", sid, limit=300)
        data_factor = min(1.0, f.get("error_count", 0) / max(conf_cfg["min_errors_full"], 1))
        cycles_known = 1.0 if f.get("total_cycles", 0) > 0 else 0.0

        ttm_hours, ttm_cycles, used_trend = _trend_rul(hist, health, min_runs)
        if used_trend:
            regime = "trend"
            conf = min(0.97, conf_cfg["trend_base"] + 0.2 * min(1.0, len(hist) / (3 * min_runs)))
            conf = conf * (0.6 + 0.4 * data_factor)
        else:
            regime = "coldstart"
            ttm_hours = COLDSTART_BANDS[tier]
            ttm_cycles = None
            conf = conf_cfg["coldstart_base"] + 0.25 * data_factor + 0.15 * cycles_known + (0.1 if hist else 0.0)
            conf = min(0.85, conf)

        primary, rca = build_rca(f, penalties)
        metrics = dict(f)
        metrics["penalties"] = {k: round(v, 2) for k, v in penalties.items()}
        metrics["penalty_total"] = round(total, 2)
        metrics["predicted_ttm_cycles"] = round(ttm_cycles, 0) if ttm_cycles is not None else None

        out.append(ComponentHealth(
            component_id=sid, component_type="shuttle", health_score=health, risk_tier=tier,
            predicted_ttm_hours=ttm_hours, confidence=conf, prediction_regime=regime,
            primary_cause=primary, rca=rca, metrics=metrics,
        ))

    out.sort(key=lambda c: c.health_score)
    log.info("shuttle health scored",
             extra={"shuttles": len(out), "worst": out[0].component_id if out else None,
                    "worst_score": out[0].health_score if out else None})
    return out
