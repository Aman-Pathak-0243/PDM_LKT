"""JSON API router.

Thin HTTP layer over webapp.services / webapp.exporting / core.scheduler. All
endpoints are local/LAN. Read endpoints back both the HTML pages and any external
tooling; write endpoints (run/automation/storage/ack) mutate state and are audited.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from core.audit import record_event
from core.config import get_config
from core.registry import all_modules
from core.scheduler import get_scheduler
from core.storage import get_storage
from core.storage.base import now_iso
from webapp import exporting, services
from webapp.background import submit_run

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class RunRequest(BaseModel):
    module: Optional[str] = None        # module name, or None/"all"
    window: Optional[str] = None


class AutomationRequest(BaseModel):
    scope: str = "global"
    enabled: bool = False
    interval_minutes: int = 60
    data_window: Optional[str] = None


class DeleteRequest(BaseModel):
    table: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    trigger_id: Optional[str] = None
    module: Optional[str] = None
    confirm: bool = False


class ArchiveRequest(BaseModel):
    table: str
    before: str


class RestoreRequest(BaseModel):
    file: str


class AckRequest(BaseModel):
    module: str
    component_id: str
    acked_by: str = "operator"
    note: str = ""


# --------------------------------------------------------------------------- #
# Health / system
# --------------------------------------------------------------------------- #
@router.get("/health")
def health():
    return {
        "status": "ok",
        "backend": get_storage().backend_name,
        "modules": [m.name for m in all_modules()],
        "time": now_iso(),
    }


@router.get("/performance")
def performance():
    return services.performance_metrics()


# --------------------------------------------------------------------------- #
# Modules / components
# --------------------------------------------------------------------------- #
@router.get("/modules")
def modules():
    return services.module_summaries()


@router.get("/overview/analytics")
def overview_analytics(window: Optional[str] = Query(None)):
    """Fleet-wide rollups for the Overview page's Graphical Overview tab."""
    return services.overview_analytics(window)


@router.get("/modules/{name}/methodology")
def module_methodology(name: str):
    from core.registry import all_modules, module_methodology as _mm

    mod = next((m for m in all_modules() if m.name == name), None)
    if not mod:
        raise HTTPException(404, "module not found")
    return _mm(mod)


@router.get("/modules/{name}/components")
def module_components(name: str):
    return services.latest_components(name)


@router.get("/modules/{name}/components/{cid}/history")
def component_history(name: str, cid: str, limit: int = 300):
    return services.component_history(name, cid, limit)


# --------------------------------------------------------------------------- #
# Runs / triggers
# --------------------------------------------------------------------------- #
@router.post("/run")
def run(req: RunRequest):
    # window None -> each module uses its own default (resolved in the runner).
    trigger_id = submit_run(req.module, req.window, "manual")
    return {"trigger_id": trigger_id, "module": req.module or "all"}


@router.get("/triggers")
def triggers(limit: int = 50, type: Optional[str] = None, status: Optional[str] = None):
    filters = {}
    if type:
        filters["trigger_type"] = type
    if status:
        filters["status"] = status
    return services.recent_triggers(limit, filters or None)


@router.get("/triggers/{trigger_id}")
def trigger_detail(trigger_id: str):
    trig = services.get_trigger(trigger_id)
    if not trig:
        raise HTTPException(404, "trigger not found")
    return {"trigger": trig, "runs": services.runs_for_trigger(trigger_id)}


# --------------------------------------------------------------------------- #
# Automation
# --------------------------------------------------------------------------- #
@router.get("/automation")
def automation_status():
    return get_scheduler().status_all()


@router.post("/automation")
def automation_apply(req: AutomationRequest):
    return get_scheduler().apply(req.scope, req.enabled, req.interval_minutes, req.data_window)


@router.post("/automation/run")
def automation_run_now(req: AutomationRequest):
    trigger_id = submit_run(None if req.scope == "global" else req.scope, req.data_window, "auto")
    return {"trigger_id": trigger_id, "scope": req.scope}


# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #
@router.get("/logs")
def logs(q: str = "", level: str = "", module: str = "", since_hours: float = 0, limit: int = 200):
    return services.search_events(q, level, module, since_hours or None, limit)


# --------------------------------------------------------------------------- #
# Storage management
# --------------------------------------------------------------------------- #
@router.get("/storage")
def storage_overview():
    return services.storage_overview()


@router.get("/storage/archives")
def storage_archives():
    return exporting.list_archives()


@router.get("/storage/export")
def storage_export(
    table: str,
    fmt: str = "csv",
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    trigger_id: Optional[str] = Query(None),
    module: Optional[str] = Query(None),
):
    try:
        filename, content, media = exporting.export(table, fmt, date_from, date_to, trigger_id, module)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/storage/delete")
def storage_delete(req: DeleteRequest):
    try:
        deleted = exporting.delete(
            req.table, req.date_from, req.date_to, req.trigger_id, req.module, req.confirm
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"deleted": deleted}


@router.post("/storage/archive")
def storage_archive(req: ArchiveRequest):
    try:
        return exporting.archive(req.table, req.before)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/storage/restore")
def storage_restore(req: RestoreRequest):
    try:
        return exporting.restore(req.file)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc))


# --------------------------------------------------------------------------- #
# Plugins / catalog / acks
# --------------------------------------------------------------------------- #
@router.get("/plugins")
def plugins():
    cfg = get_config()
    storage = get_storage()
    out = []
    for m in all_modules():
        panels = storage.select("panel_catalog", {"module": m.name})
        run = services.last_run(m.name)
        out.append(
            {
                "name": m.name,
                "title": m.title,
                "component_type": m.component_type,
                "configured": m.is_configured(cfg),
                "dashboards": m.dashboards(cfg),
                "panel_count": len(panels),
                "signal_panels": sum(1 for p in panels if p.get("is_signal")),
                "last_run_at": run.get("finished_at") if run else None,
                "last_run_status": run.get("status") if run else None,
            }
        )
    return out


@router.get("/catalog")
def catalog(module: Optional[str] = None):
    return get_storage().select("panel_catalog", {"module": module} if module else None)


@router.post("/ack")
def ack(req: AckRequest):
    get_storage().insert(
        "maintenance_ack",
        [
            {
                "module": req.module,
                "component_id": req.component_id,
                "acked_by": req.acked_by,
                "acked_at": now_iso(),
                "note": req.note,
            }
        ],
    )
    record_event(
        "maintenance_ack", source="webapp", module=req.module,
        detail={"component_id": req.component_id, "by": req.acked_by},
    )
    return {"status": "ok"}
