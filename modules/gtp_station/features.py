"""GTP STATION + SCANNER feature extraction — two entity types in one feature map.

SCANNER (component_type=gtp_scanner): per scan device from GTP Scanner logs #8
  (ReadCount/NoReadCount) + #4 (hits). misread_rate = NoRead/(Read+NoRead). A healthy
  scanner reads nearly everything; a dirty/failing/mis-aimed one's no-read rate climbs.

STATION (component_type=gtp_station): per pick station from GTP Stations #2 (roster +
  active_status) + Discrepancy Report Events #2 (per-station verification discrepancies).
  discrepancy_per_day normalises the count to the window; the store adds recurrence/trend
  and offline-persistence in health.py.

Within-snapshot peer deviation (misread_peer_z, discrepancy_peer_z) is computed here (a
single-run comparison, like Conveyor). Cross-run signals (recurrence, offline persistence,
trend) live in health.py, which holds the store history. Every feature is documented in
modules/gtp_station/README.md.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any, Dict, List, Optional

import pandas as pd

from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.gtp_station.spec import thresholds

log = get_logger("gtp_station.features")

# GS<NN>-SL<NN> = a pick-station slot scanner (belongs to station GS<NN>).
_STATION_SCANNER_RE = re.compile(r"^(GS\d+)[-_]SL\d+", re.I)
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


def _scanner_subtype(name: str) -> str:
    s = str(name).lower()
    if _STATION_SCANNER_RE.match(str(name)):
        return "station_scanner"
    if "decant" in s:
        return "decant"
    if "compaction" in s:
        return "compaction"
    if "inbound" in s:
        return "inbound_scanner"
    if "diverter" in s:
        return "diverter"
    if "zone" in s or "lane" in s:
        return "zone_scanner"
    if "scanner" in s:
        return "gtp_scanner"
    return "other"


def _parent_station(name: str) -> Optional[str]:
    m = _STATION_SCANNER_RE.match(str(name))
    return m.group(1).upper() if m else None


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

    # #4 hits, joined by scanner (best-effort volume proxy). Sum over partition rows so a
    # partitioned scanner's hits match how total_scans is summed in the misread frame.
    hits_by: Dict[str, int] = {}
    hf = bundle.frames.get("hits", pd.DataFrame())
    if hf is not None and not hf.empty:
        hsc = _col(hf, "scanner")
        hh = _col(hf, "hits")
        if hsc and hh:
            g2 = hf.copy()
            g2["_h"] = _num(g2[hh])
            for k, v in g2.groupby(g2[hsc].astype(str).str.strip())["_h"].sum().items():
                if pd.notna(v):
                    hits_by[str(k)] = int(v)

    feats: Dict[str, Dict[str, Any]] = {}
    for name, r in grp.iterrows():
        total = float(r["_total"])
        noread_n = float(r["_noread"])
        misread = (noread_n / total) if total > 0 else 0.0
        feats[str(name)] = {
            "component_id": str(name),
            "component_type": "gtp_scanner",
            "entity": "scanner",
            "scanner": str(name),
            "subtype": _scanner_subtype(name),
            "parent_station": _parent_station(name),
            "window": window,
            "read_count": int(r["_read"]),
            "no_read_count": int(noread_n),
            "total_scans": int(total),
            "misread_rate": round(misread, 5),
            "misread_pct": round(misread * 100.0, 3),
            "efficiency_percentage": round(float(eff_by[name]), 2) if eff_by is not None and pd.notna(eff_by.get(name)) else None,
            "hits": hits_by.get(str(name)),
        }

    # within-snapshot peer deviation of misread% over scanners with enough volume
    # (a low-volume scanner's rate is noisy, so it must not distort the baseline).
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
    disc = bundle.frames.get("discrepancy", pd.DataFrame())
    window_days = _window_hours(window) / 24.0

    # per-station discrepancy aggregation
    per_count: Dict[str, int] = {}
    per_short: Dict[str, int] = {}
    type_mix: Dict[str, Dict[str, int]] = {}
    if disc is not None and not disc.empty:
        st_col = _col(disc, "station")
        dt_col = _col(disc, "discrepancy_type")
        if st_col:
            d = disc.copy()
            d = d[d[st_col].notna() & (d[st_col].astype(str).str.strip() != "")]
            for st, g in d.groupby(d[st_col].astype(str).str.strip()):
                per_count[st] = int(len(g))
                if dt_col:
                    vc = g[dt_col].astype(str).str.upper().value_counts()
                    type_mix[st] = {k: int(v) for k, v in vc.items()}
                    per_short[st] = int(vc.get("SHORT", 0))

    # station universe = roster ids UNION any discrepancy stations not in the roster
    roster_rows: Dict[str, Dict[str, Any]] = {}
    if roster is not None and not roster.empty:
        id_col = _col(roster, "id")
        as_col = _col(roster, "active_status")
        op_col = _col(roster, "operation_type")
        ty_col = _col(roster, "Type", "type")
        up_col = _col(roster, "updated_on", "updated_timestamp")
        if id_col:
            rr = roster.copy()
            rr = rr[rr[id_col].notna() & (rr[id_col].astype(str).str.strip() != "")]
            rr = rr.drop_duplicates(subset=[id_col])
            for _, row in rr.iterrows():
                sid = str(row[id_col]).strip()
                status = str(row[as_col]).strip() if as_col and pd.notna(row.get(as_col)) else "Unknown"
                roster_rows[sid] = {
                    "active_status": status,
                    "is_active": status.lower() == "active",
                    "operation_type": str(row[op_col]).strip() if op_col and pd.notna(row.get(op_col)) else None,
                    "station_type": str(row[ty_col]).strip() if ty_col and pd.notna(row.get(ty_col)) else None,
                    "updated_on": str(row[up_col]) if up_col and pd.notna(row.get(up_col)) else None,
                }

    universe = set(roster_rows) | set(per_count)
    if not universe:
        return {}

    feats: Dict[str, Dict[str, Any]] = {}
    for sid in universe:
        info = roster_rows.get(sid, {"active_status": "Unknown", "is_active": None,
                                     "operation_type": None, "station_type": None, "updated_on": None})
        count = per_count.get(sid, 0)
        feats[sid] = {
            "component_id": sid,
            "component_type": "gtp_station",
            "entity": "station",
            "station": sid,
            "window": window,
            "in_roster": sid in roster_rows,
            "active_status": info["active_status"],
            "is_active": info["is_active"],
            "operation_type": info["operation_type"],
            "station_type": info["station_type"],
            "updated_on": info["updated_on"],
            "discrepancy_count": count,
            "short_count": per_short.get(sid, 0),
            "discrepancy_per_day": round(count / window_days, 3) if window_days > 0 else 0.0,
            "discrepancy_type_mix": type_mix.get(sid, {}),
        }

    # within-snapshot peer deviation over stations that actually verified (count > 0),
    # so structurally-idle/Inactive stations (0 discrepancies) do not distort the baseline.
    pool = [f["discrepancy_per_day"] for f in feats.values() if f["discrepancy_count"] > 0]
    for f in feats.values():
        f["discrepancy_peer_z"] = round(_robust_z(f["discrepancy_per_day"], pool), 3) if len(pool) >= 2 else 0.0
        f["peer_station_count"] = len(pool)
        f["discrepancy_disclosed"] = bool(disc is not None and not disc.empty)
    return feats


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    window = bundle.notes.get("window")
    scanners = _scanner_features(bundle, window)
    stations = _station_features(bundle, window)

    # scanner ids (GS030-SL02, aisle_..) and station ids (GS030) are disjoint namespaces,
    # but guard against any collision by keeping the entity type explicit on every row.
    feats: Dict[str, Dict[str, Any]] = {}
    feats.update(scanners)
    feats.update(stations)

    log.info("gtp_station features computed",
             extra={"scanners": len(scanners), "stations": len(stations),
                    "worst_misread": max((f["misread_pct"] for f in scanners.values()), default=0),
                    "max_disc": max((f["discrepancy_count"] for f in stations.values()), default=0),
                    "inactive_stations": sum(1 for f in stations.values() if f.get("is_active") is False)})
    return feats
