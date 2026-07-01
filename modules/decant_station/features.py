"""DECANTING STATION + SCANNER feature extraction — two entity types in one feature map.

SCANNER (component_type=decant_scanner): per decant/compaction scan device from GTP Scanner logs
  #8 (ReadCount/NoReadCount), filtered to the devices this module owns (name contains "decant" or
  "compaction"). misread_rate = NoRead/(Read+NoRead). A healthy scanner reads nearly everything; a
  dirty/failing one's no-read rate climbs. Peer deviation (misread_peer_z) is computed over the
  decant-module scanner fleet (a single-run comparison, like gtp_station / Conveyor).

STATION (component_type=decant_station): per decant operator station from Decanting station report
  #2 (roster + active_status) + StationWise Decanted Cartons Count #2 (per-station throughput). There
  is NO live per-station fault/discrepancy feed, so the station carries only status + throughput
  features; idle_while_active (Active + 0 decanted cartons while the whole line is busy) is the one
  within-run anomaly, and it is only ESCALATED by cross-run persistence in health.py.

Cross-run signals (scanner misread recurrence, station offline-persistence + idle-recurrence, trend)
live in health.py, which holds the store history. Every feature is documented in the module README.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any, Dict, List, Optional

import pandas as pd

from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.decant_station.spec import include_subtypes, thresholds

log = get_logger("decant_station.features")

_AISLE_RE = re.compile(r"aisle[_-]?(\d+)", re.I)
_DECANT_RE = re.compile(r"decant", re.I)
_COMPACT_RE = re.compile(r"compaction", re.I)
_WINDOW_RE = re.compile(r"now-(\d+)\s*([smhdw])", re.I)
_UNIT_HOURS = {"s": 1 / 3600.0, "m": 1 / 60.0, "h": 1.0, "d": 24.0, "w": 168.0}


def _col(df: pd.DataFrame, *names: str) -> Optional[str]:
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def _window_hours(window: Optional[str], default: float = 48.0) -> float:
    if not window:
        return default
    m = _WINDOW_RE.search(str(window))
    if not m:
        return default
    return max(float(m.group(1)) * _UNIT_HOURS.get(m.group(2).lower(), 1.0), 1e-6)


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


def _scanner_subtype(name: str) -> Optional[str]:
    """decant / compaction for owned devices; None for everything else (belongs to gtp_station)."""
    s = str(name).lower()
    if _DECANT_RE.search(s):
        return "decant"
    if _COMPACT_RE.search(s):
        return "compaction"
    return None


def _aisle(name: str) -> Optional[str]:
    m = _AISLE_RE.search(str(name))
    return f"aisle_{int(m.group(1)):02d}" if m else None


# --------------------------------------------------------------------------- #
# Scanner features
# --------------------------------------------------------------------------- #
def _scanner_features(bundle: FetchBundle, window: str) -> Dict[str, Dict[str, Any]]:
    df = bundle.frames.get("misread", pd.DataFrame())
    if df is None or df.empty:
        return {}
    sc = _col(df, "scanner")
    rc = _col(df, "ReadCount", "read_count")
    nc = _col(df, "NoReadCount", "no_read_count", "noreadcount")
    ec = _col(df, "efficiency_percentage", "efficiency")
    if not sc or (not rc and not nc):
        log.warning("scanner misread frame missing columns", extra={"cols": list(df.columns)})
        return {}

    owned = set(include_subtypes())
    df = df.copy()
    df = df[df[sc].notna() & (df[sc].astype(str).str.strip() != "")]
    read = _num(df[rc]).fillna(0) if rc else pd.Series(0, index=df.index)
    noread = _num(df[nc]).fillna(0) if nc else pd.Series(0, index=df.index)
    df["_read"] = read
    df["_noread"] = noread
    df["_total"] = read + noread
    # A scanner can appear more than once (partitioned) — sum its counts.
    grp = df.groupby(df[sc].astype(str).str.strip()).agg(
        _read=("_read", "sum"), _noread=("_noread", "sum"), _total=("_total", "sum"))
    eff_by = None
    if ec:
        df["_eff"] = _num(df[ec])
        eff_by = df.groupby(df[sc].astype(str).str.strip())["_eff"].mean()

    feats: Dict[str, Dict[str, Any]] = {}
    for name, r in grp.iterrows():
        subtype = _scanner_subtype(name)
        if subtype not in owned:            # keep only the decant/compaction devices this module owns
            continue
        total = float(r["_total"])
        noread_n = float(r["_noread"])
        misread = (noread_n / total) if total > 0 else 0.0
        feats[str(name)] = {
            "component_id": str(name),
            "component_type": "decant_scanner",
            "entity": "scanner",
            "scanner": str(name),
            "subtype": subtype,
            "aisle": _aisle(name),
            "window": window,
            "read_count": int(r["_read"]),
            "no_read_count": int(noread_n),
            "total_scans": int(total),
            "misread_rate": round(misread, 5),
            "misread_pct": round(misread * 100.0, 3),
            "efficiency_percentage": round(float(eff_by[name]), 2) if eff_by is not None and pd.notna(eff_by.get(name)) else None,
        }

    # within-snapshot peer deviation of misread% over the decant scanner fleet with enough volume
    # (a low-volume device's rate is noisy, so it must not distort the baseline).
    min_vol_peer = float(thresholds().get("scanner", {}).get("min_volume_peer", 200))
    pool = [f["misread_pct"] for f in feats.values() if f["total_scans"] >= min_vol_peer]
    for f in feats.values():
        f["misread_peer_z"] = round(_robust_z(f["misread_pct"], pool), 3) if len(pool) >= 2 else 0.0
        f["peer_scanner_count"] = len(pool)
    return feats


# --------------------------------------------------------------------------- #
# Station features
# --------------------------------------------------------------------------- #
def _station_features(bundle: FetchBundle, window: str) -> Dict[str, Dict[str, Any]]:
    roster = bundle.frames.get("stations", pd.DataFrame())
    cartons = bundle.frames.get("cartons", pd.DataFrame())
    window_days = _window_hours(window) / 24.0
    st_cfg = thresholds().get("station", {})
    idle_floor = float(st_cfg.get("idle_floor_cartons", 0))
    line_busy_min = float(st_cfg.get("line_busy_min_cartons", 50))

    # per-station throughput over the window
    per_cartons: Dict[str, int] = {}
    if cartons is not None and not cartons.empty:
        sid_col = _col(cartons, "station_id", "station id", "id")
        cc_col = _col(cartons, "carton_count", "count")
        if sid_col and cc_col:
            c = cartons.copy()
            c["_cc"] = _num(c[cc_col]).fillna(0)
            for sid, v in c.groupby(c[sid_col].astype(str).str.strip())["_cc"].sum().items():
                per_cartons[str(sid)] = int(v)
    total_line_cartons = sum(per_cartons.values())
    line_busy = total_line_cartons >= line_busy_min
    cartons_disclosed = bool(cartons is not None and not cartons.empty)

    # station universe = roster ids UNION any throughput stations not in the roster
    roster_rows: Dict[str, Dict[str, Any]] = {}
    if roster is not None and not roster.empty:
        id_col = _col(roster, "Station ID", "station_id", "id")
        as_col = _col(roster, "active_status", "active status")
        us_col = _col(roster, "User", "user_id", "user")
        if id_col:
            rr = roster.copy()
            rr = rr[rr[id_col].notna() & (rr[id_col].astype(str).str.strip() != "")]
            rr = rr.drop_duplicates(subset=[id_col])
            for _, row in rr.iterrows():
                sid = str(row[id_col]).strip()
                status = str(row[as_col]).strip() if as_col and pd.notna(row.get(as_col)) else "Unknown"
                _sl = status.lower()
                # Tri-state (matches the missing-row default below): True only for
                # Active, False only for Inactive, None for Unknown/blank — so an
                # unreported status is NOT treated as offline (no false offline-persistence).
                is_active = True if _sl == "active" else (False if _sl == "inactive" else None)
                roster_rows[sid] = {
                    "active_status": status,
                    "is_active": is_active,
                    "user": str(row[us_col]).strip() if us_col and pd.notna(row.get(us_col)) else None,
                }

    universe = set(roster_rows) | set(per_cartons)
    if not universe:
        return {}

    feats: Dict[str, Dict[str, Any]] = {}
    for sid in universe:
        info = roster_rows.get(sid, {"active_status": "Unknown", "is_active": None, "user": None})
        count = per_cartons.get(sid, 0)
        is_active = info["is_active"]
        # idle-while-active: Active station decanting <= idle_floor cartons WHILE the line is busy.
        # (A single idle window is normal — unstaffed; only cross-run persistence escalates it.)
        idle_while_active = bool(is_active is True and count <= idle_floor and line_busy)
        feats[sid] = {
            "component_id": sid,
            "component_type": "decant_station",
            "entity": "station",
            "station": sid,
            "window": window,
            "in_roster": sid in roster_rows,
            "active_status": info["active_status"],
            "is_active": is_active,
            "user": info["user"],
            "carton_count": count,
            "throughput_per_day": round(count / window_days, 2) if window_days > 0 else 0.0,
            "idle_while_active": idle_while_active,
            "line_busy": line_busy,
            "line_total_cartons": total_line_cartons,
            "cartons_disclosed": cartons_disclosed,
        }

    # within-snapshot throughput peer deviation over stations that decanted (count > 0) — CONTEXT
    # for RCA only (low throughput is not penalized; it may just be low load), not a penalty input.
    pool = [f["carton_count"] for f in feats.values() if f["carton_count"] > 0]
    for f in feats.values():
        f["throughput_peer_z"] = round(_robust_z(f["carton_count"], pool), 3) if len(pool) >= 2 else 0.0
        f["busy_station_count"] = len(pool)
    return feats


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    window = bundle.notes.get("window")
    scanners = _scanner_features(bundle, window)
    stations = _station_features(bundle, window)

    # scanner ids (aisle_01_decant_diverter, Compaction_scanner) and station ids (DS001) are
    # disjoint namespaces, but keep the entity type explicit on every row to be safe.
    feats: Dict[str, Dict[str, Any]] = {}
    feats.update(scanners)
    feats.update(stations)

    log.info("decant_station features computed",
             extra={"scanners": len(scanners), "stations": len(stations),
                    "worst_misread": max((f["misread_pct"] for f in scanners.values()), default=0),
                    "idle_active": sum(1 for f in stations.values() if f.get("idle_while_active")),
                    "inactive_stations": sum(1 for f in stations.values() if f.get("is_active") is False)})
    return feats
