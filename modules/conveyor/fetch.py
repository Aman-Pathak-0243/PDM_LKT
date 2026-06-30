"""CONVEYOR fetch step.

Primary  : Conveyor Zone Count — one timeseries panel per zone (1-6); each gives
           Conveyor Actual/Limit + Buffer Actual/Limit over time. Combined into one
           frame with a ``zone`` column.
Secondary: GTP (HOLD, TRANSIT) — order/tray flow state; counts surfaced as a
           module-level flow-stress context (not per-zone).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from core.config import get_config
from core.grafana_fetcher import download_panel_csv
from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.conveyor.spec import zone_panels

log = get_logger("conveyor.fetch")


def _panel(uid, name, pid, title, ptype, fields, role, is_signal, notes) -> Dict[str, Any]:
    return {"dashboard_uid": uid, "dashboard_name": name, "panel_id": pid,
            "panel_title": title, "panel_type": ptype, "fields": fields,
            "sql_text": "", "is_signal": is_signal, "role": role, "notes": notes}


def fetch(session, window: str) -> FetchBundle:
    urls = get_config().module_dashboard_urls("conveyor")
    frames: Dict[str, Any] = {}
    panels: List[Dict[str, Any]] = []
    rows = 0
    notes: Dict[str, Any] = {"window": window}

    czc = urls.get("CONVEYOR_ZONE_COUNT")
    if not czc:
        raise RuntimeError("CONVEYOR__CONVEYOR_ZONE_COUNT is not set in .env")

    zone_frames = []
    for pid, zone in zone_panels().items():
        try:
            res = download_panel_csv(session, czc, pid, frm=window, to="now")
            if not res.df.empty:
                df = res.df.copy()
                df["zone"] = zone
                zone_frames.append(df)
            rows += res.row_count
            panels.append(_panel("lavIciTDk", "Conveyor Zone Count", pid, f"Zone {zone}",
                                 "timeseries", list(res.df.columns), "primary", True,
                                 "Per-zone conveyor/buffer actual vs limit over time."))
        except Exception as exc:  # noqa: BLE001
            log.warning(f"zone {zone} fetch failed (continuing)", extra={"err": str(exc)[:120]})

    if not zone_frames:
        raise RuntimeError("No conveyor zone data fetched")
    frames["zone_counts"] = pd.concat(zone_frames, ignore_index=True)

    # SECONDARY: GTP HOLD/TRANSIT counts (module flow-stress context).
    ht = urls.get("GTP_HOLD_TRANSIT")
    if ht:
        for pid, key in ((2, "on_hold"), (4, "in_transit")):
            try:
                r = download_panel_csv(session, ht, pid, frm="now-2d", to="now")
                notes[f"system_{key}"] = r.row_count
                rows += r.row_count
                panels.append(_panel("C8jMvAcIk", "GTP (HOLD, TRANSIT)", pid,
                                     "ON_HOLD" if pid == 2 else "Transit", "table",
                                     list(r.df.columns), "secondary", True,
                                     "Order/tray flow state (count = flow stress)."))
            except Exception as exc:  # noqa: BLE001
                log.warning(f"hold/transit {key} fetch failed", extra={"err": str(exc)[:100]})

    log.info("conveyor fetch complete", extra={"rows": rows, "zones": len(zone_frames),
                                               "on_hold": notes.get("system_on_hold"),
                                               "in_transit": notes.get("system_in_transit")})
    return FetchBundle(frames=frames, rows_fetched=rows, panels=panels, notes=notes)
