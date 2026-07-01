"""GATE root-cause attribution.

Ranks the contributors to a gate's risk and produces a readable primary cause
describing the actuator symptom (stuck non-closed / caught mid-actuation / persistently
or repeatedly non-closed / peer-elevated), plus a cross-module flag when a whole aisle's
gates are non-closed at once (a common-cause pointing at a zone controller / comms fault
rather than the individual actuator — a candidate for a future Network / Controller module).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

_FACTOR_LABEL = {
    "stuck_latency": "Stuck non-closed (high response latency)",
    "open_request": "Caught mid-actuation (OPEN REQUEST INITIATED)",
    "persistence": "Non-closed across consecutive runs",
    "stuck_recurrence": "Repeatedly stuck across runs",
    "non_closed_rate": "Often non-closed vs its own history",
    "peer_z": "Non-closed far more than peer gates",
}

_MATERIAL = 5.0


def build_rca(feat: Dict[str, Any], prior: Dict[str, Any], penalties: Dict[str, float]) -> Tuple[str, Dict[str, Any]]:
    contributors: List[Dict[str, Any]] = []
    for key, pts in sorted(penalties.items(), key=lambda kv: -kv[1]):
        if pts <= 0.01:
            continue
        contributors.append({"factor": key, "label": _FACTOR_LABEL.get(key, key), "points": round(pts, 2)})

    status = feat.get("status_now", "UNKNOWN")
    stuck = feat.get("stuck_minutes", 0.0)
    consec = prior.get("consecutive_non_closed", 0)
    rate = prior.get("non_closed_rate", 0.0)

    # Cross-module flag: many gates on one aisle non-closed together -> common cause.
    cross: List[Dict[str, str]] = []
    if feat.get("aisle") and feat.get("aisle_non_closed_count", 0) >= 3 and feat.get("is_non_closed"):
        cross.append({
            "module": "network",
            "reason": f"{feat['aisle_non_closed_count']} gates on {feat['aisle']} are non-closed at once "
                      f"— possible zone-controller / comms common cause, not this actuator alone",
        })

    material = [c for c in contributors if c["points"] >= _MATERIAL]
    if not material:
        if feat.get("is_open_request"):
            primary = "Caught in OPEN REQUEST INITIATED (mid-actuation)"
        elif feat.get("is_open"):
            primary = "Gate OPEN (in use) — no stuck signal"
        elif feat.get("status_unknown"):
            primary = f"Gate status '{status}' (unmapped) — no stuck signal"
        else:
            primary = "Gate resting CLOSED (healthy)"
    else:
        top = material[0]["factor"]
        if top == "stuck_latency":
            primary = f"Stuck {status} for {stuck:.0f} min — actuator not completing"
        elif top == "persistence":
            primary = f"Non-closed across {consec} consecutive runs — not returning to CLOSED"
        elif top == "stuck_recurrence":
            primary = f"Repeatedly stuck across {prior.get('prior_stuck', 0)} prior runs"
        elif top == "open_request":
            primary = "Caught in OPEN REQUEST INITIATED (mid-actuation)"
        elif top in ("non_closed_rate", "peer_z"):
            primary = f"Non-closed in {rate:.0%} of runs — elevated vs peer gates"
        else:
            primary = f"Gate {status}"

    rca = {
        "summary": primary,
        "contributors": contributors,
        "gate_id": feat.get("gate_id"),
        "aisle": feat.get("aisle"),
        "level": feat.get("level"),
        "face": feat.get("face"),
        "status_now": status,
        "stuck_minutes": stuck,
        "consecutive_non_closed": consec,
        "non_closed_rate": rate,
        "prior_stuck_runs": prior.get("prior_stuck", 0),
        "runs_observed": prior.get("runs_observed", 0),
        "aisle_non_closed_count": feat.get("aisle_non_closed_count", 0),
        "cross_module_flags": cross,
    }
    return primary, rca
