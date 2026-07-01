"""BIN / TOTE-MECHANICAL feature extraction — per bin-location (slot) signals.

The component is the grid bin LOCATION (slot address ``NNN-NN-N-NNN-N-NN``). A bin-block
(tote tilt) is a tote that won't seat / is stuck at a slot. A healthy slot blocks rarely
and briefly; a degrading slot/rail blocks totes repeatedly, keeps a block unresolved for
long, and recurs at the same location. features.py is the within-snapshot view; the
historical block frequency (frozen log) and cross-run recurrence (store) enrich it in
health.py. Every feature is documented in modules/bin_mech/README.md.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any, Dict, List, Optional

import pandas as pd

from core.logging_setup import get_logger
from core.registry import FetchBundle

log = get_logger("bin_mech.features")

# Bin slot address: NNN-NN-N-NNN-N-NN  (aisle-level-rack-location-?-deep)
_LOC_RE = re.compile(r"^(\d{3})-(\d{2})-(\d)-(\d{3})-(\d)-(\d{2})$")


def _col(df: pd.DataFrame, *names: str) -> Optional[str]:
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _parse_loc(loc: str) -> Dict[str, Any]:
    m = _LOC_RE.match(str(loc).strip())
    if not m:
        return {"aisle": None, "level": None, "deep": None, "is_bin": False}
    return {"aisle": f"aisle_{int(m.group(1)):02d}", "level": int(m.group(2)),
            "deep": m.group(6), "is_bin": True}


def _historical_freq(history: pd.DataFrame) -> Dict[str, int]:
    """Per-location historical block frequency from Bin Block History (SOURCE, bin-format)."""
    if history is None or history.empty:
        return {}
    src = _col(history, "source")
    if not src:
        return {}
    s = history[src].dropna().astype(str)
    s = s[s.str.match(_LOC_RE)]
    return {loc: int(n) for loc, n in s.value_counts().items()}


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    blocked = bundle.frames.get("blocked", pd.DataFrame())
    if blocked is None or blocked.empty:
        log.warning("no bin-blocked rows fetched")
        return {}

    loc_col = _col(blocked, "location")
    if not loc_col:
        log.warning("bin-blocked frame has no location column", extra={"cols": list(blocked.columns)})
        return {}
    trk_col = _col(blocked, "tracker")
    cont_col = _col(blocked, "container")
    ai_col = _col(blocked, "aisle")
    lv_col = _col(blocked, "level")
    bt_col = _col(blocked, "blockedTime", "blocked_time", "blockedtime")

    df = blocked.copy()
    df = df[df[loc_col].notna() & (df[loc_col].astype(str).str.strip() != "")]
    if df.empty:
        return {}

    # Dedup the partition LEFT-JOIN inflation: one row per blocked tote event.
    dedup_keys = [c for c in (loc_col, trk_col, bt_col) if c]
    df = df.drop_duplicates(subset=dedup_keys)

    # block-age anchored to the newest block in the set (tz-robust: blockedTime is plant-local).
    ages = None
    as_of = None
    if bt_col:
        ts = pd.to_datetime(df[bt_col], errors="coerce")
        as_of = ts.max()
        if pd.notna(as_of):
            ages = (as_of - ts).dt.total_seconds() / 3600.0  # hours old
    as_of_str = str(as_of) if as_of is not None and pd.notna(as_of) else ""

    hist_freq = _historical_freq(bundle.frames.get("history", pd.DataFrame()))

    feats: Dict[str, Dict[str, Any]] = {}
    for loc, g in df.groupby(df[loc_col].astype(str)):
        idx = g.index
        g_ages = ages.loc[idx].dropna() if ages is not None else pd.Series(dtype=float)
        parsed = _parse_loc(loc)
        aisle = parsed["aisle"]
        if not aisle and ai_col and pd.notna(g[ai_col].iloc[0]):
            aisle = f"aisle_{int(g[ai_col].iloc[0]):02d}"
        level = parsed["level"]
        if level is None and lv_col and pd.notna(g[lv_col].iloc[0]):
            try:
                level = int(g[lv_col].iloc[0])
            except (TypeError, ValueError):
                level = None
        trackers = g[trk_col].dropna().astype(str).nunique() if trk_col else len(g)
        containers = g[cont_col].dropna().astype(str).nunique() if cont_col else len(g)

        feats[loc] = {
            "component_id": loc,
            "location": loc,
            "aisle": aisle,
            "level": level,
            "deep": parsed["deep"],
            "as_of": as_of_str,
            "window": bundle.notes.get("window"),
            "blocked_now": True,
            "current_block_count": int(trackers),
            "distinct_containers": int(containers),
            "block_age_hours": round(float(g_ages.max()), 2) if len(g_ages) else 0.0,
            "newest_block_age_hours": round(float(g_ages.min()), 2) if len(g_ages) else 0.0,
            "historical_block_count": int(hist_freq.get(loc, 0)),
        }

    # ---- roster context (within-snapshot) --------------------------------
    aisle_counts: Dict[str, int] = {}
    for f in feats.values():
        if f["aisle"]:
            aisle_counts[f["aisle"]] = aisle_counts.get(f["aisle"], 0) + 1
    total = len(feats)
    # An aisle is a block-CONCENTRATION outlier only if its count is anomalous vs peer
    # aisles (blocks are normally spread across aisles, so an absolute floor over-fires).
    counts = list(aisle_counts.values())
    outlier_thresh = float("inf")
    if len(counts) >= 2:
        med = median(counts)
        mad = median([abs(c - med) for c in counts])
        outlier_thresh = max(med + 2 * 1.4826 * mad, 1.5 * med, 5)
    for f in feats.values():
        f["total_blocked_locations"] = total
        ac = aisle_counts.get(f["aisle"], 0) if f["aisle"] else 0
        f["aisle_block_count"] = ac
        f["aisle_is_outlier"] = bool(ac >= outlier_thresh and ac >= 5)

    log.info("bin_mech features computed",
             extra={"blocked_locations": total, "as_of": as_of_str,
                    "with_history": sum(1 for f in feats.values() if f["historical_block_count"] > 0),
                    "aisle_outliers": sum(1 for f in feats.values() if f["aisle_is_outlier"]),
                    "max_age_h": max((f["block_age_hours"] for f in feats.values()), default=0)})
    return feats
