"""BIN / TOTE-MECHANICAL root-cause attribution.

Ranks the contributors to a bin slot's risk and produces a readable primary cause
describing the block (stuck/unresolved duration, chronic-slot history, cross-run recurrence,
multiple totes blocked), plus a cross-module flag when many current blocks concentrate on one
aisle (that aisle's shuttle may be mis-seating totes → Shuttle module; mislocation → Tracker).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

_FACTOR_LABEL = {
    "blocked_base": "Tote blocked at this slot now",
    "block_age": "Block unresolved for a long time (stuck)",
    "cluster": "Multiple totes blocked at this slot now",
    "historical": "Chronic slot — blocked repeatedly in history",
    "recurrence": "Recurs across PdM runs",
    "peer_z": "Blocked far longer than peer slots",
}

_MATERIAL = 5.0


def build_rca(feat: Dict[str, Any], penalties: Dict[str, float], recurrence_runs: int) -> Tuple[str, Dict[str, Any]]:
    contributors: List[Dict[str, Any]] = []
    for key, pts in sorted(penalties.items(), key=lambda kv: -kv[1]):
        if pts <= 0.01:
            continue
        contributors.append({"factor": key, "label": _FACTOR_LABEL.get(key, key), "points": round(pts, 2)})

    age = feat.get("block_age_hours", 0.0)
    hist = feat.get("historical_block_count", 0)
    cluster = feat.get("current_block_count", 1)

    # Cross-module flag: an ANOMALOUS concentration of blocks on one aisle (peer-relative
    # outlier, not an absolute floor) -> that aisle's shuttle may be mis-seating totes.
    cross: List[Dict[str, str]] = []
    if feat.get("aisle") and feat.get("aisle_is_outlier"):
        cross.append({
            "module": "shuttle",
            "reason": f"{feat['aisle_block_count']} bins blocked on {feat['aisle']} at once "
                      f"(anomalous concentration) — that aisle's shuttle may be mis-seating totes",
        })

    # Rank ignores the flat blocked_base when naming the dominant cause (it is always present).
    material = [c for c in contributors if c["points"] >= _MATERIAL and c["factor"] != "blocked_base"]
    if not material:
        primary = f"Tote blocked at this slot ({age:.0f} h, low risk)" if age else "Tote blocked at this slot (fresh, low risk)"
    else:
        top = material[0]["factor"]
        if top == "recurrence":
            primary = f"Slot keeps blocking totes — flagged in {recurrence_runs} prior runs"
        elif top == "block_age":
            primary = f"Block unresolved for {age:.0f} h — tote stuck at this slot"
        elif top == "historical":
            primary = f"Chronic slot — blocked {hist} times in history"
        elif top == "cluster":
            primary = f"{cluster} totes blocked at this slot at once"
        elif top == "peer_z":
            primary = f"Blocked far longer than peer slots ({age:.0f} h)"
        else:
            primary = "Bin blocked"

    rca = {
        "summary": primary,
        "contributors": contributors,
        "location": feat.get("location"),
        "aisle": feat.get("aisle"),
        "level": feat.get("level"),
        "deep": feat.get("deep"),
        "block_age_hours": age,
        "current_block_count": cluster,
        "distinct_containers": feat.get("distinct_containers"),
        "historical_block_count": hist,
        "recurrence_runs": recurrence_runs,
        "aisle_block_count": feat.get("aisle_block_count", 0),
        "cross_module_flags": cross,
    }
    return primary, rca
