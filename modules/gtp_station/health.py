"""GTP STATION + SCANNER health scoring — dual-entity penalty model.

Two component types, each a penalty model (start 100, subtract capped penalties):

  SCANNER (gtp_scanner): misread rate is the core signal. The misread penalty is scaled by
    scan volume (a scanner with few scans has a noisy rate, so its penalty and confidence are
    reduced). Peer deviation (misread far above peer scanners, within-snapshot) and cross-run
    recurrence (prior runs this scanner read elevated) add to it.

  STATION (gtp_station): the per-station pick-verification discrepancy rate drives the score —
    mainly via peer deviation (discrepancies/day vs sibling stations, isolating station-specific
    degradation from plant-wide inventory shorts), plus a very-high absolute rate, cross-run
    recurrence, and a low-weight offline-persistence signal (dark run-after-run). active_status
    is context, not a hard fault (many stations are legitimately Inactive).

No cycle counter, so RUL is time/recurrence-based: cold-start uses a coarse band by tier; trend
(>=5 runs) fits the component's health trajectory over accumulated runs. Every prediction is
labelled coldstart|trend with a confidence. Both entity types share the tiering + trend + RUL
machinery so the methodology stays consistent (methodology.md).
"""

from __future__ import annotations

import datetime as _dt
from statistics import median
from typing import Any, Dict, List

import numpy as np

from core.logging_setup import get_logger
from core.registry import ComponentHealth, HistoryReader
from modules.gtp_station.rca import build_scanner_rca, build_station_rca, cross_link_entities
from modules.gtp_station.spec import thresholds

log = get_logger("gtp_station.health")

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


def _scanner_recurrence(hist: List[Dict[str, Any]], min_misread_pct: float) -> int:
    """Prior runs whose MISREAD% was elevated — misread-specific, so peer-z/volume artifacts
    do not self-reinforce into a compounding recurrence penalty."""
    n = 0
    for h in hist:
        m = h.get("metrics_json") or {}
        try:
            if float(m.get("misread_pct") or 0.0) >= min_misread_pct:
                n += 1
        except (TypeError, ValueError):
            continue
    return n


def _station_recurrence(hist: List[Dict[str, Any]], floor_per_day: float, z_thresh: float) -> int:
    """Prior runs whose DISCREPANCIES were elevated (peer-z or per-day) — discrepancy-specific,
    so a legitimately-Inactive station (offline-only health drop) never accrues recurrence and
    thus never escalates past the WATCH ceiling that the offline_persistence cap intends."""
    n = 0
    for h in hist:
        m = h.get("metrics_json") or {}
        try:
            dpd = float(m.get("discrepancy_per_day") or 0.0)
            z = float(m.get("discrepancy_peer_z") or 0.0)
            if dpd > floor_per_day or z >= z_thresh:
                n += 1
        except (TypeError, ValueError):
            continue
    return n


def _consecutive_inactive(feat: Dict[str, Any], hist: List[Dict[str, Any]]) -> int:
    """Consecutive most-recent runs Inactive, INCLUDING now (persistence of downtime)."""
    if feat.get("is_active") is not False:
        return 0
    consec = 1
    for h in hist:  # newest first
        if (h.get("metrics_json") or {}).get("is_active") is False:
            consec += 1
        else:
            break
    return consec


# --------------------------------------------------------------------------- #
# Scanner scoring
# --------------------------------------------------------------------------- #
def _score_scanner(feat, hist, t, sc_cfg, tiers, conf_cfg, bands, min_runs) -> ComponentHealth:
    p = sc_cfg["penalties"]
    min_vol = float(sc_cfg.get("min_volume_full", 200))
    min_vol_peer = float(sc_cfg.get("min_volume_peer", 200))
    peer_z_min_misread = float(sc_cfg.get("peer_z_min_misread_pct", 1.0))
    recur_min_misread = float(sc_cfg.get("recur_min_misread_pct", 2.0))

    total = float(feat.get("total_scans", 0))
    misread_pct = float(feat.get("misread_pct", 0.0))
    vol_factor = min(1.0, total / min_vol) if min_vol > 0 else 1.0
    recurrence = _scanner_recurrence(hist, recur_min_misread)
    # peer_z only bites when the scanner has enough volume AND a materially elevated misread,
    # so one fluke no-read on a low-volume device (or a trivially-above-a-tiny-median rate) is not flagged.
    peer_z_eff = feat.get("misread_peer_z", 0.0) if (total >= min_vol_peer and misread_pct >= peer_z_min_misread) else 0.0

    penalties = {
        # misread penalty scaled by scan volume (noisy low-volume rates don't over-fire).
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
        component_id=feat["component_id"], component_type="gtp_scanner", health_score=health,
        risk_tier=tier, predicted_ttm_hours=ttm, confidence=conf,
        prediction_regime=regime, primary_cause=primary, rca=rca, metrics=metrics,
    )


# --------------------------------------------------------------------------- #
# Station scoring
# --------------------------------------------------------------------------- #
def _score_station(feat, hist, t, st_cfg, tiers, conf_cfg, bands, min_runs) -> ComponentHealth:
    p = st_cfg["penalties"]
    floor = float(st_cfg.get("discrepancy_abs_floor_per_day", 20))
    recur_z = float(st_cfg.get("recur_peer_z", 2.0))
    recur_per_day = float(st_cfg.get("recur_min_per_day", floor))

    recurrence = _station_recurrence(hist, recur_per_day, recur_z)
    consec_inactive = _consecutive_inactive(feat, hist)
    dpd = float(feat.get("discrepancy_per_day", 0.0))

    penalties = {
        "discrepancy_peer_z": _capped(feat.get("discrepancy_peer_z", 0.0), **p["discrepancy_peer_z"]),
        "discrepancy_abs": _capped(dpd - floor, **p["discrepancy_abs"]),
        "recurrence": _capped(recurrence, **p["recurrence"]),
        "offline_persistence": _capped(max(consec_inactive - 1, 0), **p["offline_persistence"]),
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
        evidence = min(1.0, dpd / max(floor, 1.0) + (0.2 if recurrence else 0.0)
                       + (0.15 if feat.get("discrepancy_disclosed") else 0.0))
        conf = min(0.88, conf_cfg["station_coldstart_base"] + 0.4 * evidence + (0.1 if hist else 0.0))

    primary, rca = build_station_rca(feat, penalties, recurrence, consec_inactive)
    metrics = dict(feat)
    metrics.update({
        "runs_observed": len(hist),
        "recurrence_runs": recurrence,
        "consecutive_inactive": consec_inactive,
        "penalties": {k: round(v, 2) for k, v in penalties.items()},
        "penalty_total": round(total_pen, 2),
    })
    return ComponentHealth(
        component_id=feat["component_id"], component_type="gtp_station", health_score=health,
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
        hist = history.component_history("gtp_station", cid, limit=400)
        if feat.get("component_type") == "gtp_station":
            out.append(_score_station(feat, hist, t, st_cfg, tiers, conf_cfg, bands, min_runs))
            n_stn += 1
        else:
            out.append(_score_scanner(feat, hist, t, sc_cfg, tiers, conf_cfg, bands, min_runs))
            n_scan += 1

    # Cross-entity corroboration: a station AND its slot scanner both flagged -> same-cause note.
    cross_link_entities(out)

    out.sort(key=lambda c: c.health_score)
    log.info("gtp_station health scored",
             extra={"scanners": n_scan, "stations": n_stn,
                    "worst": out[0].component_id if out else None,
                    "worst_score": out[0].health_score if out else None,
                    "flagged": sum(1 for c in out if c.risk_tier != "ok")})
    return out
