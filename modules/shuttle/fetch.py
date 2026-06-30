"""SHUTTLE fetch step.

Primary  : QUADRON ERROR HISTORY #2 (per-shuttle error events)
Primary  : QUADRON CYCLES #2        (per-shuttle cumulative cycles = RUL basis)
Secondary: Daily Shuttle Errors #2  (current aggregated errors)
Secondary: Bad Tracker #2           (current shuttle recurrence + pick-error status)
Secondary: Quadron Alerts #2        (current free-text alerts)

The two primaries are required; secondaries are best-effort.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.config import get_config
from core.grafana_fetcher import download_panel_csv
from core.logging_setup import get_logger
from core.registry import FetchBundle

log = get_logger("shuttle.fetch")


def _panel(uid, name, pid, title, fields, role, is_signal, notes) -> Dict[str, Any]:
    return {"dashboard_uid": uid, "dashboard_name": name, "panel_id": pid,
            "panel_title": title, "panel_type": "table", "fields": fields,
            "sql_text": "", "is_signal": is_signal, "role": role, "notes": notes}


def _try(session, url, pid, window, frames, key, panels, entry):
    try:
        res = download_panel_csv(session, url, pid, frm=window, to="now")
        frames[key] = res.df
        panels.append(entry(list(res.df.columns)))
        return res.row_count
    except Exception as exc:  # noqa: BLE001
        log.warning(f"{key} fetch failed (continuing)", extra={"err": str(exc)[:120]})
        return 0


def fetch(session, window: str) -> FetchBundle:
    urls = get_config().module_dashboard_urls("shuttle")
    frames: Dict[str, Any] = {}
    panels: List[Dict[str, Any]] = []
    rows = 0

    # PRIMARY: errors
    err_url = urls.get("QUADRON_ERROR_HISTORY")
    if not err_url:
        raise RuntimeError("SHUTTLE__QUADRON_ERROR_HISTORY is not set in .env")
    res = download_panel_csv(session, err_url, 2, frm=window, to="now")
    frames["errors"] = res.df
    rows += res.row_count
    panels.append(_panel("K2QzauWVz", "QUADRON ERROR HISTORY", 2, "Quadron Shuttle Errors",
                         list(res.df.columns), "primary", True, "Per-shuttle fault events."))

    # PRIMARY: cycles
    cyc_url = urls.get("QUADRON_CYCLES")
    if not cyc_url:
        raise RuntimeError("SHUTTLE__QUADRON_CYCLES is not set in .env")
    cyc = download_panel_csv(session, cyc_url, 2, frm=window, to="now")
    frames["cycles"] = cyc.df
    rows += cyc.row_count
    panels.append(_panel("8dDcXomVz", "QUADRON CYCLES", 2, "Shuttle Cycles",
                         list(cyc.df.columns), "primary", True, "Cumulative cycles per shuttle (wear/RUL basis)."))

    # SECONDARIES (best-effort)
    if urls.get("DAILY_SHUTTLE_ERRORS"):
        rows += _try(session, urls["DAILY_SHUTTLE_ERRORS"], 2, window, frames, "daily", panels,
                     lambda c: _panel("N8QvGxQIk", "Daily Shuttle Errors", 2, "Daily Shuttle Errors",
                                      c, "secondary", True, "Current aggregated errors (error_desc -> shuttles)."))
    if urls.get("BAD_TRACKER_DIAGNOSIS"):
        rows += _try(session, urls["BAD_TRACKER_DIAGNOSIS"], 2, window, frames, "bad_tracker", panels,
                     lambda c: _panel("VAW2nmqIz", "Bad Tracker Diagnosis", 2, "Bad Tracker",
                                      c, "secondary", True, "Current shuttle recurrence + SHUTTLE_PICK_ERROR."))
    if urls.get("QUADRON_ALERTS"):
        rows += _try(session, urls["QUADRON_ALERTS"], 2, window, frames, "alerts", panels,
                     lambda c: _panel("VxY5Zls7z", "Quadron Alerts", 2, "Quadron Alerts",
                                      c, "secondary", True, "Current free-text active alerts."))

    log.info("shuttle fetch complete", extra={"rows": rows, "frames": list(frames)})
    return FetchBundle(frames=frames, rows_fetched=rows, panels=panels, notes={"window": window})
