"""TRACKER root-cause attribution.

Ranks the contributors to a grid location's risk and produces a readable primary
cause describing the bad-tracker cluster (how many totes are mislocated there, how
recent, how it recurs across runs), plus cross-module flags: when one shuttle
dominates a recurring-bad location the fault may be the shuttle's positioning (→
Shuttle module); a lift in ERROR on the row flags the Lift module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

_FACTOR_LABEL = {
    "cluster": "Multiple totes mislocated at this position",
    "recent_cluster": "Recent (active) mislocated totes",
    "recurrence": "Recurs across PdM runs",
    "multi_shuttle": "Affects multiple shuttles (common-cause = the position)",
    "lift_involved": "A lift is in ERROR on this position",
    "peer_z": "Worse cluster than peer locations",
}


def build_rca(feat: Dict[str, Any], penalties: Dict[str, float], recurrence_runs: int) -> Tuple[str, Dict[str, Any]]:
    contributors: List[Dict[str, Any]] = []
    for key, pts in sorted(penalties.items(), key=lambda kv: -kv[1]):
        if pts <= 0.01:
            continue
        contributors.append({"factor": key, "label": _FACTOR_LABEL.get(key, key), "points": round(pts, 2)})

    bad = feat.get("bad_count", 0)
    recent = feat.get("recent_bad_count", 0)
    distinct_sh = feat.get("distinct_shuttles", 0)
    dom_sh = feat.get("dominant_shuttle")
    dom_share = feat.get("dominant_shuttle_share", 0.0)

    pick_err = feat.get("pick_error_count", 0)
    cross: List[Dict[str, str]] = []
    # One shuttle dominating a recurring/clustered position -> may be the shuttle, not the sensor.
    if dom_sh and dom_share >= 0.6 and (bad >= 2 or recurrence_runs >= 2):
        reason = (f"{dom_sh} accounts for {dom_share:.0%} of mislocations here "
                  f"(possible shuttle positioning fault, e.g. NOT_AT_CENTRE)")
        if pick_err:
            reason += f"; {pick_err} row(s) flagged SHUTTLE_PICK_ERROR"
        cross.append({"module": "shuttle", "reason": reason})
    if feat.get("lift_error_count", 0) > 0:
        cross.append({"module": "lift", "reason": "a lift is in ERROR on a bad-tracker row at this position"})

    material = [c for c in contributors if c["points"] >= 5]
    if not material:
        primary = f"Isolated bad-tracker ({bad} tote{'s' if bad != 1 else ''}, low risk)"
    else:
        top = material[0]["factor"]
        if top == "recurrence":
            primary = f"Position keeps mislocating totes — flagged in {recurrence_runs} prior runs"
        elif top == "recent_cluster":
            primary = f"{recent} recent tote{'s' if recent != 1 else ''} mislocated at this position"
        elif top == "multi_shuttle":
            primary = f"{distinct_sh} shuttles mislocated here — the position is the common cause"
        elif top == "lift_involved":
            primary = "Lift in ERROR at this position (bad-tracker)"
        else:
            primary = f"{bad} totes mislocated at this position (cluster)"

    rca = {
        "summary": primary,
        "contributors": contributors,
        "location": feat.get("location"),
        "aisle": feat.get("aisle"),
        "bad_count": bad,
        "recent_bad_count": recent,
        "recurrence_runs": recurrence_runs,
        "distinct_shuttles": distinct_sh,
        "dominant_shuttle": dom_sh,
        "dominant_shuttle_share": dom_share,
        "pick_error_count": pick_err,
        "lift_error_count": feat.get("lift_error_count", 0),
        "newest_age_days": feat.get("newest_age_days"),
        "oldest_age_days": feat.get("oldest_age_days"),
        "stuck_trackers": feat.get("stuck_trackers", []),
        "cross_module_flags": cross,
    }
    return primary, rca
