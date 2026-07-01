"""SHUTTLE feature extraction — errors normalised by cycles + current status.

The defining shuttle signal is **errors per million cycles** (usage-normalised
fault rate): a busy shuttle with many errors is judged against how much work it
did. Cumulative cycles also feed the cycles-based RUL in health.py. The error
window anchors to ``as_of = max(created_time)`` (live/frozen parity).

Every feature is documented in modules/shuttle/README.md with its formula.
"""

from __future__ import annotations

import datetime as _dt
import re
from statistics import median
from typing import Any, Dict, List

import pandas as pd

from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.shuttle.spec import error_info, is_mechanical, spec

log = get_logger("shuttle.features")

_SH_RE = re.compile(r"(QD_Shuttle_(\d+)_(\d+))", re.IGNORECASE)
_DAILY_RE = re.compile(r"(QD_Shuttle_\d+_\d+)\s*\((\d+)\)", re.IGNORECASE)


def _parse_window_days(window: str) -> float:
    m = re.match(r"now-(\d+)([smhdwMy])", (window or "").strip())
    if not m:
        return 2.0
    n, unit = int(m.group(1)), m.group(2)
    factor = {"s": 1 / 86400, "m": 1 / 1440, "h": 1 / 24, "d": 1, "w": 7, "M": 30, "y": 365}
    return max(n * factor.get(unit, 1), 1 / 24)


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


def _parse_shuttle_id(sid: str) -> Dict[str, Any]:
    m = _SH_RE.match(str(sid))
    return {"aisle": f"aisle_{m.group(2)}", "unit_no": m.group(3)} if m else {"aisle": None, "unit_no": None}


def _cycles_table(df) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    if df is None or df.empty or "shuttle_id" not in df.columns:
        return out
    for _, r in df.iterrows():
        sid = str(r["shuttle_id"])
        p = pd.to_numeric(r.get("PUTAWAY"), errors="coerce")
        k = pd.to_numeric(r.get("PICKING"), errors="coerce")
        s = pd.to_numeric(r.get("RESHUFFLING"), errors="coerce")
        p, k, s = (0 if pd.isna(x) else float(x) for x in (p, k, s))
        total = p + k + s
        out[sid] = {"putaway": p, "picking": k, "reshuffling": s, "total": total,
                    "reshuffle_share": round(s / total, 4) if total else 0.0}
    return out


def _daily_counts(df) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if df is None or df.empty:
        return out
    col = "Value" if "Value" in df.columns else (df.columns[-1] if len(df.columns) else None)
    if not col:
        return out
    for val in df[col].dropna().astype(str):
        for sid, n in _DAILY_RE.findall(val):
            out[sid] = out.get(sid, 0) + int(n)
    return out


def _alert_shuttles(df) -> set:
    out = set()
    if df is None or df.empty:
        return out
    col = "message" if "message" in df.columns else (df.columns[0] if len(df.columns) else None)
    if not col:
        return out
    for msg in df[col].dropna().astype(str):
        for m in _SH_RE.findall(msg):
            out.add(m[0])
    return out


