"""NETWORK / COMMS root-cause attribution (per-shuttle comms link).

Ranks the downtime penalties and names the dominant symptom; every flagged link cross-links to the
SHUTTLE module (comms drops precede pick/handling errors) so the meta-module can chain
network -> shuttle -> downstream failures. ``aisle_cluster_flags`` runs after all links are scored and
adds an aisle-level comms/AP/controller flag when downtime clusters on one aisle (a common cause).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

_MATERIAL = 5.0

_LABEL = {
    "downtime_abs": "High network downtime",
    "downtime_peer_z": "Downtime far above peer links",
    "recent_spike": "Downtime spiking today (degrading now)",
    "recurrence": "Elevated downtime across prior runs",
}


def _contributors(penalties: Dict[str, float]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, pts in sorted(penalties.items(), key=lambda kv: -kv[1]):
        if pts <= 0.01:
            continue
        out.append({"factor": key, "label": _LABEL.get(key, key), "points": round(pts, 2)})
    return out


def build_rca(feat: Dict[str, Any], penalties: Dict[str, float], recurrence: int, tier: str) -> Tuple[str, Dict[str, Any]]:
    contributors = _contributors(penalties)
    dt = feat.get("downtime_pct", 0.0)
    up = feat.get("uptime_pct", 0.0)
    today_dt = feat.get("today_downtime_pct")
    sid = feat.get("shuttle_id")

    material = [c for c in contributors if c["points"] >= _MATERIAL]
    if not material:
        primary = f"Comms healthy ({up:.1f}% uptime, {dt:.1f}% downtime)"
    else:
        top = material[0]["factor"]
        if top == "downtime_abs":
            primary = f"High network downtime: {dt:.1f}% ({up:.1f}% uptime) — flaky/degrading comms link"
        elif top == "downtime_peer_z":
            primary = f"Network downtime {dt:.1f}% — far above peer shuttle links ({feat.get('downtime_peer_z', 0):+.1f}σ)"
        elif top == "recent_spike":
            primary = f"Comms degrading now: {today_dt:.1f}% downtime today vs {dt:.1f}% over the window"
        elif top == "recurrence":
            primary = f"Network downtime elevated across {recurrence} prior runs — persistent comms degradation"
        else:
            primary = f"Network downtime {dt:.1f}%"

    # Every flagged link (tier != ok) points at the SHUTTLE module: comms drops precede pick/handling
    # errors. Gated on tier so a healthy link that merely lost a few points does not cross-flag.
    cross: List[Dict[str, str]] = []
    if tier != "ok":
        cross.append({"module": "shuttle",
                      "reason": f"comms link degraded ({dt:.1f}% downtime) — check {sid}'s pick/handling "
                                f"errors; network drops often precede/cause shuttle operational faults"})

    rca = {
        "summary": primary,
        "entity": "network_link",
        "contributors": contributors,
        "shuttle_id": sid,
        "aisle": feat.get("aisle"),
        "uptime_pct": up,
        "downtime_pct": dt,
        "today_downtime_pct": today_dt,
        "today_delta_pct": feat.get("today_delta_pct"),
        "downtime_peer_z": feat.get("downtime_peer_z"),
        "recurrence_runs": recurrence,
        "cross_module_flags": cross,
    }
    return primary, rca


def aisle_cluster_flags(components: List[Any], features: Dict[str, Dict[str, Any]],
                        aisle_downtime_pct: float, min_links: int) -> None:
    """Add an aisle-level comms flag when downtime clusters on one aisle (mean downtime >= threshold
    OR >= min_links flagged links) — a candidate aisle AP/controller common cause (-> meta / Controller)."""
    # aisle -> mean downtime (from features) and the count of flagged links (from the scored components).
    aisle_mean: Dict[str, float] = {}
    for f in features.values():
        if f.get("aisle") is not None and f.get("aisle_mean_downtime_pct") is not None:
            aisle_mean[f["aisle"]] = float(f["aisle_mean_downtime_pct"])

    flagged_by_aisle: Dict[str, List[Any]] = {}
    for c in components:
        aisle = (c.rca or {}).get("aisle")
        if aisle and c.risk_tier != "ok":
            flagged_by_aisle.setdefault(aisle, []).append(c)

    for aisle, mean_dt in aisle_mean.items():
        flagged = flagged_by_aisle.get(aisle, [])
        if mean_dt >= aisle_downtime_pct or len(flagged) >= min_links:
            note = {"module": "meta",
                    "reason": f"comms downtime clusters on {aisle} (mean {mean_dt:.1f}%, "
                              f"{len(flagged)} flagged link(s)) — possible aisle AP/controller common cause"}
            for c in flagged:
                c.rca.setdefault("cross_module_flags", []).append(note)
