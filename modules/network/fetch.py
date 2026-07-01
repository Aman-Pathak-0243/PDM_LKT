"""NETWORK / COMMS fetch step.

Primary (windowed) : Quadron Network status #4 "Shuttle network status specific date" — per-shuttle
                     network uptime% since ${Date}. We set ${Date} = the window START (now - N) so the
                     panel returns a WINDOWED downtime% for the full 124-shuttle roster.
Recency (today)    : Quadron Network status #2 "shuttle/day %uptime" — per-shuttle uptime% since
                     midnight today (best-effort). Joined by shuttle_id to flag links worse TODAY than
                     their window average (accelerating degradation).

The run fails only if the windowed panel (#4) is unavailable (no roster / no signal). The today
panel (#2) is best-effort — a failure there just drops the recency term.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, List

from core.config import get_config
from core.grafana_fetcher import download_panel_csv
from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.network.spec import date_var, today_panel, windowed_panel

log = get_logger("network.fetch")

_UID = "gL0OBnq7z"
_NAME = "Quadron Network status"
_WINDOW_RE = re.compile(r"now-(\d+)\s*([smhdw])", re.I)
_UNIT_HOURS = {"s": 1 / 3600.0, "m": 1 / 60.0, "h": 1.0, "d": 24.0, "w": 168.0}


def _window_hours(window: str, default: float = 48.0) -> float:
    m = _WINDOW_RE.search(window or "")
    if not m:
        return default
    return max(float(m.group(1)) * _UNIT_HOURS.get(m.group(2).lower(), 1.0), 1e-6)


def window_start_str(window: str) -> str:
    """The window start (now - N) as 'YYYY-MM-DD HH:MM:SS' for the #4 ${Date} var."""
    start = _dt.datetime.now() - _dt.timedelta(hours=_window_hours(window))
    return start.strftime("%Y-%m-%d %H:%M:%S")


def _panel(pid, title, fields, role, is_signal, notes) -> Dict[str, Any]:
    return {"dashboard_uid": _UID, "dashboard_name": _NAME, "panel_id": pid,
            "panel_title": title, "panel_type": "table", "fields": fields,
            "sql_text": "", "is_signal": is_signal, "role": role, "notes": notes}


def fetch(session, window: str) -> FetchBundle:
    urls = get_config().module_dashboard_urls("network")
    url = urls.get("QUADRON_NETWORK_STATUS")
    if not url:
        raise RuntimeError("NETWORK__QUADRON_NETWORK_STATUS is unset in .env")

    frames: Dict[str, Any] = {}
    panels: List[Dict[str, Any]] = []
    rows = 0
    date_str = window_start_str(window)
    notes: Dict[str, Any] = {"window": window, "date_var": date_str}

    # ---- PRIMARY (windowed): #4 with ${Date} = window start --------------
    res = download_panel_csv(session, url, windowed_panel(), frm=window, to="now",
                             variables={date_var(): date_str})
    frames["windowed"] = res.df
    rows += res.row_count
    notes["windowed_rows"] = res.row_count
    panels.append(_panel(windowed_panel(), "Shuttle network status specific date",
                         list(res.df.columns), "primary", True,
                         f"Per-shuttle uptime% since ${{{date_var()}}}={date_str} (windowed). "
                         "downtime% = 100 - uptime%. The 124-shuttle roster + core comms signal."))

    # ---- RECENCY (today): #2 since midnight — best-effort ----------------
    try:
        t = download_panel_csv(session, url, today_panel(), frm=window, to="now")
        frames["today"] = t.df
        rows += t.row_count
        notes["today_rows"] = t.row_count
        panels.append(_panel(today_panel(), "shuttle/day %uptime",
                             list(t.df.columns), "secondary", True,
                             "Per-shuttle uptime% since midnight today (recency; joined by shuttle_id)."))
    except Exception as exc:  # noqa: BLE001
        log.warning("today-uptime fetch failed (scoring on windowed downtime only)",
                    extra={"err": str(exc)[:120]})

    if "windowed" not in frames or frames["windowed"] is None or frames["windowed"].empty:
        raise RuntimeError("No windowed network uptime data fetched (#4 empty)")

    log.info("network fetch complete",
             extra={"rows": rows, "windowed_rows": notes.get("windowed_rows"),
                    "today_rows": notes.get("today_rows"), "date_var": date_str})
    return FetchBundle(frames=frames, rows_fetched=rows, panels=panels, notes=notes)
