"""SYSTEM-WIDE ANOMALY (META) feature extraction — correlate the store into per-scope incidents.

Scopes = the observed ASRS aisles (from the authoritative metrics_json.aisle) + one 'system' scope.
For each scope we compute the CROSS-MODULE correlation signals (not a re-tally of member health):

  breadth        = number of DISTINCT modules with a flagged (tier != ok) component in the scope
  worst_tier     = worst flagged member tier in the scope
  chain_edges    = realized causal edges: a flagged member whose rca.cross_module_flags names a target
                   module that is ALSO flagged in the same scope (e.g. network->shuttle both flagged on
                   an aisle) -> strong evidence of a common cause, not ten unrelated flags
  meta_signals   = flagged members carrying an explicit '-> meta' flag (controller system-wide throttle,
                   network aisle-downtime cluster)
The 'system' scope additionally carries controller_tier + compound_aisle_count (how many aisles are
themselves compound incidents -> a systemic pattern). Every feature is documented in the README.
"""

from __future__ import annotations

from typing import Any, Dict, List

from core.logging_setup import get_logger
from core.registry import FetchBundle, RISK_TIERS, tier_rank

log = get_logger("meta.features")

_SYSTEM = "system"
# real module names a cross_module_flag can name as a realized chain target (excludes the pseudo
# targets 'meta' / 'corroboration' / 'gtp_scanner', which are handled separately or are not modules).
_MODULE_NAMES = {"lift", "shuttle", "conveyor", "tracker", "gate", "bin_mech",
                 "gtp_station", "decant_station", "network", "controller"}


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _scope_of(comp: Dict[str, Any]) -> str:
    """A component maps to its ASRS aisle iff it carries an authoritative metrics_json.aisle
    (lift/shuttle/tracker/gate/bin_mech/network + decant infeed diverters); else the system scope."""
    aisle = (comp.get("metrics") or {}).get("aisle")
    if aisle and str(aisle).strip().lower().startswith("aisle"):
        return str(aisle).strip()
    return _SYSTEM


def _flag_targets(comp: Dict[str, Any]) -> List[str]:
    flags = (comp.get("rca") or {}).get("cross_module_flags") or []
    out = []
    for f in flags:
        if isinstance(f, dict) and f.get("module"):
            out.append(str(f["module"]))
    return out


def _worst_tier(tiers: List[str]) -> str:
    return min(tiers, key=tier_rank) if tiers else "ok"


def _correlate(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cross-module correlation signals for one scope's members."""
    flagged = [m for m in members if (m.get("risk_tier") or "ok").lower() != "ok"]
    flagged_modules = sorted({m["module"] for m in flagged})

    # realized causal chain edges: flagged member -> a flagged target module in the same scope.
    edges: List[Dict[str, str]] = []
    seen_edges = set()
    has_meta_flag = False
    for m in flagged:
        for tgt in _flag_targets(m):
            if tgt == "meta":
                has_meta_flag = True
            if tgt in _MODULE_NAMES and tgt != m["module"] and tgt in flagged_modules:
                key = (m["module"], tgt)
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append({"from": m["module"], "to": tgt,
                                  "from_component": m.get("component_id")})

    worst = _worst_tier([(m.get("risk_tier") or "ok").lower() for m in flagged])
    # compact per-member summary (worst-first) for the RCA / incident view.
    summary = sorted(
        [{"module": m["module"], "component_id": m.get("component_id"),
          "risk_tier": (m.get("risk_tier") or "ok").lower(),
          "health_score": round(_num(m.get("health_score"), 100.0), 1),
          "primary_cause": (m.get("primary_cause") or "")[:160]} for m in flagged],
        key=lambda d: (tier_rank(d["risk_tier"]), d["health_score"]))
    return {
        "member_count": len(members),
        "flagged_count": len(flagged),
        "flagged_modules": flagged_modules,
        "breadth": len(flagged_modules),
        "worst_flagged_tier": worst,
        "worst_flagged_health": round(min([_num(m.get("health_score"), 100.0) for m in flagged], default=100.0), 1),
        "chain_edges": edges,
        "chain_edge_count": len(edges),
        "has_meta_flag": has_meta_flag,
        "flagged_members": summary,
    }


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    components: List[Dict[str, Any]] = bundle.frames.get("components", []) or []
    window = bundle.notes.get("window")

    # partition into scopes
    by_scope: Dict[str, List[Dict[str, Any]]] = {}
    for c in components:
        by_scope.setdefault(_scope_of(c), []).append(c)

    aisles = sorted([s for s in by_scope if s != _SYSTEM])
    # aisle roster is dynamic (observed aisles); system is always present.
    feats: Dict[str, Dict[str, Any]] = {}

    aisle_corr: Dict[str, Dict[str, Any]] = {}
    for aisle in aisles:
        corr = _correlate(by_scope.get(aisle, []))
        aisle_corr[aisle] = corr
        feats[aisle] = {
            "component_id": aisle,
            "component_type": "incident_scope",
            "scope_kind": "aisle",
            "scope": aisle,
            "window": window,
            **corr,
        }

    # system scope: non-aisle members + controller + breadth of compound aisles.
    sys_members = by_scope.get(_SYSTEM, [])
    sys_corr = _correlate(sys_members)
    controller_tier = "ok"
    for m in sys_members:
        if m["module"] == "controller":
            controller_tier = (m.get("risk_tier") or "ok").lower()
            break
    compound_aisles = sorted([a for a, c in aisle_corr.items() if c["breadth"] >= 2])
    feats[_SYSTEM] = {
        "component_id": _SYSTEM,
        "component_type": "incident_scope",
        "scope_kind": "system",
        "scope": _SYSTEM,
        "window": window,
        "controller_tier": controller_tier,
        "compound_aisle_count": len(compound_aisles),
        "compound_aisles": compound_aisles,
        **sys_corr,
    }

    log.info("meta features computed",
             extra={"aisles": len(aisles), "scopes": len(feats),
                    "compound_aisles": len(compound_aisles),
                    "controller_tier": controller_tier,
                    "components_correlated": len(components)})
    return feats
