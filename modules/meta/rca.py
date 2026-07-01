"""SYSTEM-WIDE ANOMALY (META) root-cause attribution — the compound-incident narrative.

Names the dominant compound pattern for a scope, lists the realized causal chain edges and the flagged
member components (so the incident view shows exactly which modules/units are involved), and emits a
cross_module_flag per involved module so an operator can drill into the source module's own page.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

_LABEL = {
    "breadth": "Multiple subsystems degraded together",
    "severity": "A degraded subsystem is severe",
    "chain": "Realized cross-module causal chain",
    "persistence": "Compound incident persists across runs",
    "controller_trigger": "Controller saturated (system-wide)",
    "aisle_breadth": "Many aisles compound at once",
    "meta_flag": "Explicit cross-module escalation (→ meta)",
}


def _contributors(penalties: Dict[str, float]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, pts in sorted(penalties.items(), key=lambda kv: -kv[1]):
        if pts <= 0.01:
            continue
        out.append({"factor": key, "label": _LABEL.get(key, key), "points": round(pts, 2)})
    return out


def _chain_str(edges: List[Dict[str, str]]) -> str:
    return ", ".join(f"{e['from']}→{e['to']}" for e in edges)


def build_rca(feat: Dict[str, Any], penalties: Dict[str, float], consec_compound: int) -> Tuple[str, Dict[str, Any]]:
    contributors = _contributors(penalties)
    scope = feat.get("scope")
    kind = feat.get("scope_kind")
    breadth = int(feat.get("breadth", 0))
    modules = feat.get("flagged_modules", [])
    worst = str(feat.get("worst_flagged_tier", "ok")).lower()
    edges = feat.get("chain_edges", []) or []
    members = feat.get("flagged_members", []) or []

    if kind == "system":
        ctl = str(feat.get("controller_tier", "ok")).lower()
        n_aisles = int(feat.get("compound_aisle_count", 0))
        bits = []
        if ctl != "ok":
            bits.append(f"controller {ctl} (WES throttle risk)")
        if n_aisles:
            bits.append(f"{n_aisles} aisle(s) in compound incident ({', '.join(feat.get('compound_aisles', []))})")
        if breadth >= 2:
            bits.append(f"{breadth} area subsystems degraded ({', '.join(modules)})")
        if not bits:
            primary = "System nominal — no controller saturation or cross-area compound pattern"
        else:
            primary = "System compound-risk: " + "; ".join(bits)
    else:
        has_meta = bool(feat.get("has_meta_flag"))
        if breadth == 0:
            primary = f"{scope} nominal — no correlated cross-module degradation"
        elif breadth == 1:
            if has_meta:
                primary = (f"{scope}: {modules[0]} raised an explicit cross-module escalation "
                           f"(→ meta) — coordinated pattern (e.g. aisle-wide comms), watch for compounding")
            else:
                primary = f"{scope}: single-subsystem issue ({modules[0]}) — not a compound incident (see that module)"
        else:
            chain = f"; realized chain {_chain_str(edges)}" if edges else ""
            primary = (f"Compound incident on {scope}: {breadth} subsystems degraded "
                       f"({', '.join(modules)}; worst {worst}){chain}")

    # one drill-down flag per involved module (worst member first).
    cross: List[Dict[str, str]] = []
    seen = set()
    for m in members:
        mod = m.get("module")
        if mod and mod not in seen:
            seen.add(mod)
            cross.append({"module": mod,
                          "reason": f"{scope}: {m.get('component_id')} {m.get('risk_tier')} — {m.get('primary_cause')}"})

    rca = {
        "summary": primary,
        "entity": "incident_scope",
        "scope": scope,
        "scope_kind": kind,
        "contributors": contributors,
        "breadth": breadth,
        "flagged_modules": modules,
        "worst_flagged_tier": worst,
        "chain_edges": edges,
        "chain": _chain_str(edges),
        "flagged_members": members,
        "consecutive_compound": consec_compound,
        "controller_tier": feat.get("controller_tier") if kind == "system" else None,
        "compound_aisles": feat.get("compound_aisles") if kind == "system" else None,
        "cross_module_flags": cross,
    }
    return primary, rca
