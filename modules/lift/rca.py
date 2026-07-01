"""LIFT root-cause attribution.

Given a lift's features and the penalty breakdown computed by ``health.py``,
produce the dominant contributing signals: a one-line ``primary_cause``, a ranked
contributor list, the error-code mix, and any cross-module flags (e.g. comms
errors that also inform the Network module — Module 9, built Session 9).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from modules.lift.spec import error_info

_FACTOR_LABEL = {
    "rate_peer_z": "Error rate far above peer lifts",
    "abs_rate": "High absolute error rate",
    "severity": "High-severity error mix",
    "mechanical": "Mechanical-wear errors",
    "recurrence": "Same fault recurring",
    "diversity": "Many distinct fault types",
    "current_error": "Currently in ERROR state",
}


def build_rca(
    feat: Dict[str, Any], penalties: Dict[str, float]
) -> Tuple[str, Dict[str, Any]]:
    # Rank contributors by points they removed from health.
    contributors: List[Dict[str, Any]] = []
    for key, pts in sorted(penalties.items(), key=lambda kv: -kv[1]):
        if pts <= 0.01:
            continue
        contributors.append(
            {"factor": key, "label": _FACTOR_LABEL.get(key, key), "points": round(pts, 2)}
        )

    # Dominant error code.
    code_counts: Dict[str, int] = feat.get("code_counts", {})
    dominant = None
    if code_counts:
        top = max(code_counts, key=code_counts.get)
        info = error_info(top)
        dominant = {
            "code": top,
            "desc": info["desc"],
            "category": info["category"],
            "severity": info["severity"],
            "count": code_counts[top],
        }

    # Cross-module flags: communication-class errors precede many faults.
    comm = feat.get("category_counts", {})
    cross = []
    comm_n = comm.get("communication", 0) + comm.get("drive_comm", 0)
    if comm_n and feat.get("error_count"):
        if comm_n / feat["error_count"] >= 0.2:
            cross.append(
                {"module": "network", "reason": f"{comm_n} communication-class errors "
                 f"({comm_n/feat['error_count']:.0%} of window)"}
            )

    # Primary cause sentence.
    if feat.get("current_error_status"):
        primary = "Lift currently reporting ERROR status (bad-tracker)"
    elif dominant and (contributors and contributors[0]["factor"] in {"severity", "mechanical"}):
        primary = f"{dominant['desc']} (code {dominant['code']}) — {dominant['count']} events"
    elif contributors and contributors[0]["factor"] == "rate_peer_z":
        primary = (
            f"Error rate {feat.get('error_rate_per_day')}/day "
            f"({feat.get('rate_peer_z')}σ above peer median)"
        )
    elif dominant:
        primary = f"{dominant['desc']} (code {dominant['code']}) — {dominant['count']} events"
    else:
        primary = "No significant fault signal in window"

    rca = {
        "summary": primary,
        "contributors": contributors,
        "dominant_error": dominant,
        "error_mix": dict(sorted(code_counts.items(), key=lambda kv: -kv[1])[:6]),
        "mechanical_share": feat.get("mechanical_share"),
        "share_of_total": feat.get("share_of_total"),
        "cross_module_flags": cross,
    }
    return primary, rca
