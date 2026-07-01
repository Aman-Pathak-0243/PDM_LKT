"""CONVEYOR root-cause attribution.

Ranks the congestion contributors and produces a readable primary cause describing
how backed-up the zone runs (mean/peak congestion, time spent severely saturated,
buffer fill), plus cross-module flags (sustained buffer fill → downstream/outbound).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

_FACTOR_LABEL = {
    "congestion_excess": "Queue runs above its limit",
    "severe_saturation": "Sustained severe saturation",
    "peak_excess": "Extreme peak backup",
    "buffer_congestion": "Buffer filling (downstream backup)",
    "congestion_peer_z": "More congested than peer zones",
    "sustained_congestion": "Congested most of the window (p90)",
    "stall_idle": "Zone idle/stalled while peers flow (possible belt/motor stall)",
}


def build_rca(feat: Dict[str, Any], penalties: Dict[str, float], peak_ref: float) -> Tuple[str, Dict[str, Any]]:
    contributors: List[Dict[str, Any]] = []
    for key, pts in sorted(penalties.items(), key=lambda kv: -kv[1]):
        if pts <= 0.01:
            continue
        contributors.append({"factor": key, "label": _FACTOR_LABEL.get(key, key), "points": round(pts, 2)})

    cross: List[Dict[str, str]] = []
    if feat.get("buffer_congestion_mean", 0) >= 0.5:
        cross.append({"module": "outbound/buffer", "reason": "buffer filling — downstream not clearing"})

    cm = feat.get("congestion_mean", 0.0)
    peak = feat.get("congestion_peak", 0.0)
    sat = feat.get("severe_saturation_share", 0.0)
    idle = feat.get("idle_share", 0.0)
    material = [c for c in contributors if c["points"] >= 5]
    if material:
        top = material[0]["factor"]
        if top == "stall_idle":
            primary = (f"Zone idle {idle:.0%} of the window while peer zones keep flowing "
                       f"— possible belt/motor stall (throughput {feat.get('throughput_mean')})")
        elif top == "buffer_congestion":
            primary = f"Buffer filling ({feat.get('buffer_congestion_mean'):.0%} of limit) — downstream backup"
        elif top == "peak_excess":
            primary = f"Peak backup {peak:.2f}× limit (extreme spikes)"
        elif top == "severe_saturation":
            primary = f"Severely saturated {sat:.0%} of the window (≥ severe limit)"
        elif top == "sustained_congestion":
            primary = f"Congested most of the window (p90 {feat.get('congestion_p90'):.2f}× limit)"
        else:
            primary = f"Queue runs {cm:.2f}× its limit on average"
    else:
        primary = f"Flowing normally (avg {cm:.2f}× limit)"

    rca = {
        "summary": primary,
        "contributors": contributors,
        "congestion_mean": cm,
        "congestion_peak": peak,
        "severe_saturation_share": sat,
        "buffer_congestion_mean": feat.get("buffer_congestion_mean"),
        "throughput_mean": feat.get("throughput_mean"),
        "cross_module_flags": cross,
    }
    return primary, rca
