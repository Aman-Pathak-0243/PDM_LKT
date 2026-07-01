"""SYSTEM-WIDE ANOMALY (META) health scoring — per-scope COMPOUND-RISK (not a re-tally).

health = clamp(100 - Σ capped_penalties, 0, 100). A scope's compound-risk reflects CO-OCCURRENCE +
realized causal chains across modules, NOT the sum of member health (which would double-count each
module's own verdict). Penalties:

  breadth      — distinct modules flagged in the scope beyond the first (>=2 = a compound incident).
  severity     — worst flagged tier, applied ONLY when breadth >= 2 (it amplifies a compound incident,
                 it does not manufacture one from a single module -> no double-count).
  chain        — realized causal edges within the scope (flagged member -> flagged target module).
  persistence  — consecutive prior meta runs this scope was compound (store-driven).
  system only  — controller_trigger (a saturated controller is a system incident on its own) +
                 compound-aisle breadth (how many aisles are simultaneously compound -> systemic).

RUL is store/time-based: cold-start uses a coarse band by tier; trend (>=5 runs) fits the scope's
compound-risk trajectory. Both scope kinds share the tiering + trend machinery (methodology.md).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.meta.rca import build_rca
from modules.meta.spec import thresholds

log = get_logger("meta.health")

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
    if float(np.ptp(xs)) < 1e-9:
        return (0.0 if score <= CRITICAL_SCORE else None), True
    slope = np.polyfit(xs - xs.min(), ys, 1)[0]
    if slope < -1e-4 and score > CRITICAL_SCORE:
        return min(float((score - CRITICAL_SCORE) / (-slope)), 24 * 365.0), True
    if score <= CRITICAL_SCORE:
        return 0.0, True
    return None, True


def _consecutive_compound(feat: Dict[str, Any], hist: List[Dict[str, Any]]) -> int:
    """Consecutive most-recent meta runs (incl. now) where this scope was compound (breadth >= 2)."""
    if int(feat.get("breadth", 0)) < 2:
        return 0
    consec = 1
    for h in hist:
        try:
            if int((h.get("metrics_json") or {}).get("breadth") or 0) >= 2:
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
    sev_by_tier = t.get("severity_by_tier", {"critical": 18, "warn": 8, "watch": 2, "ok": 0})
    ctl_by_tier = t.get("controller_trigger_by_tier", {"critical": 30, "warn": 15, "watch": 5, "ok": 0})
    aisle_w = float(t.get("compound_aisle_weight", 10))
    aisle_cap = float(t.get("aisle_breadth_cap", 40))

    out: List[ComponentHealth] = []
    for cid, feat in features.items():
        hist = history.component_history("meta", cid, limit=400)
        breadth = int(feat.get("breadth", 0))
        worst = str(feat.get("worst_flagged_tier", "ok")).lower()
        chain_n = int(feat.get("chain_edge_count", 0))
        consec = _consecutive_compound(feat, hist)
        is_system = feat.get("scope_kind") == "system"

        # severity amplifies a compound incident only (breadth >= 2) -> never double-counts a lone module.
        severity_pts = float(sev_by_tier.get(worst, 0)) if breadth >= 2 else 0.0
        penalties = {
            "breadth": _capped(breadth - 1, **p["breadth"]),
            "severity": severity_pts,
            "chain": _capped(chain_n, **p["chain"]),
            "persistence": _capped(max(consec - 1, 0), **p["persistence"]),
        }
        if is_system:
            # a saturated controller is a system incident on its own (explicit system trigger);
            # and many simultaneously-compound aisles indicate a systemic common cause.
            penalties["controller_trigger"] = float(ctl_by_tier.get(str(feat.get("controller_tier", "ok")).lower(), 0))
            penalties["aisle_breadth"] = min(int(feat.get("compound_aisle_count", 0)) * aisle_w, aisle_cap)

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
            conf = min(0.9, conf_cfg["coldstart_base"] + 0.08 * breadth + 0.1 * chain_n + (0.1 if hist else 0.0))

        primary, rca = build_rca(feat, penalties, consec)
        metrics = dict(feat)
        metrics.update({
            "runs_observed": len(hist),
            "consecutive_compound": consec,
            "penalties": {k: round(v, 2) for k, v in penalties.items()},
            "penalty_total": round(total_pen, 2),
        })
        out.append(ComponentHealth(
            component_id=cid, component_type="incident_scope", health_score=health, risk_tier=tier,
            predicted_ttm_hours=ttm, confidence=conf, prediction_regime=regime,
            primary_cause=primary, rca=rca, metrics=metrics,
        ))

    # rank worst-first (system + compound aisles float to the top).
    out.sort(key=lambda c: c.health_score)
    log.info("meta health scored",
             extra={"scopes": len(out), "worst": out[0].component_id if out else None,
                    "worst_score": out[0].health_score if out else None,
                    "incidents": sum(1 for c in out if c.risk_tier != "ok")})
    return out
