"""DECANTING STATION + SCANNER fetch step.

Scanner (primary) : GTP Scanner logs #8 "Scanner Read /No read Data" — per-scanner
                    ReadCount / NoReadCount / efficiency over the window. SHARED panel with the
                    GTP module; features.py filters it to the decant/compaction devices this
                    module owns (the rest belong to gtp_station). This is the strong live signal.
Station roster    : Decanting station report #2 "Decanting Station Report" — the DS001..DS010
                    station universe + Active/Inactive status + assigned user (current snapshot).
Station throughput: StationWise Decanted Cartons Count #2 — per-station decanted-carton count over
                    the window (best-effort). Used for the idle-while-active anomaly + utilization.

The scanner and station roster are independent primaries: a scanner-source failure still lets
stations be scored (and vice-versa). The run only fails hard if BOTH the scanner misread table and
the station roster are unavailable (no component universe at all). Throughput is best-effort.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.config import get_config
from core.grafana_fetcher import download_panel_csv
from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.decant_station.spec import cartons_panel, misread_panel, station_report_panel

log = get_logger("decant_station.fetch")

_SCAN_UID = "pK7-8NmVz"
_SCAN_NAME = "GTP Scanner logs"
_STN_UID = "B4i1-HpVz"
_STN_NAME = "Decanting station report"
_CC_UID = "n1oZnY_Vz"
_CC_NAME = "StationWise Decanted Cartons Count"


def _panel(uid, name, pid, title, fields, role, is_signal, notes) -> Dict[str, Any]:
    return {"dashboard_uid": uid, "dashboard_name": name, "panel_id": pid,
            "panel_title": title, "panel_type": "table", "fields": fields,
            "sql_text": "", "is_signal": is_signal, "role": role, "notes": notes}


def fetch(session, window: str) -> FetchBundle:
    urls = get_config().module_dashboard_urls("decant_station")
    frames: Dict[str, Any] = {}
    panels: List[Dict[str, Any]] = []
    rows = 0
    notes: Dict[str, Any] = {"window": window}

    scan_url = urls.get("GTP_SCANNER_LOGS")
    stn_url = urls.get("DECANTING_STATION_REPORT")
    cc_url = urls.get("STATIONWISE_DECANTED_CARTONS")
    if not scan_url and not stn_url:
        raise RuntimeError(
            "DECANT_STATION__GTP_SCANNER_LOGS and DECANT_STATION__DECANTING_STATION_REPORT "
            "are both unset in .env"
        )

    # ---- SCANNER primary: per-scanner misread (#8), filtered downstream ----
    if scan_url:
        res = download_panel_csv(session, scan_url, misread_panel(), frm=window, to="now")
        frames["misread"] = res.df
        rows += res.row_count
        notes["scanner_rows"] = res.row_count
        panels.append(_panel(_SCAN_UID, _SCAN_NAME, misread_panel(), "Scanner Read /No read Data",
                             list(res.df.columns), "primary", True,
                             "Per-scanner ReadCount/NoReadCount/efficiency over the window -> misread rate. "
                             "SHARED with gtp_station; filtered to decant/compaction devices here."))

    # ---- STATION roster: DS001..DS010 universe + status (#2) --------------
    if stn_url:
        try:
            s = download_panel_csv(session, stn_url, station_report_panel(), frm=window, to="now")
            frames["stations"] = s.df
            rows += s.row_count
            notes["station_rows"] = s.row_count
            panels.append(_panel(_STN_UID, _STN_NAME, station_report_panel(), "Decanting Station Report",
                                 list(s.df.columns), "primary", True,
                                 "Decant station roster (Station ID, active_status, User). Station universe."))
        except Exception as exc:  # noqa: BLE001
            log.warning("decant station roster fetch failed", extra={"err": str(exc)[:120]})

    # ---- STATION throughput: per-station decanted cartons (#2) — best-effort
    if cc_url:
        try:
            c = download_panel_csv(session, cc_url, cartons_panel(), frm=window, to="now")
            frames["cartons"] = c.df
            rows += c.row_count
            notes["carton_rows"] = c.row_count
            panels.append(_panel(_CC_UID, _CC_NAME, cartons_panel(), "Station-Wise-Decanted-Cartons",
                                 list(c.df.columns), "secondary", True,
                                 "Per-station decanted-carton count over the window (throughput / idle-while-active)."))
        except Exception as exc:  # noqa: BLE001
            log.warning("station throughput fetch failed (stations scored on roster/status only)",
                        extra={"err": str(exc)[:120]})

    # Non-signal panels (documented, not fetched).
    panels.append(_panel(_STN_UID, _STN_NAME, 4, "Material Type Available", [], "none", False,
                         "Partition inventory by hsn_classification — not a health signal."))
    panels.append(_panel("E_nYUnU4z", "Discrepancy Marked Barcode", 2, "Discrepancy Marked Barcode", [], "none", False,
                         "DROPPED: drill-down into discrepancy_details by ${Serial_No}; no station key; frozen 2022. "
                         "No live per-station discrepancy rate."))
    panels.append(_panel("LQMn4RU4k", "Discrepancy Marked Carton", 2, "Discrepancy marked carton/barcode", [], "none", False,
                         "DROPPED: drill-down into discrepancy_details by ${Carton_Id}; no station key; frozen 2022."))

    if "misread" not in frames and "stations" not in frames:
        raise RuntimeError("No decant scanner or station data fetched (both primaries failed)")

    log.info("decant_station fetch complete",
             extra={"rows": rows, "scanner_rows": notes.get("scanner_rows"),
                    "station_rows": notes.get("station_rows"), "carton_rows": notes.get("carton_rows")})
    return FetchBundle(frames=frames, rows_fetched=rows, panels=panels, notes=notes)
