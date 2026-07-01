"""SHUTTLE root-cause attribution.

Ranks the penalty contributors, identifies the dominant fault (error_type +
error_desc), reports the error mix and cycle context, and raises cross-module
flags (e.g. servo-drive faults → drive layer; persistent pick errors → tracker).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from modules.shuttle.spec import error_info

_FACTOR_LABEL = {
    "epc_peer_z": "Errors/cycle far above fleet",
    "epc_abs": "High errors per million cycles",
    "severity": "High-severity error mix",
    "mechanical": "Mechanical-wear errors (fork/telescope)",
    "recurrence": "Same fault recurring",
    "diversity": "Many distinct fault types",
    "reshuffle_excess": "Reshuffle load above fleet",
    "current_badtracker": "Currently in a pick-error state (bad-tracker)",
    "current_alert": "Currently in an active alert",
    "current_daily": "New errors reported today (beyond the window)",
}


def build_rca(feat: Dict[str, Any], penalties: Dict[str, float]) -> Tuple[str, Dict[str, Any]]:
    contributors: List[Dict[str, Any]] = []
    for key, pts in sorted(penalties.items(), key=lambda kv: -kv[1]):
        if pts <= 0.01:
            continue
        contributors.append({"factor": key, "label": _FACTOR_LABEL.get(key, key), "points": round(pts, 2)})

    desc_counts: Dict[str, int] = feat.get("desc_counts", {})
    dominant = None
    if desc_counts:
        top = max(desc_counts, key=desc_counts.get)
        info = error_info(feat.get("top_type"), top)
        dominant = {"error_type": feat.get("top_type"), "error_desc": top,
                    "category": info["category"], "severity": info["severity"],
                    "count": desc_counts[top]}

    cross: List[Dict[str, str]] = []
    cats = feat.get("category_counts", {})
    if cats.get("drive_motor"):
        cross.append({"module": "network", "reason": "servo-drive faults can follow comms/drive degradation"})
    if feat.get("current_pick_error") or feat.get("bad_tracker_events", 0) >= 3:
        cross.append({"module": "tracker", "reason": f"{feat.get('bad_tracker_events',0)} bad-tracker events / pick errors"})

    if feat.get("current_alert"):
        primary = "Currently in an active Quadron alert"
    elif dominant and contributors and contributors[0]["factor"] in {"severity", "mechanical", "epc_peer_z"}:
        primary = f"{dominant['error_desc']} ({dominant['error_type']}) — {dominant['count']} events"
    elif feat.get("bad_tracker_events", 0) and not desc_counts:
        primary = f"{feat['bad_tracker_events']} current bad-tracker / pick events"
    elif dominant:
        primary = f"{dominant['error_desc']} ({dominant['error_type']}) — {dominant['count']} events"
    else:
        primary = "No significant fault signal in window"

    rca = {
        "summary": primary,
        "contributors": contributors,
        "dominant_error": dominant,
        "error_mix": desc_counts,
        "errors_per_mcycle": feat.get("errors_per_mcycle"),
        "total_cycles": feat.get("total_cycles"),
        "reshuffle_share": feat.get("reshuffle_share"),
        "cross_module_flags": cross,
    }
    return primary, rca
