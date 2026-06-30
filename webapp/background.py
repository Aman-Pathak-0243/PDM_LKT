"""Background execution of manual PdM triggers.

Manual "Run now" requests must not block the event loop or the HTTP response, so
they are submitted to a small thread pool and the trigger id is returned
immediately. The client polls ``/api/triggers/{id}`` for progress. (Automated runs
go through APScheduler in ``core.scheduler`` instead.)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from core.logging_setup import get_logger
from core.runner import make_trigger_id, run_all, run_module

log = get_logger("webapp.background")
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pdm-run")


def _safe(fn, *args) -> None:
    try:
        fn(*args)
    except Exception:  # noqa: BLE001
        log.exception("background run crashed")


def submit_run(module: Optional[str], window: Optional[str], trigger_type: str = "manual") -> str:
    """Kick off a run on a worker thread; return its trigger id immediately."""
    trigger_id = make_trigger_id(trigger_type)
    if not module or module in ("all", "*"):
        _executor.submit(_safe, run_all, trigger_type, window, trigger_id)
    else:
        _executor.submit(_safe, run_module, module, trigger_type, window, trigger_id)
    log.info("submitted run", extra={"trigger_id": trigger_id, "module": module or "all"})
    return trigger_id
