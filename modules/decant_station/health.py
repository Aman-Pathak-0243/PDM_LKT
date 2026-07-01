"""DECANTING STATION + SCANNER health scoring — dual-entity penalty model.

Two component types, each a penalty model (start 100, subtract capped penalties):

  SCANNER (decant_scanner): misread rate is the core signal (same calibration as the proven
    gtp_station scanner model). The misread penalty is scaled by scan volume (few scans -> noisy
    rate -> reduced penalty + confidence). Peer deviation (misread far above the decant scanner
    fleet, within-snapshot, gated) and cross-run recurrence (prior runs this device read elevated)
    add to it. This is the strong, immediately-meaningful signal.

  STATION (decant_station): there is NO live per-station fault/discrepancy feed, so the station is
    scored coarsely and honestly. Only two penalties, both cross-run so cold-start stations are ok
    at low confidence: offline_persistence (Inactive across consecutive runs -> WATCH ceiling; may
    be intentional) and idle_recurrence (Active but decanting nothing while the line is busy, across
    consecutive runs -> can reach WARN when sustained). A single idle/Inactive run adds nothing.

No cycle counter, so RUL is time/recurrence-based: cold-start uses a coarse band by tier; trend
(>=5 runs) fits the component's health trajectory over accumulated runs. Every prediction is
labelled coldstart|trend with a confidence. Both entity types share the tiering + trend + RUL
machinery so the methodology stays consistent (methodology.md).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.decant_station.rca import build_scanner_rca, build_station_rca, line_level_corroboration
from modules.decant_station.spec import thresholds

log = get_logger("decant_station.health")

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
    # Degenerate x (all snapshots share a timestamp, e.g. bulk import) -> polyfit would raise
    # LinAlgError / emit NaN. We are in the trend regime but cannot project an RUL.
    if float(np.ptp(xs)) < 1e-9:
        return (0.0 if score <= CRITICAL_SCORE else None), True
    slope = np.polyfit(xs - xs.min(), ys, 1)[0]  # health per hour
    if slope < -1e-4 and score > CRITICAL_SCORE:
        return min(float((score - CRITICAL_SCORE) / (-slope)), 24 * 365.0), True
    if score <= CRITICAL_SCORE:
        return 0.0, True
    return None, True


def _scanner_recurrence(hist: List[Dict[str, Any]], min_misread_pct: float, min_vol: float = 0.0) -> int:
    """Prior runs whose MISREAD% was elevated AND which had adequate scan volume — misread- and
    volume-specific, so a low-scan device's noisy misread% cannot compound a recurrence penalty
    that the (volume-gated) misread penalty deliberately suppresses."""
    n = 0
    for h in hist:
        m = h.get("metrics_json") or {}
        try:
            if float(m.get("total_scans") or 0.0) < min_vol:
                continue
            if float(m.get("misread_pct") or 0.0) >= min_misread_pct:
                n += 1
        except (TypeError, ValueError):
            continue
    return n


def _consecutive_flag(feat_now: bool, hist: List[Dict[str, Any]], key: str) -> int:
    """Consecutive most-recent runs (newest-first) whose metrics[key] is True, INCLUDING now."""
    if not feat_now:
        return 0
    consec = 1
    for h in hist:
        if (h.get("metrics_json") or {}).get(key) is True:
            consec += 1
        else:
            break
    return consec


# --------------------------------------------------------------------------- #
# Scanner scoring
# --------------------------------------------------------------------------- #
def _score_scanner(feat, hist, sc_cfg, tiers, conf_cfg, bands, min_runs) -> ComponentHealth:
    p = sc_cfg["penalties"]
    min_vol = float(sc_cfg.get("min_volume_full", 200))
    min_vol_peer = float(sc_cfg.get("min_volume_peer", 200))
    peer_z_min_misread = float(sc_cfg.get("peer_z_min_misread_pct", 1.0))
    recur_min_misread = float(sc_cfg.get("recur_min_misread_pct", 2.0))

    total = float(feat.get("total_scans", 0))
    misread_pct = float(feat.get("misread_pct", 0.0))
    vol_factor = min(1.0, total / min_vol) if min_vol > 0 else 1.0
    # Recurrence only counts prior runs that had adequate volume, matching the
    # volume-gate on the misread penalty (a noisy low-scan run must not accumulate
    # recurrence points the misread gate suppresses).
    recurrence = _scanner_recurrence(hist, recur_min_misread, min_vol)
    # peer_z only bites with enough volume AND a materially-elevated misread, so a clean decant
    # diverter sitting slightly above a tight fleet median is never flagged.
    peer_z_eff = feat.get("misread_peer_z", 0.0) if (total >= min_vol_peer and misread_pct >= peer_z_min_misread) else 0.0

    penalties = {
        "misread": _capped(misread_pct, **p["misread"]) * vol_factor,
        "peer_z": _capped(peer_z_eff, **p["peer_z"]),
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
        conf = min(0.9, conf_cfg["scanner_coldstart_base"] + 0.4 * vol_factor + (0.1 if hist else 0.0))

    primary, rca = build_scanner_rca(feat, penalties, recurrence)
    metrics = dict(feat)
    metrics.update({
        "runs_observed": len(hist),
        "recurrence_runs": recurrence,
        "volume_factor": round(vol_factor, 3),
        "penalties": {k: round(v, 2) for k, v in penalties.items()},
        "penalty_total": round(total_pen, 2),
    })
    return ComponentHealth(
        component_id=feat["component_id"], component_type="decant_scanner", health_score=health,
        risk_tier=tier, predicted_ttm_hours=ttm, confidence=conf,
        prediction_regime=regime, primary_cause=primary, rca=rca, metrics=metrics,
    )


# --------------------------------------------------------------------------- #
# Station scoring
# --------------------------------------------------------------------------- #
def _score_station(feat, hist, st_cfg, tiers, conf_cfg, bands, min_runs) -> ComponentHealth:
    p = st_cfg["penalties"]

    # Consecutive most-recent runs Inactive, INCLUDING now (offline persistence). We match on the
    # stored is_active flag being False (not just missing), so 'Unknown'/absent status never counts.
    consec_inactive = 0
    if feat.get("is_active") is False:
        consec_inactive = 1
        for h in hist:
            if (h.get("metrics_json") or {}).get("is_active") is False:
                consec_inactive += 1
            else:
                break
    # Consecutive most-recent runs idle-while-active-while-line-busy, INCLUDING now.
    consec_idle_active = _consecutive_flag(bool(feat.get("idle_while_active")), hist, "idle_while_active")

    penalties = {
        # both are cross-run: a single Inactive / idle-while-active run adds nothing (beyond-1).
        "offline_persistence": _capped(max(consec_inactive - 1, 0), **p["offline_persistence"]),
        "idle_recurrence": _capped(max(consec_idle_active - 1, 0), **p["idle_recurrence"]),
    }
    total_pen = sum(penalties.values())
    health = max(0.0, 100.0 - total_pen)
    tier = _tier(health, tiers)

    ttm, used_trend = _trend(hist, health, min_runs)
    if used_trend:
        regime = "trend"
        conf = min(0.95, conf_cfg["trend_base"] + 0.2 * min(1.0, len(hist) / (3 * min_runs)))
    else:
        regime = "coldstart"
        ttm = bands.get(tier)
        # Station confidence is deliberately modest — no live fault feed. It rises with throughput
        # disclosure + accumulated persistence evidence + any history.
        evidence = min(1.0, 0.25 * max(consec_inactive - 1, 0) + 0.25 * max(consec_idle_active - 1, 0)
                       + (0.3 if feat.get("cartons_disclosed") else 0.0))
        conf = min(0.75, conf_cfg["station_coldstart_base"] + 0.4 * evidence + (0.1 if hist else 0.0))

    primary, rca = build_station_rca(feat, penalties, consec_inactive, consec_idle_active)
    metrics = dict(feat)
    metrics.update({
        "runs_observed": len(hist),
        "consecutive_inactive": consec_inactive,
        "consecutive_idle_active": consec_idle_active,
        "penalties": {k: round(v, 2) for k, v in penalties.items()},
        "penalty_total": round(total_pen, 2),
    })
    return ComponentHealth(
        component_id=feat["component_id"], component_type="decant_station", health_score=health,
        risk_tier=tier, predicted_ttm_hours=ttm, confidence=conf,
        prediction_regime=regime, primary_cause=primary, rca=rca, metrics=metrics,
    )


def score(features: Dict[str, Dict[str, Any]], history: HistoryReader) -> List[ComponentHealth]:
    t = thresholds()
    tiers = t["tiers"]
    conf_cfg = t["confidence"]
    bands = t.get("ttm_bands_hours", {"critical": 48, "warn": 240, "watch": 720})
    min_runs = int(t.get("history_min_runs_for_trend", 5))
    sc_cfg = t["scanner"]
    st_cfg = t["station"]

    out: List[ComponentHealth] = []
    n_scan = n_stn = 0
    for cid, feat in features.items():
        hist = history.component_history("decant_station", cid, limit=400)
        if feat.get("component_type") == "decant_station":
            out.append(_score_station(feat, hist, st_cfg, tiers, conf_cfg, bands, min_runs))
            n_stn += 1
        else:
            out.append(_score_scanner(feat, hist, sc_cfg, tiers, conf_cfg, bands, min_runs))
            n_scan += 1

    # Line-level corroboration: decant scanners are per-aisle and stations are operator stations
    # (no 1:1 device mapping), so we only add a line-level note when BOTH entity types look unhealthy.
    line_level_corroboration(out)

    out.sort(key=lambda c: c.health_score)
    log.info("decant_station health scored",
             extra={"scanners": n_scan, "stations": n_stn,
                    "worst": out[0].component_id if out else None,
                    "worst_score": out[0].health_score if out else None,
                    "flagged": sum(1 for c in out if c.risk_tier != "ok")})
    return out
