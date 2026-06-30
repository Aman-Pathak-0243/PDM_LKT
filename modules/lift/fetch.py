"""LIFT fetch step — pull the resolved panels into DataFrames.

Primary  : Lift Error History #2  (per-lift fault events; full history)
Secondary: Bad Tracker #2          (lift recurrence + current ERROR status)
Secondary: Lift Error Analysis #2  (per-lift task counts = load context)

Secondary fetches are best-effort: if one fails the run continues on the primary
signal. Each fetched panel is recorded as a ``panel_catalog`` entry.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.config import get_config
from core.grafana_fetcher import download_panel_csv
from core.logging_setup import get_logger
from core.registry import FetchBundle

log = get_logger("lift.fetch")

# Resolved panel ids (see module.yaml).
PRIMARY_PANEL = 2
BAD_TRACKER_PANEL = 2
TASK_COUNT_PANEL = 2


def _panel_entry(uid, name, pid, title, ptype, fields, role, is_signal, notes) -> Dict[str, Any]:
    return {
        "dashboard_uid": uid,
        "dashboard_name": name,
        "panel_id": pid,
        "panel_title": title,
        "panel_type": ptype,
        "fields": fields,
        "sql_text": "",
        "is_signal": is_signal,
        "role": role,
        "notes": notes,
    }


def fetch(session, window: str) -> FetchBundle:
    cfg = get_config()
    urls = cfg.module_dashboard_urls("lift")
    frames: Dict[str, Any] = {}
    panels: List[Dict[str, Any]] = []
    rows = 0

    # ---- PRIMARY: Lift Error History --------------------------------------
    primary_url = urls.get("LIFT_ERROR_HISTORY")
    if not primary_url:
        raise RuntimeError("LIFT__LIFT_ERROR_HISTORY is not set in .env")
    res = download_panel_csv(session, primary_url, PRIMARY_PANEL, frm=window, to="now")
    frames["errors"] = res.df
    rows += res.row_count
    panels.append(
        _panel_entry(
            "wQds52G4z", "Lift Error History", PRIMARY_PANEL, "Lift Error History",
            "table", list(res.df.columns), "primary", True,
            "Per-lift fault events (lift_id, error_code, error_desc, created_time).",
        )
    )

    # ---- SECONDARY: Bad Tracker (lift recurrence + current status) --------
    bt_url = urls.get("BAD_TRACKER_DIAGNOSIS")
    if bt_url:
        try:
            bt = download_panel_csv(session, bt_url, BAD_TRACKER_PANEL, frm=window, to="now")
            frames["bad_tracker"] = bt.df
            rows += bt.row_count
            panels.append(
                _panel_entry(
                    "VAW2nmqIz", "Bad Tracker Diagnosis", BAD_TRACKER_PANEL, "Bad Tracker",
                    "table", list(bt.df.columns), "secondary", True,
                    "lift_id + lift status when bad tracker is lift-associated.",
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("bad tracker fetch failed (continuing)", extra={"err": str(exc)[:120]})

    # ---- SECONDARY: Lift Error Analysis task counts (load context) --------
    lea_url = urls.get("LIFT_ERROR_ANALYSIS")
    if lea_url:
        try:
            lea = download_panel_csv(session, lea_url, TASK_COUNT_PANEL, frm=window, to="now")
            frames["task_counts"] = lea.df
            rows += lea.row_count
            panels.append(
                _panel_entry(
                    "EqDhnQ9Sz", "Lift Error Analysis", TASK_COUNT_PANEL,
                    "Lift Level Task Creation Count", "table", list(lea.df.columns),
                    "secondary", False, "Per-aisle/position cumulative task counts (load proxy).",
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("task-count fetch failed (continuing)", extra={"err": str(exc)[:120]})

    log.info("lift fetch complete", extra={"rows": rows, "frames": list(frames)})
    return FetchBundle(frames=frames, rows_fetched=rows, panels=panels, notes={"window": window})
