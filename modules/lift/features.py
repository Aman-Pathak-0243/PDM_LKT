"""LIFT feature extraction — raw + derived per-lift features.

The window is anchored to ``as_of = max(created_time)`` in the fetched errors so
the model evaluates "the most recent <window> of available data" identically on
live and historical/frozen sources (see methodology.md §6 + module.yaml).

Every derived feature below is documented in modules/lift/README.md with its
formula and the panel/fields it combines.
"""

from __future__ import annotations

import datetime as _dt
import re
from statistics import median
from typing import Any, Dict, List, Optional

import pandas as pd

from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.lift.spec import error_info, is_mechanical, spec

log = get_logger("lift.features")

_LIFT_RE = re.compile(r"aisle_(\d+)_(inbound|outbound)_lift_(\d+)", re.IGNORECASE)

# Maps the Lift Error Analysis task-count columns to lift_id suffixes.
_TASK_COL_MAP = {
    "Front Inbound Lift": ("inbound", "01"),
    "Back Inbound Lift": ("inbound", "02"),
    "Front Outbound Lift": ("outbound", "01"),
    "Back Outbound Lift": ("outbound", "02"),
}


def _parse_window_days(window: str) -> float:
    """Parse a Grafana-style relative window into days (defaults to 2)."""
    m = re.match(r"now-(\d+)([smhdwMy])", (window or "").strip())
    if not m:
        return 2.0
    n, unit = int(m.group(1)), m.group(2)
    factor = {"s": 1 / 86400, "m": 1 / 1440, "h": 1 / 24, "d": 1, "w": 7, "M": 30, "y": 365}
    return max(n * factor.get(unit, 1), 1 / 24)


def _parse_lift_id(lift_id: str) -> Dict[str, Any]:
    m = _LIFT_RE.match(str(lift_id))
    if not m:
        return {"aisle": None, "face": None, "unit_no": None}
    return {"aisle": f"aisle_{m.group(1)}", "face": m.group(2).lower(), "unit_no": m.group(3)}


def _robust_z(value: float, values: List[float]) -> float:
    """Robust z-score vs peers using median + MAD; falls back to a standard
    deviation z when the MAD is zero (≥half the peers identical), and to 0 when
    there is no spread at all."""
    if len(values) < 2:
        return 0.0
    med = median(values)
    mad = median([abs(v - med) for v in values])
    scale = 1.4826 * mad
    if scale >= 1e-9:
        return (value - med) / scale
    mean = sum(values) / len(values)
    std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    if std < 1e-9:
        return 0.0
    return (value - mean) / std


