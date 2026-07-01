"""GTP STATION + SCANNER fetch step.

Scanner (primary) : GTP Scanner logs #8 "Scanner Read /No read Data" — per-scanner
                    ReadCount / NoReadCount / efficiency over the window (the misread
                    signal + scanner universe). #4 "Scanner Hits" — per-scanner volume
                    (best-effort, an independent usage proxy).
Station (primary) : Discrepancy Report Events #2 — verification_events (per-station
                    pick-verification discrepancies over the window). Best-effort: if it
                    fails, stations are still scored on the roster/status with 0 discrepancies.
Station roster    : GTP Stations #2 "Station Summary" — the 63-station universe + Active/
                    Inactive status + updated_on (current snapshot, not window-filtered).

The two primaries are independent: a scanner-source failure still lets stations be scored
and vice-versa. The run only fails hard if BOTH the scanner misread table and the station
roster are unavailable (no component universe at all).
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.config import get_config
from core.grafana_fetcher import download_panel_csv
from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.gtp_station.spec import discrepancy_panel, hits_panel, misread_panel, stations_panel

log = get_logger("gtp_station.fetch")

_SCAN_UID = "pK7-8NmVz"
_SCAN_NAME = "GTP Scanner logs"
_DISC_UID = "D6sQle2Vz"
_DISC_NAME = "Discrepancy Report Events"
_STN_UID = "GlGBwgY4z"
_STN_NAME = "GTP Stations"


def _panel(uid, name, pid, title, fields, role, is_signal, notes) -> Dict[str, Any]:
    return {"dashboard_uid": uid, "dashboard_name": name, "panel_id": pid,
            "panel_title": title, "panel_type": "table", "fields": fields,
            "sql_text": "", "is_signal": is_signal, "role": role, "notes": notes}


def fetch(session, window: str) -> FetchBundle:
    urls = get_config().module_dashboard_urls("gtp_station")
    frames: Dict[str, Any] = {}
    panels: List[Dict[str, Any]] = []
    rows = 0
    notes: Dict[str, Any] = {"window": window}

    scan_url = urls.get("GTP_SCANNER_LOGS")
    stn_url = urls.get("GTP_STATIONS")
    disc_url = urls.get("DISCREPANCY_REPORT_EVENTS")
    if not scan_url and not stn_url:
        raise RuntimeError(
            "GTP_STATION__GTP_SCANNER_LOGS and GTP_STATION__GTP_STATIONS are both unset in .env"
        )

    # ---- SCANNER primary: per-scanner misread (#8) + hits (#4) ------------
    if scan_url:
        res = download_panel_csv(session, scan_url, misread_panel(), frm=window, to="now")
        frames["misread"] = res.df
        rows += res.row_count
        notes["scanner_rows"] = res.row_count
        panels.append(_panel(_SCAN_UID, _SCAN_NAME, misread_panel(), "Scanner Read /No read Data",
                             list(res.df.columns), "primary", True,
                             "Per-scanner ReadCount/NoReadCount/efficiency over the window -> misread rate. "
                             "Scanner component universe."))
        try:
            h = download_panel_csv(session, scan_url, hits_panel(), frm=window, to="now")
            frames["hits"] = h.df
            rows += h.row_count
            panels.append(_panel(_SCAN_UID, _SCAN_NAME, hits_panel(), "Scanner Hits",
                                 list(h.df.columns), "secondary", True,
                                 "Per-scanner hit count (usage/volume proxy)."))
        except Exception as exc:  # noqa: BLE001
            log.warning("scanner hits fetch failed (continuing on misread only)",
                        extra={"err": str(exc)[:120]})
        # Non-signal panels on the scanner dashboard (documented, not fetched).
        panels.append(_panel(_SCAN_UID, _SCAN_NAME, 2, "GTP Time wise scanner logs", [], "none", False,
                             "Raw scanner_events (scanner/decision/decision_reason) — heavy, no CSV; aggregated by #8."))
        panels.append(_panel(_SCAN_UID, _SCAN_NAME, 6, "Tote Hits", [], "none", False,
                             "Per-container hit count — not a scanner signal."))

    # ---- STATION primary: per-station discrepancies (#2) — best-effort ----
    if disc_url:
        try:
            d = download_panel_csv(session, disc_url, discrepancy_panel(), frm=window, to="now")
            frames["discrepancy"] = d.df
            rows += d.row_count
            notes["discrepancy_rows"] = d.row_count
            panels.append(_panel(_DISC_UID, _DISC_NAME, discrepancy_panel(), "Discrepancy Report Events",
                                 list(d.df.columns), "primary", True,
                                 "verification_events per station (pick-verification discrepancies) over the window."))
        except Exception as exc:  # noqa: BLE001
            log.warning("discrepancy fetch failed (stations scored on roster/status only)",
                        extra={"err": str(exc)[:120]})

    # ---- STATION roster: 63-station universe + status (#2) ----------------
    if stn_url:
        try:
            s = download_panel_csv(session, stn_url, stations_panel(), frm=window, to="now")
            frames["stations"] = s.df
            rows += s.row_count
            notes["station_rows"] = s.row_count
            panels.append(_panel(_STN_UID, _STN_NAME, stations_panel(), "Station Summary",
                                 list(s.df.columns), "primary", True,
                                 "63-station roster + active_status + operation_type + updated_on. Station universe."))
        except Exception as exc:  # noqa: BLE001
            log.warning("station roster fetch failed", extra={"err": str(exc)[:120]})

    if "misread" not in frames and "stations" not in frames:
        raise RuntimeError("No GTP scanner or station data fetched (both primaries failed)")

    log.info("gtp_station fetch complete",
             extra={"rows": rows, "scanner_rows": notes.get("scanner_rows"),
                    "discrepancy_rows": notes.get("discrepancy_rows"),
                    "station_rows": notes.get("station_rows")})
    return FetchBundle(frames=frames, rows_fetched=rows, panels=panels, notes=notes)
