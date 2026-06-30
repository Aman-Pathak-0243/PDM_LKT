"""PdM run orchestration.

A PdM run = fetch → features → health → persist. The runner is backend-agnostic
(writes through ``core.storage``) and transport-agnostic (the same functions serve
manual webapp triggers and automated scheduler triggers). Every run is wrapped in a
traceable trigger (``trigger_log``) with timing, counts, and status.

All work here is synchronous and intended to run on a worker thread (scheduler
executor or the webapp thread pool), never the asyncio event loop.
"""

from __future__ import annotations

import datetime as _dt
from time import perf_counter
from typing import Any, Dict, List, Optional, Sequence

from core.audit import record_event
from core.config import get_config
from core.logging_setup import get_logger
from core.registry import ComponentHealth, PdMModule, all_modules, get_module, worst_tier
from core.storage import get_storage
from core.storage.base import StorageBackend, new_uid, now_iso, to_json

log = get_logger("runner")


# --------------------------------------------------------------------------- #
# History reader (baselines / trend regime for scoring)
# --------------------------------------------------------------------------- #
class StorageHistoryReader:
    def __init__(self, storage: StorageBackend):
        self._s = storage

    def component_history(self, module: str, component_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        return self._s.select(
            "component_health",
            {"module": module, "component_id": component_id},
            order_by=("created_at", "desc"),
            limit=limit,
        )

    def run_count(self, module: str) -> int:
        return self._s.count("pdm_run", {"module": module, "status": "success"})


# --------------------------------------------------------------------------- #
# Trigger ids
# --------------------------------------------------------------------------- #
def make_trigger_id(trigger_type: str) -> str:
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"trg-{trigger_type}-{ts}-{new_uid()[:6]}"


# --------------------------------------------------------------------------- #
# Panel catalog persistence
# --------------------------------------------------------------------------- #
def _persist_panels(storage: StorageBackend, module: str, panels: Sequence[Dict[str, Any]]) -> None:
    for p in panels or []:
        row = {
            "module": module,
            "dashboard_uid": p.get("dashboard_uid", ""),
            "dashboard_name": p.get("dashboard_name", ""),
            "panel_id": p.get("panel_id"),
            "panel_title": p.get("panel_title", ""),
            "panel_type": p.get("panel_type", ""),
            "fields_json": p.get("fields", []),
            "sql_text": p.get("sql_text", ""),
            "is_signal": bool(p.get("is_signal", False)),
            "role": p.get("role", "none"),
            "notes": p.get("notes", ""),
            "updated_at": now_iso(),
        }
        try:
            storage.upsert("panel_catalog", ["module", "dashboard_uid", "panel_id"], row)
        except Exception:  # noqa: BLE001
            log.exception("failed to persist panel_catalog row", extra={"module": module})


# --------------------------------------------------------------------------- #
# Single-module execution (no trigger management)
# --------------------------------------------------------------------------- #
def _execute_module(
    session,
    module: PdMModule,
    window: str,
    storage: StorageBackend,
    trigger_type: str,
    trigger_id: str,
) -> Dict[str, Any]:
    run_uid = new_uid()
    started = now_iso()
    t0 = perf_counter()
    components: List[ComponentHealth] = []
    rows_fetched = 0
    status = "success"
    error = ""

    cfg = get_config()
    # Window resolution: explicit > module default > global default.
    eff_window = window or module.default_window(cfg)
    try:
        if not module.is_configured(cfg):
            raise RuntimeError(
                f"Module '{module.name}' has no dashboard URLs configured in .env "
                f"(expected {module.name.upper()}__* keys)."
            )
        bundle = module.fetch(session, eff_window)
        rows_fetched = bundle.rows_fetched
        _persist_panels(storage, module.name, bundle.panels)
        features = module.compute_features(bundle)
        history = StorageHistoryReader(storage)
        components = [c.clamp() for c in module.score(features, history)]
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error = str(exc)[:1000]
        log.exception("module run failed", extra={"module": module.name, "run_uid": run_uid})

    finished = now_iso()
    # Persist the run record (success or failed).
    storage.insert(
        "pdm_run",
        [
            {
                "run_uid": run_uid,
                "module": module.name,
                "trigger_type": trigger_type,
                "trigger_id": trigger_id,
                "data_window": eff_window,
                "started_at": started,
                "finished_at": finished,
                "status": status,
                "rows_fetched": rows_fetched,
                "components_scored": len(components),
                "error": error,
                "created_at": finished,
            }
        ],
    )
    # Persist component health rows (the longitudinal store).
    if components:
        storage.insert(
            "component_health",
            [
                {
                    "run_uid": run_uid,
                    "module": module.name,
                    "component_id": c.component_id,
                    "component_type": c.component_type,
                    "health_score": c.health_score,
                    "risk_tier": c.risk_tier,
                    "predicted_ttm_hours": c.predicted_ttm_hours,
                    "confidence": c.confidence,
                    "prediction_regime": c.prediction_regime,
                    "primary_cause": c.primary_cause,
                    "rca_json": c.rca,
                    "metrics_json": c.metrics,
                    "created_at": finished,
                }
                for c in components
            ],
        )

    return {
        "module": module.name,
        "run_uid": run_uid,
        "status": status,
        "error": error,
        "rows_fetched": rows_fetched,
        "components_scored": len(components),
        "worst_tier": worst_tier([c.risk_tier for c in components]),
        "duration_ms": int((perf_counter() - t0) * 1000),
    }


# --------------------------------------------------------------------------- #
# Trigger-wrapped public API
# --------------------------------------------------------------------------- #
def _open_trigger(storage, trigger_id, trigger_type, module_label, window) -> str:
    started = now_iso()
    storage.insert(
        "trigger_log",
        [
            {
                "trigger_id": trigger_id,
                "trigger_type": trigger_type,
                "module": module_label,
                "status": "running",
                "data_window": window,
                "started_at": started,
                "finished_at": "",
                "duration_ms": 0,
                "records_processed": 0,
                "success_count": 0,
                "failure_count": 0,
                "retry_count": 0,
                "run_uids_json": [],
                "message": "started",
                "created_at": started,
            }
        ],
    )
    return started


def _close_trigger(storage, trigger_id, started, results) -> None:
    finished = now_iso()
    started_dt = _dt.datetime.fromisoformat(started)
    finished_dt = _dt.datetime.fromisoformat(finished)
    duration_ms = int((finished_dt - started_dt).total_seconds() * 1000)
    success = sum(1 for r in results if r["status"] == "success")
    failure = sum(1 for r in results if r["status"] != "success")
    status = "success" if failure == 0 else ("partial" if success else "failed")
    storage.upsert(
        "trigger_log",
        ["trigger_id"],
        {
            "trigger_id": trigger_id,
            "status": status,
            "finished_at": finished,
            "duration_ms": duration_ms,
            "records_processed": sum(r["rows_fetched"] for r in results),
            "success_count": success,
            "failure_count": failure,
            "run_uids_json": [r["run_uid"] for r in results],
            "message": "; ".join(f"{r['module']}:{r['status']}" for r in results) or "no modules",
        },
    )
    record_event(
        "pdm_trigger_complete",
        level="INFO" if status == "success" else "WARNING",
        source="runner",
        detail={"trigger_id": trigger_id, "status": status, "results": results},
    )


def run_modules(
    module_names: Sequence[str],
    trigger_type: str = "manual",
    window: Optional[str] = None,
    trigger_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one or more named modules under a single traceable trigger."""
    from core.grafana_auth import GrafanaSession  # lazy: avoids Playwright import cost

    storage = get_storage()
    trigger_id = trigger_id or make_trigger_id(trigger_type)
    modules = [get_module(n) for n in module_names]
    label = modules[0].name if len(modules) == 1 else "all"
    # window=None means "let each module use its own default" (resolved per module).
    trig_window = window or "module-default"

    started = _open_trigger(storage, trigger_id, trigger_type, label, trig_window)
    log.info(
        "trigger started",
        extra={"trigger_id": trigger_id, "modules": module_names, "window": window},
    )

    results: List[Dict[str, Any]] = []
    try:
        with GrafanaSession() as gs:
            for module in modules:
                results.append(_execute_module(gs, module, window, storage, trigger_type, trigger_id))
    except Exception as exc:  # noqa: BLE001 - session/login failure affects all modules
        log.exception("trigger failed before/at session", extra={"trigger_id": trigger_id})
        for module in modules:
            if not any(r["module"] == module.name for r in results):
                results.append(
                    {
                        "module": module.name,
                        "run_uid": "",
                        "status": "failed",
                        "error": f"session error: {exc}",
                        "rows_fetched": 0,
                        "components_scored": 0,
                        "worst_tier": "ok",
                        "duration_ms": 0,
                    }
                )

    _close_trigger(storage, trigger_id, started, results)
    return {"trigger_id": trigger_id, "window": window, "results": results}


def run_module(
    module_name: str,
    trigger_type: str = "manual",
    window: Optional[str] = None,
    trigger_id: Optional[str] = None,
) -> Dict[str, Any]:
    return run_modules([module_name], trigger_type, window, trigger_id)


def run_all(
    trigger_type: str = "manual",
    window: Optional[str] = None,
    trigger_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run every configured registered module under one trigger."""
    cfg = get_config()
    names = [m.name for m in all_modules() if m.is_configured(cfg)]
    if not names:
        names = [m.name for m in all_modules()]  # let it report 'not configured'
    return run_modules(names, trigger_type, window, trigger_id)
