"""NETWORK / COMMS feature extraction — one component type: the per-shuttle comms link.

Per shuttle from Quadron Network status #4 (windowed uptime%) + #2 (today uptime%, recency):
  downtime% = 100 - uptime%  (the core comms signal; higher = flakier link)
  today_downtime% / today_delta = how much worse the link is TODAY vs its window average (accelerating)
  downtime_peer_z = robust z of downtime% vs the shuttle fleet (within-snapshot, like Conveyor/Gate)
  aisle + aisle_mean_downtime = for the aisle-clustering cross-feature (an aisle AP/controller common cause)

Cross-run signals (recurrence, trend) live in health.py, which holds the store history. Every feature
is documented in modules/network/README.md.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any, Dict, List, Optional

import pandas as pd

from core.logging_setup import get_logger
from core.registry import FetchBundle

log = get_logger("network.features")

_AISLE_RE = re.compile(r"shuttle[_-]?(\d+)", re.I)


def _col(df: pd.DataFrame, *names: str) -> Optional[str]:
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _num(s):
    return pd.to_numeric(s, errors="coerce")


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


def _aisle(sid: str) -> Optional[str]:
    m = _AISLE_RE.search(str(sid))
    return f"aisle_{int(m.group(1)):02d}" if m else None


def _uptime_by_shuttle(df: pd.DataFrame) -> Dict[str, float]:
    """Map shuttle_id -> uptime% from a Quadron Network status panel frame."""
    out: Dict[str, float] = {}
    if df is None or df.empty:
        return out
    sid = _col(df, "shuttle_id", "shuttle")
    val = _col(df, "Value", "uptime", "value")
    if not sid or not val:
        return out
    d = df.copy()
    d["_u"] = _num(d[val])
    d = d[d[sid].notna() & (d[sid].astype(str).str.strip() != "")]
    # a shuttle should appear once; if partitioned, take the mean uptime.
    for k, v in d.groupby(d[sid].astype(str).str.strip())["_u"].mean().items():
        if pd.notna(v):
            out[str(k)] = float(v)
    return out


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    window = bundle.notes.get("window")
    win_up = _uptime_by_shuttle(bundle.frames.get("windowed", pd.DataFrame()))
    today_up = _uptime_by_shuttle(bundle.frames.get("today", pd.DataFrame()))
    today_disclosed = bool(today_up)

    if not win_up:
        log.warning("no windowed uptime rows — no network components")
        return {}

    feats: Dict[str, Dict[str, Any]] = {}
    for sid, uptime in win_up.items():
        downtime = round(max(0.0, 100.0 - uptime), 3)
        today_u = today_up.get(sid)
        today_dt = round(max(0.0, 100.0 - today_u), 3) if today_u is not None else None
        feats[sid] = {
            "component_id": sid,
            "component_type": "network_link",
            "entity": "network_link",
            "shuttle_id": sid,
            "aisle": _aisle(sid),
            "window": window,
            "uptime_pct": round(uptime, 3),
            "downtime_pct": downtime,
            "today_uptime_pct": round(today_u, 3) if today_u is not None else None,
            "today_downtime_pct": today_dt,
            "today_delta_pct": round(today_dt - downtime, 3) if today_dt is not None else None,
            "today_disclosed": today_disclosed,
        }

    # within-snapshot peer deviation of downtime% over the whole fleet.
    pool = [f["downtime_pct"] for f in feats.values()]
    for f in feats.values():
        f["downtime_peer_z"] = round(_robust_z(f["downtime_pct"], pool), 3) if len(pool) >= 2 else 0.0
        f["fleet_link_count"] = len(pool)

    # per-aisle mean downtime% for the aisle-clustering cross-feature.
    aisle_vals: Dict[str, List[float]] = {}
    for f in feats.values():
        if f["aisle"]:
            aisle_vals.setdefault(f["aisle"], []).append(f["downtime_pct"])
    aisle_mean = {a: round(sum(v) / len(v), 3) for a, v in aisle_vals.items()}
    aisle_n = {a: len(v) for a, v in aisle_vals.items()}
    for f in feats.values():
        f["aisle_mean_downtime_pct"] = aisle_mean.get(f["aisle"])
        f["aisle_link_count"] = aisle_n.get(f["aisle"])

    log.info("network features computed",
             extra={"links": len(feats),
                    "worst_downtime": round(max((f["downtime_pct"] for f in feats.values()), default=0), 2),
                    "median_downtime": round(median([f["downtime_pct"] for f in feats.values()]), 2) if feats else 0,
                    "today_disclosed": today_disclosed})
    return feats
