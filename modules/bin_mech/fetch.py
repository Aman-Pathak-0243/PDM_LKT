"""BIN / TOTE-MECHANICAL fetch step.

Primary   : Bin blocked (i.e. tote tilted) #2 — the CURRENT set of blocked bins
            (one row per blocked tote/partition: location, aisle, level, container,
            blockedTime). Current-state; the component universe is derived from it.
Secondary : Bin Block History #2 — the FROZEN historical block log (shuttle_command
            status=10, source/destination bin locations) → per-location historical block
            frequency (chronic-slot enrichment). Best-effort: it is large (~26k rows) and
            frozen, so if it fails/times out the run continues on current + store recurrence.

The #4 "update_bin_block" panel is an UPDATE (write) action and #5 is unacknowledged bids —
both are non-signal and are recorded in the catalog but never fetched.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.config import get_config
from core.grafana_fetcher import download_panel_csv
from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.bin_mech.spec import history_panel, tilted_panel

log = get_logger("bin_mech.fetch")

_TILT_UID = "GOqISik4k"
_TILT_NAME = "Bin blocked(i.e. tote tilted)"
_HIST_UID = "hIVZMtGVz"
_HIST_NAME = "Bin Block History"


def _panel(uid, name, pid, title, fields, role, is_signal, notes) -> Dict[str, Any]:
    return {"dashboard_uid": uid, "dashboard_name": name, "panel_id": pid,
            "panel_title": title, "panel_type": "table", "fields": fields,
            "sql_text": "", "is_signal": is_signal, "role": role, "notes": notes}


def fetch(session, window: str) -> FetchBundle:
    urls = get_config().module_dashboard_urls("bin_mech")
    frames: Dict[str, Any] = {}
    panels: List[Dict[str, Any]] = []
    rows = 0
    notes: Dict[str, Any] = {"window": window}

    tilt_url = urls.get("BIN_BLOCKED_TILTED")
    if not tilt_url:
        raise RuntimeError("BIN_MECH__BIN_BLOCKED_TILTED is not set in .env")

    # ---- PRIMARY: current blocked-bin set (#2) ----------------------------
    pid = tilted_panel()
    res = download_panel_csv(session, tilt_url, pid, frm=window, to="now")
    frames["blocked"] = res.df
    rows += res.row_count
    panels.append(_panel(_TILT_UID, _TILT_NAME, pid, "Bin Blocked report", list(res.df.columns),
                         "primary", True,
                         "Current set of blocked bins (bin_blocked status=0), per location. "
                         "Component universe. Partition rows deduped in features."))
    # Non-signal panels (documented, not fetched).
    panels.append(_panel(_TILT_UID, _TILT_NAME, 4, "update_bin_block", [], "none", False,
                         "UPDATE statement (write/action panel) — non-signal, not fetched."))
    panels.append(_panel(_TILT_UID, _TILT_NAME, 5, "Bid Unacknowledged report", [], "none", False,
                         "Unacknowledged bids (status=0) — not a bin-block signal, not fetched."))

    # ---- SECONDARY: historical block frequency (#2) — best-effort ---------
    hist_url = urls.get("BIN_BLOCK_HISTORY")
    if hist_url:
        try:
            h = download_panel_csv(session, hist_url, history_panel(), frm=window, to="now")
            frames["history"] = h.df
            rows += h.row_count
            notes["history_rows"] = h.row_count
            panels.append(_panel(_HIST_UID, _HIST_NAME, history_panel(), "Bin block Block History",
                                 list(h.df.columns), "secondary", True,
                                 "Frozen block log (shuttle_command status=10). Per-location SOURCE "
                                 "frequency = chronic-slot enrichment."))
        except Exception as exc:  # noqa: BLE001
            log.warning("bin block history fetch failed (continuing on current + store)",
                        extra={"err": str(exc)[:120]})

    log.info("bin_mech fetch complete",
             extra={"rows": rows, "blocked_rows": res.row_count,
                    "history_rows": notes.get("history_rows")})
    return FetchBundle(frames=frames, rows_fetched=rows, panels=panels, notes=notes)
