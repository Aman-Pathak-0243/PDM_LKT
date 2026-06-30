"""TRACKER fetch step.

Primary: Bad Tracker Diagnosis #2 ("Bad Tracker") — the CURRENT set of mislocated
totes (one row per stuck tracker tag, with its grid `location`, the shuttle/lift that
last errored on it, and `created_time`). This panel is current-state: the dashboard
time window does not filter it, so we fetch it once and apply the recency split in
features. Panel #4 ("Total BT Totes") is fetched as a cheap context scalar.

The #8/#6/#10 panels are per-entity drill-downs (require ${tracker}/${lift}/${shuttle}
template vars); they are documented in module.yaml as future RCA enrichment and are
NOT population signals, so the core run does not fetch them.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.config import get_config
from core.grafana_fetcher import download_panel_csv
from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.tracker.spec import signal_panel

log = get_logger("tracker.fetch")

_UID = "VAW2nmqIz"
_NAME = "Bad Tracker Diagnosis"


def _panel(pid, title, fields, role, is_signal, notes) -> Dict[str, Any]:
    return {"dashboard_uid": _UID, "dashboard_name": _NAME, "panel_id": pid,
            "panel_title": title, "panel_type": "table", "fields": fields,
            "sql_text": "", "is_signal": is_signal, "role": role, "notes": notes}


def fetch(session, window: str) -> FetchBundle:
    urls = get_config().module_dashboard_urls("tracker")
    frames: Dict[str, Any] = {}
    panels: List[Dict[str, Any]] = []
    rows = 0
    notes: Dict[str, Any] = {"window": window}

    bt_url = urls.get("BAD_TRACKER_DIAGNOSIS")
    if not bt_url:
        raise RuntimeError("TRACKER__BAD_TRACKER_DIAGNOSIS is not set in .env")

    # PRIMARY: current bad-tracker set (#2). Current-state -> window not server-filtered.
    pid = signal_panel()
    res = download_panel_csv(session, bt_url, pid, frm=window, to="now")
    frames["bad_tracker"] = res.df
    rows += res.row_count
    panels.append(_panel(pid, "Bad Tracker", list(res.df.columns), "primary", True,
                         "Current set of mislocated totes; clusters per grid location = sensor pre-failure."))

    # CONTEXT: Total BT Totes (#4) — a scalar count for the snapshot.
    try:
        tot = download_panel_csv(session, bt_url, 4, frm=window, to="now")
        if not tot.df.empty and "Value" in tot.df.columns:
            notes["total_bt_totes"] = int(tot.df["Value"].iloc[0])
        rows += tot.row_count
        panels.append(_panel(4, "Total BT Totes", list(tot.df.columns), "secondary", False,
                             "Scalar count of bad-tracker totes (snapshot context)."))
    except Exception as exc:  # noqa: BLE001
        log.warning("Total BT Totes fetch failed (continuing)", extra={"err": str(exc)[:100]})

    # Record the drill-down (template-var) panels in the catalog as non-signal, so
    # Chapter 2 / the plugin page reflect that they were enumerated and intentionally skipped.
    panels.append(_panel(8, "Tracker Journrey", ["tracker", "source", "destination", "create_timestamp"],
                         "none", False, "Per-tracker drill-down (needs ${tracker}); future RCA enrichment."))
    panels.append(_panel(6, "latest Lift Tasks WithIn Given TimeRange", [], "none", False,
                         "Per-lift drill-down (needs ${lift}); cross-module, not a tracker population signal."))
    panels.append(_panel(10, "Latest Shuttle Commands WithIn Given TimeRange", [], "none", False,
                         "Per-shuttle drill-down (needs ${shuttle}); cross-module, not a tracker population signal."))

    log.info("tracker fetch complete",
             extra={"rows": res.row_count, "total_bt_totes": notes.get("total_bt_totes")})
    return FetchBundle(frames=frames, rows_fetched=rows, panels=panels, notes=notes)
