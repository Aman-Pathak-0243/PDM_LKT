"""TRACKER feature extraction — per grid-location (position-sensor) signals.

The component is the grid `location` (e.g. ``aisle_03_bt_10``) — the fixed position
sensor / tracker reader. Bad-tracker events (mislocated totes) cluster on the same
location; a healthy sensor produces isolated one-offs, a degrading one accumulates a
cluster of stuck totes and recurs across runs. Each feature is documented in
modules/tracker/README.md. Cross-run recurrence/persistence is added in health.py
(which has the history); features.py is the within-snapshot view.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any, Dict, List, Optional

import pandas as pd

from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.tracker.spec import thresholds

log = get_logger("tracker.features")

_AISLE_RE = re.compile(r"aisle[_-]?(\d+)", re.I)


def _robust_z(value: float, values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    med = median(values)
    mad = median([abs(v - med) for v in values])
    scale = 1.4826 * mad
    if scale >= 1e-9:
        return (value - med) / scale
    mean = sum(values) / len(values)
    std = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    return (value - mean) / std if std >= 1e-9 else 0.0


def _aisle_of(loc: str) -> Optional[str]:
    m = _AISLE_RE.search(str(loc))
    return f"aisle_{int(m.group(1)):02d}" if m else None


def _col(df: pd.DataFrame, *names: str) -> Optional[str]:
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _parse_window_days(window: Optional[str], default: float = 7.0) -> float:
    if not window:
        return default
    m = re.search(r"now-(\d+)([dhwm])", str(window))
    if not m:
        return default
    n, unit = int(m.group(1)), m.group(2)
    return {"h": n / 24.0, "d": float(n), "w": n * 7.0, "m": n * 30.0}.get(unit, default)


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    t = thresholds()
    recent_days = float(t.get("recent_days", 7))
    win_days = _parse_window_days(bundle.notes.get("window"), recent_days)
    # "recent / active" = newer than the smaller of the window and the recent_days knob,
    # so a short window tightens what counts as currently-active.
    active_days = min(recent_days, win_days) if win_days > 0 else recent_days

    bt = bundle.frames.get("bad_tracker", pd.DataFrame())
    if bt is None or bt.empty:
        log.warning("no bad-tracker data")
        return {}

    loc_col = _col(bt, "location")
    if not loc_col:
        log.warning("bad-tracker frame has no location column", extra={"cols": list(bt.columns)})
        return {}
    trk_col = _col(bt, "tracker")
    cont_col = _col(bt, "container")
    ct_col = _col(bt, "created_time")
    sh_col = _col(bt, "shuttle_id")
    lift_col = _col(bt, "lift_id")
    task_col = _col(bt, "task_type")
    sh_desc_col = _col(bt, "shuttle Status Description")
    lift_desc_col = _col(bt, "lift Status Description")

    df = bt.copy()
    df = df[df[loc_col].notna() & (df[loc_col].astype(str).str.strip() != "")]
    if df.empty:
        return {}

    ages = None
    as_of = None
    if ct_col:
        ts = pd.to_datetime(df[ct_col], errors="coerce")
        as_of = ts.max()
        if pd.notna(as_of):
            ages = (as_of - ts).dt.total_seconds() / 86400.0  # days old
    as_of_str = str(as_of) if as_of is not None and pd.notna(as_of) else ""

    feats: Dict[str, Dict[str, Any]] = {}
    for loc, g in df.groupby(df[loc_col].astype(str)):
        idx = g.index
        g_ages = ages.loc[idx].dropna() if ages is not None else pd.Series(dtype=float)
        recent_n = int((g_ages <= active_days).sum()) if len(g_ages) else 0
        shuttles = g[sh_col].dropna().astype(str) if sh_col else pd.Series(dtype=str)
        sh_counts = shuttles.value_counts()
        lift_ids = g[lift_col].dropna().astype(str) if lift_col else pd.Series(dtype=str)
        pick_err = 0
        if sh_desc_col:
            pick_err = int(g[sh_desc_col].astype(str).str.contains("PICK_ERROR", case=False, na=False).sum())
        lift_err = 0
        if lift_desc_col:
            lift_err = int(g[lift_desc_col].astype(str).str.upper().str.contains("ERROR", na=False).sum())
        tasks = g[task_col].dropna().astype(str).value_counts() if task_col else pd.Series(dtype=int)
        trackers = g[trk_col].dropna().astype(str).tolist() if trk_col else []
        containers = g[cont_col].dropna().astype(str).nunique() if cont_col else len(g)

        feats[loc] = {
            "component_id": loc,
            "location": loc,
            "aisle": _aisle_of(loc),
            "as_of": as_of_str,
            "window": bundle.notes.get("window"),
            "bad_count": int(len(g)),
            "recent_bad_count": recent_n,
            "recent_share": round(recent_n / len(g), 3) if len(g) else 0.0,
            "newest_age_days": round(float(g_ages.min()), 2) if len(g_ages) else None,
            "oldest_age_days": round(float(g_ages.max()), 2) if len(g_ages) else None,
            "median_age_days": round(float(g_ages.median()), 2) if len(g_ages) else None,
            "distinct_shuttles": int(shuttles.nunique()),
            "dominant_shuttle": (sh_counts.index[0] if len(sh_counts) else None),
            "dominant_shuttle_share": round(float(sh_counts.iloc[0] / len(g)), 3) if len(sh_counts) else 0.0,
            "distinct_containers": int(containers),
            "lift_involved_count": int(lift_ids.nunique()),
            "lift_error_count": lift_err,
            "pick_error_count": pick_err,
            "dominant_task": (tasks.index[0] if len(tasks) else None),
            "stuck_trackers": trackers[:10],
            "active_days": round(active_days, 2),
        }

    counts = [f["bad_count"] for f in feats.values()]
    peer_med = round(median(counts), 2) if counts else 0.0
    for f in feats.values():
        f["peer_median_bad"] = peer_med
        f["bad_count_peer_z"] = round(_robust_z(f["bad_count"], counts), 3)

    log.info("tracker features computed",
             extra={"locations": len(feats), "as_of": as_of_str,
                    "worst_cluster": max(counts) if counts else None,
                    "total_bad": int(df.shape[0])})
    return feats
