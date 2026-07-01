"""SYSTEM-WIDE ANOMALY (META) module — self-registers a :class:`PdMModule` on import.

The FINAL module (Module 11). Unlike the ten equipment/infra modules it has NO Grafana source: it is a
correlation layer over the PdM store. Pipeline: fetch.py (reads the store) -> features.py (correlate into
per-scope incidents) -> health.py (compound-risk, calls rca.py). Tunables in module.yaml (via spec.py).

  * incident_scope — a correlation scope: each observed ASRS aisle (aisle_<NN>) + one 'system' scope.
    An aisle scope groups the flagged components (tier != ok) of every module that maps to that aisle
    (lift/shuttle/tracker/gate/bin_mech/network + decant infeed diverters, via metrics_json.aisle); the
    system scope groups the controller + non-aisle areas + a breadth-of-compound-aisles signal. Each is
    scored by COMPOUND-RISK: module co-occurrence + realized causal chains + persistence (NOT a re-tally
    of member health -> no double-count). Surfaces compound failures with a likely common cause.

is_configured() is overridden to True (no dashboards). Registered LAST so a "Run all" trigger correlates
the same trigger's fresh per-module results.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.meta.features import compute_features as _compute_features
from modules.meta.fetch import fetch as _fetch
from modules.meta.health import score as _score
from modules.meta.spec import spec


class MetaModule(PdMModule):
    name = "meta"
    title = "System-Wide Anomaly (Meta) PdM"
    component_type = "incident_scope"
    description = (
        "The system-wide anomaly layer. A correlation layer over the PdM store (no Grafana fetch): it "
        "reads the latest scored components of every other module and their cross-module flags, and "
        "correlates them by aisle (+ a system scope) into ranked compound-risk incidents — scoring "
        "module co-occurrence and realized causal chains, not a re-tally of member health."
    )

    methodology = {
        "summary": (
            "This is the meta-module: it does NOT read Grafana. It reads the PdM store — the latest scored "
            "component of every other module and each one's rca cross-module flags — and correlates them into "
            "compound-risk incidents. A component maps to an ASRS aisle via its authoritative metrics.aisle "
            "(lift/shuttle/tracker/gate/bin_mech/network + decant infeed diverters); everything else "
            "(controller, GTP, decant stations, conveyor) maps to a 'system' scope. Each scope (6 aisles + "
            "system) is scored by COMPOUND-RISK: how many DISTINCT modules are flagged in it (breadth), the "
            "worst flagged tier (severity, applied only when >=2 modules co-occur so a lone module is never "
            "re-flagged), realized causal CHAIN edges (a flagged member whose cross-module flag names another "
            "module that is ALSO flagged in the same scope), and cross-run PERSISTENCE. The system scope adds "
            "a controller-saturation trigger and a count of simultaneously-compound aisles. The point is to "
            "surface a likely COMMON CAUSE (e.g. controller saturation -> network downtime -> shuttle errors "
            "-> bin blocks on one aisle) as ONE ranked incident, instead of ten unrelated per-module flags — "
            "genuinely new information the individual modules cannot see, without double-counting them."
        ),
        "signals": [
            {"name": "Breadth (co-occurrence)", "source": "store: distinct modules flagged in the scope",
             "what": ">=2 modules flagged on the same aisle/scope = a compound incident (1 = the module's own problem)."},
            {"name": "Realized causal chain", "source": "store: rca.cross_module_flags of flagged members",
             "what": "An edge counts only when a flagged member names a target module that is ALSO flagged here (e.g. network->shuttle)."},
            {"name": "Severity", "source": "worst flagged tier in the scope",
             "what": "Amplifies a compound incident (applied only when breadth >= 2 — never manufactures one from a lone module)."},
            {"name": "Controller trigger + aisle breadth", "source": "system scope",
             "what": "A saturated controller is a system incident on its own; many simultaneously-compound aisles = a systemic common cause."},
            {"name": "Persistence", "source": "the accumulated meta store",
             "what": "Consecutive prior meta runs this scope was compound -> a sustained (not transient) compound incident."},
        ],
        "entity_verdict": [
            "Read the latest scored component of every other module from the store (excluding meta itself).",
            "Bucket each component into its scope: its ASRS aisle (metrics.aisle) or the 'system' scope.",
            "For each scope compute breadth (distinct flagged modules), worst tier, and realized chain edges "
            "(a flagged member -> a flagged target module named in its cross-module flags).",
            "Start at 100 and subtract capped penalties — breadth (beyond the first module), severity (only if "
            ">=2 modules), chain edges, persistence; the system scope adds controller-trigger + compound-aisle breadth.",
            "Map the score to a tier: ok >=85, watch 65-85, warn 40-65, critical <40 — ranked worst-first as incidents.",
            "Estimate time-to-maintenance: cold-start => a coarse band by tier; trend (>=5 runs) => project the "
            "scope's compound-risk trajectory over accumulated meta runs.",
        ],
        "formulas": [
            {"name": "breadth", "formula": "count(distinct modules with a flagged component in the scope)"},
            {"name": "chain_edge", "formula": "flagged member m -> target T iff T in m.rca.cross_module_flags AND T is also flagged in the scope"},
            {"name": "compound_incident", "formula": "breadth >= 2"},
            {"name": "health", "formula": "clamp(100 - Sum(capped_penalties), 0, 100)  [compound-risk, NOT a re-tally]"},
        ],
        "notes": [
            "NO Grafana fetch: every mapped §11 candidate (Aggregate Error Report, QUADRON ERROR HISTORY, "
            "Quadron Alerts, Quadron Network status, CPU Stats) is already owned by another module or was "
            "dropped as redundant (Aggregate Error Report = shuttle_error UNION lift_error, covered by "
            "Shuttle+Lift). Meta reads only the store, so it never double-counts a fetch.",
            "Compound-risk is NOT a sum of member health — a lone flagged module leaves the scope ok (that "
            "module owns it); meta only escalates when >=2 modules co-occur, and highest when a realized "
            "causal chain links them (a likely common cause).",
            "Aisle key = the authoritative metrics.aisle set by the source modules (not parsed from arbitrary "
            "component ids), so GTP/decant-station/conveyor/controller correctly fall to the system scope.",
            "Registered LAST, so on a 'Run all' trigger the other modules persist their fresh rows before meta "
            "correlates them; run solo, it correlates the most-recently-stored verdicts. Regular automation "
            "makes the persistence signal + trend RUL meaningful.",
        ],
    }

    # No Grafana source -> always 'configured' (it reads the store). Keeps it in Run-all + runnable solo
    # with no core/ changes (the plugin rule).
    def is_configured(self, cfg: Optional[Config] = None) -> bool:
        return True

    def default_window(self, cfg: Optional[Config] = None) -> str:
        return spec().get("default_window") or super().default_window(cfg)

    def fetch(self, session, window: str) -> FetchBundle:
        return _fetch(session, window)

    def compute_features(self, bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
        return _compute_features(bundle)

    def score(self, features: Dict[str, Dict[str, Any]], history: HistoryReader) -> List[ComponentHealth]:
        return _score(features, history)


register(MetaModule())
