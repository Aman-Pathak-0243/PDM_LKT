"""CONTROLLER / COMPUTE root-cause attribution (per compute node).

Ranks the CPU penalties and names the dominant symptom; notes the SQL CPU share as context. When the
node is saturated (tier >= meta_flag_tier), raises a system-wide 'meta' cross-flag — a saturated
controller starves the WES and slows every shuttle/lift/GTP operation, so the meta-module (Module 11)
can chain compute-saturation -> system-wide throttle -> downstream errors.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from core.registry import tier_rank

_MATERIAL = 5.0

_LABEL = {
    "saturation": "High CPU utilization",
    "sustained_high": "CPU pinned high across consecutive runs",
}


def _contributors(penalties: Dict[str, float]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, pts in sorted(penalties.items(), key=lambda kv: -kv[1]):
        if pts <= 0.01:
            continue
        out.append({"factor": key, "label": _LABEL.get(key, key), "points": round(pts, 2)})
    return out


def build_rca(feat: Dict[str, Any], penalties: Dict[str, float], consec_high: int, tier: str,
              sql_dominant_share: float, meta_tier: str) -> Tuple[str, Dict[str, Any]]:
    contributors = _contributors(penalties)
    util = feat.get("utilization_pct", 0.0)
    idle = feat.get("cpu_idle_pct", 0.0)
    sql = feat.get("cpu_sql_pct", 0.0)
    sql_share = feat.get("sql_share", 0.0)
    node = feat.get("node")
    sql_dominated = bool(sql_share >= sql_dominant_share and util > 0)
    sql_note = " — SQL-dominated load" if sql_dominated else ""

    material = [c for c in contributors if c["points"] >= _MATERIAL]
    if not material:
        primary = f"CPU healthy ({util:.0f}% utilization, {idle:.0f}% idle, {sql:.0f}% SQL)"
    else:
        top = material[0]["factor"]
        if top == "saturation":
            primary = f"High CPU utilization: {util:.0f}% ({idle:.0f}% idle){sql_note} — controller throttle/crash risk"
        elif top == "sustained_high":
            primary = f"CPU pinned high ({util:.0f}%) across {consec_high} consecutive runs — sustained controller saturation"
        else:
            primary = f"CPU utilization {util:.0f}%"

    # A saturated controller is a SYSTEM-WIDE risk: it runs the WES that drives every robot.
    cross: List[Dict[str, str]] = []
    if tier_rank(tier) <= tier_rank(meta_tier):   # tier is at or worse than the meta-flag tier
        cross.append({"module": "meta",
                      "reason": f"controller {node} CPU saturated ({util:.0f}%) — system-wide throttle risk: "
                                f"starves the WES and slows every shuttle/lift/GTP operation"})

    rca = {
        "summary": primary,
        "entity": "compute_node",
        "contributors": contributors,
        "node": node,
        "utilization_pct": util,
        "cpu_idle_pct": idle,
        "cpu_sql_pct": sql,
        "cpu_other_pct": feat.get("cpu_other_pct"),
        "sql_share": sql_share,
        "sql_dominated": sql_dominated,
        "consecutive_high": consec_high,
        "cross_module_flags": cross,
    }
    return primary, rca
