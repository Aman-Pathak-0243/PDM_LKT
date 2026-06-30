"""LIFT module — self-registers a :class:`PdMModule` on import.

Delegates the pipeline to the SOP files: fetch.py → features.py → health.py
(which calls rca.py). Tunables live in module.yaml (loaded via spec.py).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.lift.features import compute_features as _compute_features
from modules.lift.fetch import fetch as _fetch
from modules.lift.health import score as _score
from modules.lift.spec import spec


class LiftModule(PdMModule):
    name = "lift"
    title = "Lift PdM"
    component_type = "lift"
    description = (
        "Predictive maintenance for ASRS lifts from per-lift error rate, severity, "
        "recurrence, peer deviation, current status, and load context."
    )

    methodology = {
        "summary": (
            "Each lift is scored from its fault events over the analysis window — how "
            "often it faults, how serious those faults are, whether the same fault keeps "
            "recurring, and how it compares to peer lifts. There is no cycle counter for "
            "lifts, so faults are normalised by time (per active day) rather than by usage."
        ),
        "signals": [
            {"name": "Error rate", "source": "Lift Error History",
             "what": "Faults per day over the window (time-normalised intensity)."},
            {"name": "Peer deviation", "source": "all 16 lifts",
             "what": "Robust z-score of error rate vs the peer median."},
            {"name": "Severity & mechanical share", "source": "error_code catalog",
             "what": "Motor/brake/belt/axis/roller faults weigh heaviest (physical wear)."},
            {"name": "Recurrence & diversity", "source": "Lift Error History",
             "what": "Same code repeating, and how many distinct fault types appear."},
            {"name": "Current status", "source": "Bad Tracker Diagnosis",
             "what": "Whether the lift is currently reporting ERROR."},
            {"name": "Load context", "source": "Lift Error Analysis",
             "what": "Per-lift task counts as a relative load/wear indicator."},
        ],
        "entity_verdict": [
            "Anchor the window to the latest available data and count this lift's faults.",
            "Start at health 100 and subtract capped penalties: peer-relative rate, absolute "
            "rate, severity, mechanical share, recurrence, fault diversity, and current ERROR.",
            "Map the score to a tier: ok ≥85, watch 65–85, warn 40–65, critical <40.",
            "Estimate time-to-maintenance: cold-start → a coarse band by tier (low confidence); "
            "trend (≥5 snapshots) → project the health trajectory's slope (higher confidence).",
            "Attribute root cause: rank the contributing penalties and name the dominant error.",
        ],
        "formulas": [
            {"name": "error_rate_per_day", "formula": "error_count / window_days"},
            {"name": "rate_peer_z", "formula": "(rate − median_rate) / (1.4826 · MAD)"},
            {"name": "health", "formula": "clamp(100 − Σ capped_penalties, 0, 100)"},
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


register(LiftModule())
