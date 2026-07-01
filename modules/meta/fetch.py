"""SYSTEM-WIDE ANOMALY (META) fetch step — reads the PdM STORE, not Grafana.

Unlike every other module, meta has no Grafana source. Its "fetch" ignores the Playwright session and
reads the latest scored component of every OTHER module from the store (component_health), so the
correlation layer can group them by aisle / system in features.py. Registered LAST, so on a "Run all"
trigger the other modules have already persisted their fresh rows before this runs (same-trigger
correlation); run solo, it correlates the most-recently-stored verdicts.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.logging_setup import get_logger
from core.registry import FetchBundle
from core.storage import get_storage
from core.storage.base import from_json

log = get_logger("meta.fetch")


def _as_dict(v) -> Dict[str, Any]:
    d = from_json(v)
    return d if isinstance(d, dict) else {}


def fetch(session, window: str) -> FetchBundle:
    # session is intentionally unused (no Grafana call).
    storage = get_storage()
    latest = storage.latest_per("component_health", ["module", "component_id"], "created_at")

    components: List[Dict[str, Any]] = []
    for r in latest:
        mod = r.get("module")
        if not mod or mod == "meta":            # never correlate our own output
            continue
        components.append({
            "module": mod,
            "component_id": r.get("component_id"),
            "component_type": r.get("component_type"),
            "health_score": r.get("health_score"),
            "risk_tier": (r.get("risk_tier") or "ok"),
            "primary_cause": r.get("primary_cause") or "",
            "created_at": r.get("created_at"),
            "rca": _as_dict(r.get("rca_json")),
            "metrics": _as_dict(r.get("metrics_json")),
        })

    modules_seen = sorted({c["module"] for c in components})
    panels = [{
        "dashboard_uid": "store", "dashboard_name": "PdM store (component_health)", "panel_id": 0,
        "panel_title": "cross-module correlation", "panel_type": "store", "fields": ["module", "risk_tier", "rca_json.cross_module_flags", "metrics_json.aisle"],
        "sql_text": "latest per (module, component_id) excluding module='meta'",
        "is_signal": True, "role": "primary",
        "notes": "Meta reads the store (no Grafana). Correlates the latest verdicts + cross-module flags of all other modules.",
    }]
    log.info("meta fetch complete (store read)",
             extra={"components": len(components), "modules": modules_seen})
    return FetchBundle(frames={"components": components}, rows_fetched=len(components),
                       panels=panels, notes={"window": window, "modules_seen": modules_seen})
