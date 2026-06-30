"""Automation scheduler (APScheduler, in-process, time-triggered).

Runs **independently of the dashboard**: the background scheduler lives in the
server process (a daemon thread pool), so closing the browser never stops
automation. Only stopping the service halts it. Schedules persist in
``automation_config`` and are reloaded on startup, so a restart resumes automation.

Scope semantics:
* ``global`` → run every configured module on the interval.
* ``<module>`` → run just that module on the interval.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.audit import record_event
from core.config import get_config
from core.logging_setup import get_logger
from core.runner import make_trigger_id, run_all, run_module
from core.storage import get_storage
from core.storage.base import now_iso

log = get_logger("scheduler")

_scheduler: Optional["AutomationScheduler"] = None
_lock = threading.Lock()


def _job_id(scope: str) -> str:
    return f"auto:{scope}"


class AutomationScheduler:
    def __init__(self):
        self._sched = BackgroundScheduler(
            executors={"default": ThreadPoolExecutor(max_workers=4)},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
            timezone="UTC",
        )

    # ----- lifecycle ------------------------------------------------------ #
    def start(self) -> None:
        if not self._sched.running:
            self._sched.start()
            log.info("automation scheduler started")
        self._reload_from_config()

    def shutdown(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)
            log.info("automation scheduler stopped")

    # ----- job target ----------------------------------------------------- #
    @staticmethod
    def _fire(scope: str) -> None:
        trigger_id = make_trigger_id("auto")
        # Use the window the operator configured for this scope (may be None ->
        # each module falls back to its own default).
        rows = get_storage().select("automation_config", {"scope": scope})
        window = rows[0].get("data_window") if rows else None
        log.info("automation firing", extra={"scope": scope, "trigger_id": trigger_id, "window": window})
        try:
            if scope == "global":
                run_all(trigger_type="auto", window=window, trigger_id=trigger_id)
            else:
                run_module(scope, trigger_type="auto", window=window, trigger_id=trigger_id)
        except Exception:  # noqa: BLE001 - never let a job crash the scheduler
            log.exception("automation run errored", extra={"scope": scope})

    # ----- config-driven scheduling --------------------------------------- #
    def _reload_from_config(self) -> None:
        storage = get_storage()
        for row in storage.select("automation_config"):
            if row.get("enabled"):
                self._add_or_update_job(
                    row["scope"], int(row.get("interval_minutes") or 60)
                )

    def _add_or_update_job(self, scope: str, interval_minutes: int) -> None:
        self._sched.add_job(
            self._fire,
            trigger=IntervalTrigger(minutes=max(1, interval_minutes)),
            id=_job_id(scope),
            args=[scope],
            replace_existing=True,
        )

    def apply(
        self,
        scope: str,
        enabled: bool,
        interval_minutes: int,
        data_window: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist an automation config and (re)schedule or remove its job."""
        cfg = get_config()
        storage = get_storage()
        interval_minutes = max(1, int(interval_minutes))
        storage.upsert(
            "automation_config",
            ["scope"],
            {
                "scope": scope,
                "enabled": bool(enabled),
                "interval_minutes": interval_minutes,
                "data_window": data_window or cfg.fetch_default_window,
                "updated_at": now_iso(),
            },
        )
        if enabled:
            self._add_or_update_job(scope, interval_minutes)
        else:
            try:
                self._sched.remove_job(_job_id(scope))
            except Exception:  # noqa: BLE001 - job may not exist
                pass
        record_event(
            "automation_config_changed",
            source="scheduler",
            module=None if scope == "global" else scope,
            detail={"scope": scope, "enabled": enabled, "interval_minutes": interval_minutes},
        )
        return self.status_for(scope)

    # ----- status --------------------------------------------------------- #
    def status_for(self, scope: str) -> Dict[str, Any]:
        storage = get_storage()
        rows = storage.select("automation_config", {"scope": scope})
        conf = rows[0] if rows else {"scope": scope, "enabled": False, "interval_minutes": 60}
        job = self._sched.get_job(_job_id(scope)) if self._sched.running else None
        next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
        return {
            "scope": scope,
            "enabled": bool(conf.get("enabled")),
            "interval_minutes": int(conf.get("interval_minutes") or 60),
            "data_window": conf.get("data_window"),
            "next_run_at": next_run,
        }

    def status_all(self) -> List[Dict[str, Any]]:
        storage = get_storage()
        scopes = {r["scope"] for r in storage.select("automation_config")}
        scopes.add("global")
        return [self.status_for(s) for s in sorted(scopes)]

    def trigger_now(self, scope: str) -> None:
        self._fire(scope)


def get_scheduler() -> AutomationScheduler:
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = AutomationScheduler()
        return _scheduler
