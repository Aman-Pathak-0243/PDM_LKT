"""Read-side services for the dashboard (summaries, history, storage overview).

Pure query/aggregation helpers over ``core.storage`` + ``core.registry``. No
HTTP concerns here, so the same functions back both HTML pages and JSON APIs.
"""

from __future__ import annotations

import datetime as _dt
import re as _re
from typing import Any, Dict, List, Optional

from core.config import get_config
from core.registry import (
    RISK_TIERS,
    all_modules,
    score_to_tier,
    tier_rank,
    worst_tier,
)
from core.storage import get_storage


def _hours_ago_iso(hours: float) -> str:
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours)).isoformat(
        timespec="milliseconds"
    )


def latest_components(module: str) -> List[Dict[str, Any]]:
    """Latest health row per component for a module (most recent run wins)."""
    storage = get_storage()
    rows = storage.latest_per(
        "component_health", ["module", "component_id"], "created_at", {"module": module}
    )
    # Worst-first: worst tier first, then lowest health within a tier.
    rows.sort(key=lambda r: (tier_rank(r.get("risk_tier", "ok")), (r.get("health_score") or 0)))
    return rows


def last_run(module: str) -> Optional[Dict[str, Any]]:
    rows = get_storage().select(
        "pdm_run", {"module": module}, order_by=("created_at", "desc"), limit=1
    )
    return rows[0] if rows else None


def module_summaries() -> List[Dict[str, Any]]:
    cfg = get_config()
    out: List[Dict[str, Any]] = []
    for m in all_modules():
        comps = latest_components(m.name)
        run = last_run(m.name)
        tiers = [c.get("risk_tier", "ok") for c in comps]
        out.append(
            {
                "name": m.name,
                "title": m.title,
                "component_type": m.component_type,
                "description": m.description,
                "configured": m.is_configured(cfg),
                "dashboards": list(m.dashboards(cfg).keys()),
                "component_count": len(comps),
                "worst_tier": worst_tier(tiers) if tiers else "unknown",
                "tier_counts": {t: tiers.count(t) for t in set(tiers)} if tiers else {},
                "last_run_at": run.get("finished_at") if run else None,
                "last_run_status": run.get("status") if run else None,
            }
        )
    return out


def component_history(module: str, component_id: str, limit: int = 300) -> List[Dict[str, Any]]:
    rows = get_storage().select(
        "component_health",
        {"module": module, "component_id": component_id},
        order_by=("created_at", "asc"),
        limit=limit,
    )
    return rows


