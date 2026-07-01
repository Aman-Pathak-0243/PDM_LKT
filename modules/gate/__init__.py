"""GATE / Door-actuator module — self-registers a :class:`PdMModule` on import.

Pipeline: fetch.py -> features.py -> health.py (calls rca.py). Tunables in module.yaml
(via spec.py). This is a current-state + latency + recurrence module: the component is
each physical gate (aisle_<NN>_level_<NN>_<FG|RG>), and a degrading door ACTUATOR gets
caught/stuck non-closed — in OPEN REQUEST INITIATED (issued an open it can't complete) or
stuck OPEN (won't return to closed) — with a growing response latency and cross-run
persistence that the store accumulates.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.gate.features import compute_features as _compute_features
from modules.gate.fetch import fetch as _fetch
from modules.gate.health import score as _score
from modules.gate.spec import spec


class GateModule(PdMModule):
    name = "gate"
    title = "Gate / Door-Actuator PdM"
    component_type = "gate"
    description = (
        "Predictive maintenance for ASRS Quadron gates (door actuators; front + rear gate "
        "per aisle+level) from each gate's open/close state, how long it is stuck non-closed "
        "(response latency), and cross-run non-closed/stuck persistence + peer deviation."
    )

    methodology = {
        "summary": (
            "Each component is a physical GATE (e.g. aisle_02_level_01_FG — the front-gate "
            "actuator at aisle 2, level 1). A healthy gate rests CLOSED and opens only briefly "
            "during operation; a degrading actuator gets caught or stuck NON-CLOSED — either in "
            "OPEN REQUEST INITIATED (it was told to open but can't complete) or stuck OPEN (it "
            "won't return to closed). We score every gate each run from its current status, how "
            "many minutes it has been stuck (response latency), and — from the accumulated store "
            "— how persistently and how often it is non-closed compared to its own past and to "
            "peer gates."
        ),
        "signals": [
            {"name": "Stuck latency", "source": "Quadron Alerts #2 (gate messages)",
             "what": "Minutes a non-closed gate has been stuck (from gate.updated_timestamp) beyond a short grace — the actuator response-latency signal."},
            {"name": "Mid-actuation", "source": "Quadron-gate-status #2 (status)",
             "what": "Caught in OPEN REQUEST INITIATED — an open was issued but the gate has not reached OPEN."},
            {"name": "Persistence", "source": "the accumulated store",
             "what": "How many consecutive PdM runs the gate has stayed non-closed (not returning to CLOSED)."},
            {"name": "Stuck recurrence", "source": "the accumulated store",
             "what": "How many prior runs this gate was stuck — repeated actuator hesitation over time."},
            {"name": "Non-closed rate & peer deviation", "source": "the accumulated store + all 52 gates",
             "what": "Fraction of runs the gate is non-closed, and its robust z-score vs peer gates (once enough history exists)."},
        ],
        "entity_verdict": [
            "Fetch the current state of all 52 gates (id, status, aisle) — a current-state panel.",
            "For any non-closed gate, read its stuck-minutes from the Quadron Alerts message (response latency).",
            "Read this gate's history from the store: consecutive non-closed runs, prior stuck runs, non-closed rate.",
            "Start at health 100 and subtract capped penalties: stuck latency, mid-actuation, consecutive persistence, "
            "stuck recurrence, non-closed rate, and peer deviation (rate/peer only after enough runs accrue).",
            "Map the score to a tier: ok >=85, watch 65-85, warn 40-65, critical <40.",
            "Estimate time-to-maintenance: cold-start => a coarse band by tier; trend (>=5 runs) => project the gate's "
            "health trajectory over time (higher confidence).",
            "Attribute root cause and raise a cross-module flag when a whole aisle's gates are non-closed at once "
            "(possible zone-controller / comms common cause).",
        ],
        "formulas": [
            {"name": "stuck_excess_minutes", "formula": "max(stuck_minutes - grace, 0)"},
            {"name": "non_closed_rate", "formula": "prior runs non-closed / runs observed"},
            {"name": "consecutive_non_closed", "formula": "consecutive most-recent runs (incl. now) with status != CLOSED"},
            {"name": "health", "formula": "clamp(100 - Σ capped_penalties, 0, 100)"},
        ],
        "notes": [
            "The Gate-status panel is current-state (52 rows unchanged across windows); the store overcomes the "
            "2-day retention by snapshotting gate state each run so persistence/recurrence accrue over time.",
            "Every gate is scored each run (fixed 52-gate roster) — unlike the tracker's dynamic anomaly set.",
            "Being OPEN briefly is normal operation and is not penalised; the signal is being stuck non-closed "
            "(high latency) or persistently/repeatedly non-closed across runs.",
            "QUADRON ERROR HISTORY carries no gate column (it is shuttle_error) so it is not a gate source; the "
            "Quadron Alerts panel is shared with the Shuttle module (Gate parses only the front_gate/rear_gate messages).",
        ],
    }

    def default_window(self, cfg: Optional[Config] = None) -> str:
        return spec().get("default_window") or super().default_window(cfg)

    def fetch(self, session, window: str) -> FetchBundle:
        return _fetch(session, window)

    def compute_features(self, bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
        return _compute_features(bundle)

    def score(self, features: Dict[str, Dict[str, Any]], history: HistoryReader) -> List[ComponentHealth]:
        return _score(features, history)


register(GateModule())
