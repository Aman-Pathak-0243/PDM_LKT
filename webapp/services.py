"""Read-side services for the dashboard (summaries, history, storage overview).

Pure query/aggregation helpers over ``core.storage`` + ``core.registry``. No
HTTP concerns here, so the same functions back both HTML pages and JSON APIs.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

from core.config import get_config
from core.registry import all_modules, tier_rank, worst_tier
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