def recent_triggers(limit: int = 50, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return get_storage().select(
        "trigger_log", filters, order_by=("created_at", "desc"), limit=limit
    )


def get_trigger(trigger_id: str) -> Optional[Dict[str, Any]]:
    rows = get_storage().select("trigger_log", {"trigger_id": trigger_id}, limit=1)
    return rows[0] if rows else None


def runs_for_trigger(trigger_id: str) -> List[Dict[str, Any]]:
    return get_storage().select(
        "pdm_run", {"trigger_id": trigger_id}, order_by=("created_at", "asc")
    )


def search_events(
    q: str = "",
    level: str = "",
    module: str = "",
    since_hours: Optional[float] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    filters: Dict[str, Any] = {}
    if level:
        filters["level"] = level.upper()
    if module:
        filters["module"] = module
    if since_hours:
        filters["ts"] = (">=", _hours_ago_iso(since_hours))
    rows = get_storage().select("event_log", filters, order_by=("ts", "desc"), limit=limit * 3)
    if q:
        ql = q.lower()
        rows = [
            r
            for r in rows
            if ql in str(r.get("event", "")).lower()
            or ql in str(r.get("detail_json", "")).lower()
            or ql in str(r.get("source", "")).lower()
        ]
    return rows[:limit]


def _fmt_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.1f} {unit}" if unit != "B" else f"{int(f)} B"
        f /= 1024
    return f"{f:.1f} TB"


def storage_overview() -> Dict[str, Any]:
    storage = get_storage()
    stats = storage.stats()
    # Growth: rows created in the last 24h for time-stamped tables.
    since = _hours_ago_iso(24)
    growth_col = {
        "pdm_run": "created_at",
        "component_health": "created_at",
        "trigger_log": "created_at",
        "event_log": "ts",
        "maintenance_ack": "acked_at",
    }
    datasets = []
    total_bytes = total_rows = 0
    for s in stats:
        col = growth_col.get(s.table)
        last_24h = storage.count(s.table, {col: (">=", since)}) if col else None
        total_bytes += s.size_bytes
        total_rows += s.record_count
        datasets.append(
            {
                "table": s.table,
                "record_count": s.record_count,
                "size_bytes": s.size_bytes,
                "size_human": _fmt_bytes(s.size_bytes),
                "last_modified": s.last_modified,
                "location": s.location,
                "added_last_24h": last_24h,
            }
        )
    return {
        "backend": storage.backend_name,
        "total_bytes": total_bytes,
        "total_human": _fmt_bytes(total_bytes),
        "total_rows": total_rows,
        "datasets": datasets,
    }


def performance_metrics() -> Dict[str, Any]:
    storage = get_storage()
    triggers = storage.select("trigger_log", order_by=("created_at", "desc"), limit=100)
    durations = [t.get("duration_ms") or 0 for t in triggers if t.get("status") != "running"]
    runs = storage.select("pdm_run", order_by=("created_at", "desc"), limit=200)
    failed = [r for r in runs if r.get("status") == "failed"]
    return {
        "triggers_total": storage.count("trigger_log"),
        "runs_total": storage.count("pdm_run"),
        "runs_failed": len(failed),
        "avg_trigger_ms": round(sum(durations) / len(durations), 1) if durations else 0,
        "max_trigger_ms": max(durations) if durations else 0,
        "last_trigger_ms": durations[0] if durations else 0,
    }


# --------------------------------------------------------------------------- #
# Graphical overview analytics
# --------------------------------------------------------------------------- #
# One aggregation call backs the Overview page's "Graphical Overview" tab. It
# reads the accumulated longitudinal store (component_health) and derives fleet-
# wide rollups the SVG charts render. Everything degrades to empty-but-valid
# shapes when no PdM run has happened yet, so the page never errors on cold start.

_AISLE_RE = _re.compile(r"aisle[_-]?0*(\d+)", _re.IGNORECASE)
# (label, lo_exclusive, hi_inclusive) — matched as ``lo < ttm <= hi`` so the "≤24h"
# label genuinely includes the 24.0h boundary (a common cold-start critical band) and
# stays consistent with the ``imminent`` KPI (ttm ≤ 24). ttm is clamped ≥ 0, so the
# first bucket's -1 lower bound captures ttm == 0.
_TTM_BUCKETS = (
    ("≤24h", -1.0, 24.0),
    ("1–3d", 24.0, 72.0),
    ("3–7d", 72.0, 168.0),
    (">7d", 168.0, float("inf")),
)


def _parse_aisle(text: str) -> Optional[str]:
    """Normalise an aisle token out of a string, e.g. ``aisle_04_inbound_lift_02``
    / ``aisle_4`` -> ``aisle_04``. None if no aisle token is present."""
    m = _AISLE_RE.search(text or "")
    return f"aisle_{int(m.group(1)):02d}" if m else None


def _aisle_of(comp: Dict[str, Any]) -> Optional[str]:
    """Resolve a component's aisle. Prefer the module-computed ``metrics_json.aisle``
    (authoritative — many ids like ``QD_Shuttle_03_06`` or ``002-04-…`` don't carry a
    literal ``aisle`` token), and fall back to parsing the component id itself."""
    a = (comp.get("metrics_json") or {}).get("aisle")
    if a:
        got = _parse_aisle(str(a))
        if got:
            return got
    return _parse_aisle(comp.get("component_id") or "")


def _window_to_hours(window: Optional[str], default: float = 168.0) -> float:
    """Parse a Grafana-style relative window (``now-2d``/``now-6h``/``now-90d``)
    into hours for the trend time span. Falls back to ``default`` (7 days).

    Case-sensitive per Grafana units (matching modules/tracker's parser): lowercase
    ``m`` = minutes, uppercase ``M`` = months — so ``now-30m`` is 0.5h, not ~900 days.
    """
    if not window:
        return default
    m = _re.search(r"now-(\d+)\s*([smhdwMy])", window.strip())
    if not m:
        return default
    n = int(m.group(1))
    unit_hours = {"s": 1 / 3600, "m": 1 / 60, "h": 1, "d": 24, "w": 168, "M": 720, "y": 8760}
    return float(n * unit_hours[m.group(2)])


def _mean(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 1) if values else None


def _fleet_trend(window: Optional[str], max_points: int = 60) -> List[Dict[str, Any]]:
    """Fleet-average health over time, adaptively bucketed within the window.

    Groups every component_health snapshot in the window into evenly-sized time
    buckets and averages the health score per bucket, so the store's accumulated
    history (far longer than any single Grafana fetch) reads as one trend line.
    """
    storage = get_storage()
    span_h = _window_to_hours(window)
    cutoff = _hours_ago_iso(span_h)
    rows = storage.select(
        "component_health",
        {"created_at": (">=", cutoff)},
        order_by=("created_at", "asc"),
        limit=100000,
    )
    pts: List[tuple] = []
    for r in rows:
        try:
            ts = _dt.datetime.fromisoformat(str(r["created_at"]))
        except (TypeError, ValueError, KeyError):
            continue
        hs = r.get("health_score")
        if hs is None:
            continue
        pts.append((ts, float(hs)))
    if not pts:
        return []
    t0 = min(p[0] for p in pts)
    t1 = max(p[0] for p in pts)
    span = (t1 - t0).total_seconds()
    bucket = max(3600.0, span / max_points) if span > 0 else 3600.0
    buckets: Dict[int, List[float]] = {}
    for ts, hs in pts:
        idx = int((ts - t0).total_seconds() // bucket)
        buckets.setdefault(idx, []).append(hs)
    out = []
    for idx in sorted(buckets):
        vals = buckets[idx]
        centre = t0 + _dt.timedelta(seconds=(idx + 0.5) * bucket)
        out.append(
            {
                "t": centre.isoformat(timespec="minutes"),
                "v": round(sum(vals) / len(vals), 1),
                "n": len(vals),
            }
        )
    return out


def overview_analytics(window: Optional[str] = None) -> Dict[str, Any]:
    """Fleet-wide rollups for the Overview page's Graphical Overview tab."""
    cfg = get_config()
    storage = get_storage()
    modules = all_modules()

    all_comps: List[Dict[str, Any]] = []
    per_module: List[Dict[str, Any]] = []
    last_runs: List[str] = []

    for m in modules:
        comps = latest_components(m.name)
        run = last_run(m.name)
        if run and run.get("finished_at"):
            last_runs.append(run["finished_at"])
        tiers = [c.get("risk_tier") or "unknown" for c in comps]
        scores = [c["health_score"] for c in comps if c.get("health_score") is not None]
        per_module.append(
            {
                "name": m.name,
                "title": m.title,
                "component_type": m.component_type,
                "configured": m.is_configured(cfg),
                "component_count": len(comps),
                "tier_counts": {t: tiers.count(t) for t in RISK_TIERS},
                "worst_tier": worst_tier(tiers) if tiers else "unknown",
                "avg_health": _mean(scores),
                "last_run_at": run.get("finished_at") if run else None,
            }
        )
        for c in comps:
            all_comps.append({**c, "module": m.name, "module_title": m.title})

    total = len(all_comps)
    tier_counts = {t: sum(1 for c in all_comps if (c.get("risk_tier") or "unknown") == t)
                   for t in (*RISK_TIERS, "unknown")}
    all_scores = [c["health_score"] for c in all_comps if c.get("health_score") is not None]

    # Health-score histogram (10-point bins, coloured by the bin's tier band).
    hist = []
    for lo in range(0, 100, 10):
        hi = lo + 10
        cnt = sum(1 for s in all_scores if (lo <= s < hi) or (hi == 100 and s == 100))
        hist.append({"lo": lo, "hi": hi, "count": cnt, "tier": score_to_tier(lo + 5)})

    # Worst components across the whole fleet (already worst-first per module).
    ranked = sorted(
        all_comps,
        key=lambda c: (tier_rank(c.get("risk_tier") or "ok"), c.get("health_score") or 0),
    )
    top_at_risk = [
        {
            "component_id": c.get("component_id"),
            "module": c.get("module"),
            "module_title": c.get("module_title"),
            "health_score": round(c.get("health_score"), 1) if c.get("health_score") is not None else None,
            "risk_tier": c.get("risk_tier") or "unknown",
            "predicted_ttm_hours": c.get("predicted_ttm_hours"),
            "primary_cause": c.get("primary_cause") or "",
        }
        for c in ranked
        if (c.get("risk_tier") or "ok") != "ok"
    ][:12]

    # Time-to-maintenance buckets for flagged components with an ETA.
    ttm_buckets = [{"label": lab, "count": 0} for lab, _, _ in _TTM_BUCKETS]
    imminent = 0
    for c in all_comps:
        if (c.get("risk_tier") or "ok") == "ok":
            continue
        ttm = c.get("predicted_ttm_hours")
        if ttm is None:
            continue
        if ttm <= 24.0:
            imminent += 1
        for i, (_, lo, hi) in enumerate(_TTM_BUCKETS):
            if lo < ttm <= hi:
                ttm_buckets[i]["count"] += 1
                break

    # Aisle × module risk heatmap (six-aisle ASRS layout).
    cell_acc: Dict[tuple, Dict[str, Any]] = {}
    aisles_seen: set = set()
    modules_with_aisle: Dict[str, str] = {}
    for c in all_comps:
        aisle = _aisle_of(c)
        if not aisle:
            continue
        aisles_seen.add(aisle)
        modules_with_aisle[c["module"]] = c["module_title"]
        key = (aisle, c["module"])
        acc = cell_acc.setdefault(key, {"tiers": [], "scores": []})
        acc["tiers"].append(c.get("risk_tier") or "unknown")
        if c.get("health_score") is not None:
            acc["scores"].append(c["health_score"])
    heatmap_modules = [
        {"name": m.name, "title": m.title}
        for m in modules
        if m.name in modules_with_aisle
    ]
    cells = [
        {
            "aisle": a,
            "module": mod,
            "worst_tier": worst_tier(acc["tiers"]) if acc["tiers"] else "unknown",
            "count": len(acc["tiers"]),
            "avg_health": _mean(acc["scores"]),
        }
        for (a, mod), acc in cell_acc.items()
    ]

    kpis = {
        "total_components": total,
        "modules_total": len(modules),
        "modules_configured": sum(1 for m in per_module if m["configured"]),
        "ok": tier_counts.get("ok", 0),
        "watch": tier_counts.get("watch", 0),
        "warn": tier_counts.get("warn", 0),
        "critical": tier_counts.get("critical", 0),
        "unknown": tier_counts.get("unknown", 0),
        "avg_health": _mean(all_scores),
        "imminent": imminent,
        "coldstart": sum(1 for c in all_comps if c.get("prediction_regime") == "coldstart"),
        "trend": sum(1 for c in all_comps if c.get("prediction_regime") == "trend"),
        "last_run_at": max(last_runs) if last_runs else None,
        "runs_total": storage.count("pdm_run"),
        "triggers_total": storage.count("trigger_log"),
    }

    return {
        "has_data": total > 0,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "window": window,
        "kpis": kpis,
        "tier_distribution": [
            {"tier": t, "count": tier_counts.get(t, 0)} for t in RISK_TIERS
        ],
        "modules": per_module,
        "score_histogram": hist,
        "top_at_risk": top_at_risk,
        "ttm_buckets": ttm_buckets,
        "aisle_matrix": {
            "aisles": sorted(aisles_seen),
            "modules": heatmap_modules,
            "cells": cells,
        },
        "fleet_trend": _fleet_trend(window),
    }