def _bad_tracker(df) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if df is None or df.empty or "shuttle_id" not in df.columns:
        return out
    bt = df.dropna(subset=["shuttle_id"])
    desc_col = "shuttle Status Description"
    for sid, grp in bt.groupby(bt["shuttle_id"].astype(str)):
        pick_err = False
        if desc_col in grp.columns:
            pick_err = grp[desc_col].astype(str).str.upper().str.contains("ERROR").any()
        out[sid] = {"events": int(len(grp)), "pick_error": bool(pick_err)}
    return out


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    s = spec()
    errors = bundle.frames.get("errors", pd.DataFrame())
    cycles = _cycles_table(bundle.frames.get("cycles"))
    daily = _daily_counts(bundle.frames.get("daily"))
    alerts = _alert_shuttles(bundle.frames.get("alerts"))
    bad = _bad_tracker(bundle.frames.get("bad_tracker"))
    window = bundle.notes.get("window", "now-30d")
    window_days = _parse_window_days(window)

    if not cycles and (errors is None or errors.empty):
        log.warning("no shuttle cycles or errors fetched")
        return {}

    # Error window (anchored to data as_of).
    win = pd.DataFrame()
    as_of = None
    if errors is not None and not errors.empty and "shuttle_id" in errors.columns:
        e = errors.copy()
        e["ct"] = pd.to_datetime(e["created_time"], errors="coerce")
        e = e.dropna(subset=["ct", "shuttle_id"])
        if not e.empty:
            as_of = e["ct"].max() if s.get("anchor_to_data_asof", True) else pd.Timestamp(_dt.datetime.now())
            win = e[e["ct"] >= as_of - pd.Timedelta(days=window_days)]
    as_of_iso = as_of.isoformat() if as_of is not None else None

    # Universe = roster from cycles ∪ shuttles seen anywhere.
    universe = set(cycles) | set(daily) | set(bad) | set(alerts)
    if not win.empty:
        universe |= set(win["shuttle_id"].astype(str))

    feats: Dict[str, Dict[str, Any]] = {}
    for sid in sorted(universe):
        cyc = cycles.get(sid, {"putaway": 0, "picking": 0, "reshuffling": 0, "total": 0, "reshuffle_share": 0.0})
        g = win[win["shuttle_id"].astype(str) == sid] if not win.empty else pd.DataFrame()
        n = int(len(g))

        type_counts: Dict[str, int] = {}
        desc_counts: Dict[str, int] = {}
        sev_sum = 0.0
        mech = 0
        cat_counts: Dict[str, int] = {}
        for _, row in g.iterrows():
            et = str(row.get("error_type"))
            ed = str(row.get("error_desc"))
            info = error_info(et, ed)
            type_counts[et] = type_counts.get(et, 0) + 1
            desc_counts[ed] = desc_counts.get(ed, 0) + 1
            sev_sum += float(info["severity"])
            cat_counts[info["category"]] = cat_counts.get(info["category"], 0) + 1
            if is_mechanical(info["category"]):
                mech += 1

        times = sorted(g["ct"].tolist()) if not g.empty else []
        gaps_h = [(times[i] - times[i - 1]).total_seconds() / 3600.0 for i in range(1, len(times))]
        last_age_h = (as_of - times[-1]).total_seconds() / 3600.0 if (times and as_of is not None) else None
        total_cycles = cyc["total"]
        # errors/Mcycle is only defined when the shuttle's cycle count is known; a
        # shuttle present in errors/daily/alerts but absent from the CYCLES roster
        # gets None — NOT a fabricated n*1000 rate that would pollute the fleet
        # median and every other shuttle's peer z-score.
        epc = round(n / total_cycles * 1e6, 3) if total_cycles > 0 else None
        top_desc = max(desc_counts, key=desc_counts.get) if desc_counts else None
        top_type = max(type_counts, key=type_counts.get) if type_counts else None

        feats[sid] = {
            "component_id": sid,
            **_parse_shuttle_id(sid),
            "as_of": as_of_iso,
            "window": window,
            "window_days": round(window_days, 3),
            "putaway_cycles": cyc["putaway"],
            "picking_cycles": cyc["picking"],
            "reshuffling_cycles": cyc["reshuffling"],
            "total_cycles": total_cycles,
            "reshuffle_share": cyc["reshuffle_share"],
            "error_count": n,
            "errors_per_mcycle": epc,
            "distinct_types": len(type_counts),
            "severity_mean": round(sev_sum / n, 4) if n else 0.0,
            "mechanical_count": mech,
            "mechanical_share": round(mech / n, 4) if n else 0.0,
            "recurrence_max": max(desc_counts.values()) if desc_counts else 0,
            "type_counts": type_counts,
            "desc_counts": dict(sorted(desc_counts.items(), key=lambda kv: -kv[1])[:6]),
            "category_counts": cat_counts,
            "top_type": top_type,
            "top_desc": top_desc,
            "top_desc_n": desc_counts.get(top_desc, 0) if top_desc else 0,
            "median_gap_hours": round(median(gaps_h), 3) if gaps_h else None,
            "last_error_age_hours": round(last_age_h, 2) if last_age_h is not None else None,
            "current_daily_errors": daily.get(sid, 0),
            # Today's current errors beyond what the analysis window already counted:
            # when the window covers today (live) daily≈window so excess≈0 (no
            # double-count with epc/severity); when the window is frozen/old, the
            # daily panel surfaces genuinely new activity -> full excess.
            "current_daily_excess": max(int(daily.get(sid, 0)) - n, 0),
            "bad_tracker_events": bad.get(sid, {}).get("events", 0),
            "current_pick_error": bad.get(sid, {}).get("pick_error", False),
            "current_alert": sid in alerts,
        }

    # Peer-relative signals across the fleet (exclude cycle-less shuttles whose epc
    # is None so they neither pollute the median nor get a fabricated z-score).
    epcs = [f["errors_per_mcycle"] for f in feats.values() if f["errors_per_mcycle"] is not None]
    reshuffles = [f["reshuffle_share"] for f in feats.values() if f["total_cycles"] > 0]
    peer_epc = round(median(epcs), 3) if epcs else 0.0
    peer_resh = round(median(reshuffles), 4) if reshuffles else 0.0
    for f in feats.values():
        f["fleet_median_epc"] = peer_epc
        f["epc_peer_z"] = (round(_robust_z(f["errors_per_mcycle"], epcs), 3)
                           if f["errors_per_mcycle"] is not None else 0.0)
        f["fleet_median_reshuffle"] = peer_resh
        f["reshuffle_excess"] = round(max(f["reshuffle_share"] - peer_resh, 0.0), 4)

    log.info("shuttle features computed",
             extra={"shuttles": len(feats), "as_of": as_of_iso, "window_days": window_days,
                    "win_errors": int(len(win)) if not win.empty else 0})
    return feats
