"""CONTROLLER / COMPUTE fetch step.

Primary : CPU Stats #17 "CPU Utilisation" — EXEC [DBA].[dbo].[getCPUDetails] -> a single row
          (cpu_idle, cpu_sql) for the controller compute node. Current-state (the window does not
          filter the proc; the store provides history across runs). If the proc ever returns per-host
          rows, features.py keys by the host/node column (scalable to N nodes).

The run fails only if the CPU panel is unavailable / empty (no compute signal).
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.config import get_config
from core.grafana_fetcher import download_panel_csv
from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.controller.spec import cpu_panel

log = get_logger("controller.fetch")

_UID = "CwTEp_GSz"
_NAME = "CPU Stats"


def _panel(pid, title, fields, role, is_signal, notes) -> Dict[str, Any]:
    return {"dashboard_uid": _UID, "dashboard_name": _NAME, "panel_id": pid,
            "panel_title": title, "panel_type": "table", "fields": fields,
            "sql_text": "", "is_signal": is_signal, "role": role, "notes": notes}


def fetch(session, window: str) -> FetchBundle:
    urls = get_config().module_dashboard_urls("controller")
    url = urls.get("CPU_STATS")
    if not url:
        raise RuntimeError("CONTROLLER__CPU_STATS is unset in .env")

    res = download_panel_csv(session, url, cpu_panel(), frm=window, to="now")
    frames: Dict[str, Any] = {"cpu": res.df}
    panels: List[Dict[str, Any]] = [
        _panel(cpu_panel(), "CPU Utilisation", list(res.df.columns), "primary", True,
               "EXEC getCPUDetails -> cpu_idle, cpu_sql. utilization% = 100 - cpu_idle. Current-state "
               "snapshot of the controller compute node; the store provides trend/sustained-high.")
    ]
    if res.df is None or res.df.empty:
        raise RuntimeError("No CPU data fetched (CPU Stats #17 empty)")

    log.info("controller fetch complete", extra={"rows": res.row_count, "cols": list(res.df.columns)})
    return FetchBundle(frames=frames, rows_fetched=res.row_count, panels=panels,
                       notes={"window": window})
