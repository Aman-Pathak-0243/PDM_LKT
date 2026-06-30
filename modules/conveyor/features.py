"""CONVEYOR feature extraction — per-zone congestion from the queue-vs-limit signal.

Since all zones routinely run above their soft limit, absolute saturation is not
discriminating; the model leans on mean congestion *excess* above 1.0, severe-
saturation share, peak backups, buffer fill, and peer deviation. Each feature is
documented in modules/conveyor/README.md.
"""

from __future__ import annotations

import re
from statistics import median
from typing import Any, Dict, List

import pandas as pd

from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.conveyor.spec import spec, thresholds

log = get_logger("conveyor.features")


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


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    t = thresholds()
    severe = float(t.get("severe_ratio", 1.5))
    zc = bundle.frames.get("zone_counts", pd.DataFrame())
    if zc is None or zc.empty or "zone" not in zc.columns:
        log.warning("no conveyor zone data")
        return {}

    tcol = "time" if "time" in zc.columns else zc.columns[0]
    ca_col = next((c for c in zc.columns if c.lower().startswith("conveyor actual")), None)
    cl_col = next((c for c in zc.columns if c.lower().startswith("conveyor limit")), None)
    ba_col = next((c for c in zc.columns if c.lower().startswith("buffer actual")), None)
    bl_col = next((c for c in zc.columns if c.lower().startswith("buffer limit")), None)
    as_of = str(zc[tcol].max())

    feats: Dict[str, Dict[str, Any]] = {}
    for zone, g in zc.groupby(zc["zone"].astype(str)):
        ca = _num(g[ca_col]) if ca_col else pd.Series(dtype=float)
        cl = _num(g[cl_col]) if cl_col else pd.Series(dtype=float)
        ba = _num(g[ba_col]) if ba_col else pd.Series(dtype=float)
        bl = _num(g[bl_col]) if bl_col else pd.Series(dtype=float)
        cong = (ca / cl.replace(0, pd.NA)).dropna()
        bcong = (ba / bl.replace(0, pd.NA)).dropna()
        feats[f"zone_{zone}"] = {
            "component_id": f"zone_{zone}",
            "zone": zone,
            "as_of": as_of,
            "window": bundle.notes.get("window"),
            "samples": int(len(g)),
            "throughput_mean": round(float(ca.mean()), 2) if len(ca) else 0.0,
            "conveyor_limit": int(cl.dropna().iloc[-1]) if len(cl.dropna()) else None,
            "congestion_mean": round(float(cong.mean()), 4) if len(cong) else 0.0,
            "congestion_peak": round(float(cong.max()), 4) if len(cong) else 0.0,
            "congestion_p90": round(float(cong.quantile(0.9)), 4) if len(cong) else 0.0,
            "severe_saturation_share": round(float((cong >= severe).mean()), 4) if len(cong) else 0.0,
            "buffer_congestion_mean": round(float(bcong.mean()), 4) if len(bcong) else 0.0,
            "buffer_peak": round(float(bcong.max()), 4) if len(bcong) else 0.0,
            "idle_share": round(float((ca == 0).mean()), 4) if len(ca) else 0.0,
            "system_on_hold": bundle.notes.get("system_on_hold"),
            "system_in_transit": bundle.notes.get("system_in_transit"),
        }

    congs = [f["congestion_mean"] for f in feats.values()]
    bufs = [f["buffer_congestion_mean"] for f in feats.values()]
    peer_c = round(median(congs), 4) if congs else 0.0
    peer_b = round(median(bufs), 4) if bufs else 0.0
    for f in feats.values():
        f["peer_median_congestion"] = peer_c
        f["congestion_peer_z"] = round(_robust_z(f["congestion_mean"], congs), 3)
        f["peer_median_buffer"] = peer_b

    log.info("conveyor features computed",
             extra={"zones": len(feats), "as_of": as_of,
                    "worst_congestion": max(congs) if congs else None})
    return feats