def _task_counts(df: Optional[pd.DataFrame]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if df is None or df.empty or "Aisle" not in df.columns:
        return out
    for _, row in df.iterrows():
        aisle = str(row.get("Aisle", "")).strip()
        if not aisle.startswith("aisle_"):
            continue
        for col, (face, unit) in _TASK_COL_MAP.items():
            if col in df.columns and pd.notna(row.get(col)):
                out[f"{aisle}_{face}_lift_{unit}"] = int(row[col])
    return out


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    s = spec()
    errors = bundle.frames.get("errors", pd.DataFrame())
    bad_tracker = bundle.frames.get("bad_tracker", pd.DataFrame())
    task_counts = _task_counts(bundle.frames.get("task_counts"))
    window = bundle.notes.get("window", "now-2d")
    window_days = _parse_window_days(window)

    if errors is None or errors.empty or "lift_id" not in errors.columns:
        log.warning("no lift error rows fetched")
        return {}

    df = errors.copy()
    df["ct"] = pd.to_datetime(df["created_time"], errors="coerce")
    df = df.dropna(subset=["ct", "lift_id"])
    if df.empty:
        return {}

    anchor = bool(s.get("anchor_to_data_asof", True))
    as_of = df["ct"].max() if anchor else pd.Timestamp(_dt.datetime.now())
    window_start = as_of - pd.Timedelta(days=window_days)
    win = df[df["ct"] >= window_start]

    # Universe of lifts = every lift seen in the full fetched data (so all units
    # get a health row even with zero errors in the current window).
    universe = sorted(set(df["lift_id"].astype(str)))
    total_win_errors = int(len(win))

    # ---- Bad tracker (current status + recurrence) ------------------------
    bt_events: Dict[str, int] = {}
    bt_error_now: Dict[str, bool] = {}
    if bad_tracker is not None and not bad_tracker.empty and "lift_id" in bad_tracker.columns:
        bt = bad_tracker.dropna(subset=["lift_id"])
        for lid, grp in bt.groupby(bt["lift_id"].astype(str)):
            bt_events[lid] = int(len(grp))
            desc_col = "lift Status Description"
            if desc_col in grp.columns:
                bt_error_now[lid] = grp[desc_col].astype(str).str.upper().eq("ERROR").any()

    feats: Dict[str, Dict[str, Any]] = {}
    for lid in universe:
        g = win[win["lift_id"].astype(str) == lid]
        n = int(len(g))
        parsed = _parse_lift_id(lid)

        # error-code mix + severity
        code_counts: Dict[str, int] = {}
        sev_sum = 0.0
        mech = 0
        cat_counts: Dict[str, int] = {}
        for code in g.get("error_code", pd.Series(dtype=object)):
            info = error_info(code)
            code_counts[str(code)] = code_counts.get(str(code), 0) + 1
            sev_sum += float(info["severity"])
            cat = info["category"]
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            if is_mechanical(cat):
                mech += 1

        # inter-fault timing
        times = sorted(g["ct"].tolist())
        gaps_h = [
            (times[i] - times[i - 1]).total_seconds() / 3600.0 for i in range(1, len(times))
        ]
        last_age_h = (as_of - times[-1]).total_seconds() / 3600.0 if times else None
        top_code = max(code_counts, key=code_counts.get) if code_counts else None

        feats[lid] = {
            "component_id": lid,
            **parsed,
            "as_of": as_of.isoformat(),
            "window": window,
            "window_days": round(window_days, 3),
            "error_count": n,
            "error_rate_per_day": round(n / window_days, 4),
            "share_of_total": round(n / total_win_errors, 4) if total_win_errors else 0.0,
            "distinct_codes": len(code_counts),
            "severity_mean": round(sev_sum / n, 4) if n else 0.0,
            "mechanical_count": mech,
            "mechanical_share": round(mech / n, 4) if n else 0.0,
            "recurrence_max": max(code_counts.values()) if code_counts else 0,
            "code_counts": code_counts,
            "category_counts": cat_counts,
            "top_code": top_code,
            "top_code_desc": error_info(top_code)["desc"] if top_code else None,
            "top_code_n": code_counts.get(top_code, 0) if top_code else 0,
            "median_gap_hours": round(median(gaps_h), 3) if gaps_h else None,
            "min_gap_hours": round(min(gaps_h), 3) if gaps_h else None,
            "last_error_age_hours": round(last_age_h, 2) if last_age_h is not None else None,
            "load_tasks": task_counts.get(lid),
            "bad_tracker_events": bt_events.get(lid, 0),
            "current_error_status": bool(bt_error_now.get(lid, False)),
        }

    # ---- peer-relative rate (robust z across all lifts) -------------------
    rates = [f["error_rate_per_day"] for f in feats.values()]
    peer_med = round(median(rates), 4) if rates else 0.0
    for f in feats.values():
        f["peer_median_rate"] = peer_med
        f["rate_peer_z"] = round(_robust_z(f["error_rate_per_day"], rates), 3)

    log.info(
        "lift features computed",
        extra={"lifts": len(feats), "as_of": as_of.isoformat(), "window_days": window_days,
               "win_errors": total_win_errors},
    )
    return feats
