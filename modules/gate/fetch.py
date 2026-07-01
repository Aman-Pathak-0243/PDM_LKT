"""GATE fetch step.

Primary : Quadron-gate-status #2 ("Gate status") — the CURRENT state of all 52 gates
          (id, status[CLOSED/OPEN REQUEST INITIATED/OPEN], aisle). This panel is
          current-state: the dashboard time window does not filter it, so one fetch
          returns the whole roster and the store carries persistence across runs.
Context : Quadron-gate-status #4 ("OPEN/REQUESTED gate's") — the status 2..3 subset;
          fetched best-effort as an integrity cross-check (its ids must equal #2's
          non-closed ids).
Secondary: Quadron Alerts #2 — free-text message rows; the front_gate/rear_gate stuck
          messages carry per-gate stuck-minutes (response latency). Best-effort.

Secondary/context fetches never fail the run — the primary roster alone is enough to score.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.config import get_config
from core.grafana_fetcher import download_panel_csv
from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.gate.spec import alerts_panel, context_panel, signal_panel

log = get_logger("gate.fetch")

_GS_UID = "5gFdGgwnz"
_GS_NAME = "Quadron-gate-status"
_AL_UID = "VxY5Zls7z"
_AL_NAME = "Quadron Alerts"


def _panel(uid, name, pid, title, fields, role, is_signal, notes) -> Dict[str, Any]:
    return {"dashboard_uid": uid, "dashboard_name": name, "panel_id": pid,
            "panel_title": title, "panel_type": "table", "fields": fields,
            "sql_text": "", "is_signal": is_signal, "role": role, "notes": notes}


def fetch(session, window: str) -> FetchBundle:
    urls = get_config().module_dashboard_urls("gate")
    frames: Dict[str, Any] = {}
    panels: List[Dict[str, Any]] = []
    rows = 0
    notes: Dict[str, Any] = {"window": window}

    gs_url = urls.get("QUADRON_GATE_STATUS")
    if not gs_url:
        raise RuntimeError("GATE__QUADRON_GATE_STATUS is not set in .env")

    # ---- PRIMARY: full gate roster + current status (#2) ------------------
    pid = signal_panel()
    res = download_panel_csv(session, gs_url, pid, frm=window, to="now")
    frames["gate_status"] = res.df
    rows += res.row_count
    panels.append(_panel(_GS_UID, _GS_NAME, pid, "Gate status", list(res.df.columns),
                         "primary", True,
                         "Current state of all 52 gates (id, status, aisle). Current-state; "
                         "window not server-filtered. Component universe."))

    # ---- CONTEXT: OPEN/REQUESTED subset (#4) — best-effort cross-check -----
    try:
        cid = context_panel()
        sub = download_panel_csv(session, gs_url, cid, frm=window, to="now")
        rows += sub.row_count
        notes["open_requested_count"] = int(sub.row_count)
        panels.append(_panel(_GS_UID, _GS_NAME, cid, "OPEN/REQUESTED gate's",
                             list(sub.df.columns), "secondary", False,
                             "Currently open / open-request-initiated gates (status 2..3). "
                             "Cross-check of #2's non-closed set."))
    except Exception as exc:  # noqa: BLE001
        log.warning("gate #4 (open/requested) fetch failed (continuing)", extra={"err": str(exc)[:120]})

    # ---- SECONDARY: Quadron Alerts #2 — gate stuck-duration (latency) -----
    al_url = urls.get("QUADRON_ALERTS")
    if al_url:
        try:
            al = download_panel_csv(session, al_url, alerts_panel(), frm=window, to="now")
            frames["alerts"] = al.df
            rows += al.row_count
            panels.append(_panel(_AL_UID, _AL_NAME, alerts_panel(), "Quadron Alerts",
                                 list(al.df.columns), "secondary", True,
                                 "front_gate/rear_gate 'open initiated|opened for N minutes' "
                                 "messages -> per-gate stuck_minutes (response latency). Shared "
                                 "panel with the Shuttle module."))
        except Exception as exc:  # noqa: BLE001
            log.warning("gate alerts fetch failed (continuing)", extra={"err": str(exc)[:120]})

    log.info("gate fetch complete",
             extra={"rows": rows, "gates": res.row_count,
                    "open_requested": notes.get("open_requested_count")})
    return FetchBundle(frames=frames, rows_fetched=rows, panels=panels, notes=notes)
