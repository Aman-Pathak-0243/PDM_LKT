"""SHUTTLE module — self-registers a :class:`PdMModule` on import.

Pipeline: fetch.py -> features.py -> health.py (calls rca.py). Tunables in
module.yaml (via spec.py). Exploits cycle data for usage-normalised faults and a
cycles-based RUL.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.shuttle.features import compute_features as _compute_features
from modules.shuttle.fetch import fetch as _fetch
from modules.shuttle.health import score as _score
from modules.shuttle.spec import spec


class ShuttleModule(PdMModule):
    name = "shuttle"
    title = "Shuttle PdM"
    component_type = "shuttle"
    description = (
        "Predictive maintenance for ASRS shuttles from errors normalised by cycles "
        "(errors/Mcycle), severity, recurrence, reshuffle load, peer deviation, and "
        "current status — with a cycles-based RUL as run history accumulates."
    )

    # How verdicts are reached (rendered on the module page + served via API).
    methodology = {
        "summary": (
            "Each shuttle is scored from its fault events normalised by how much work "
            "it has done (errors per million cycles), so a busy shuttle is judged fairly "
            "against its usage. Cumulative cycles also drive a cycles-based remaining-"
            "useful-life estimate once enough run history exists."
        ),
        "signals": [
            {"name": "Errors per Mcycle", "source": "QUADRON ERROR HISTORY ÷ QUADRON CYCLES",
             "what": "Usage-normalised fault rate — the primary tiering signal."},
            {"name": "Error severity & mechanical share", "source": "error_type/error_desc catalog",
             "what": "Fork/telescope/servo faults weigh heaviest (physical wear)."},
            {"name": "Recurrence", "source": "QUADRON ERROR HISTORY",
             "what": "Same fault repeating = degradation, not a one-off."},
            {"name": "Reshuffle load", "source": "QUADRON CYCLES (RESHUFFLING/TOTAL)",
             "what": "Excess reshuffles vs fleet = added stress."},
            {"name": "Peer deviation", "source": "fleet of 124 shuttles",
             "what": "Robust z-score of errors/Mcycle vs the fleet median."},
            {"name": "Current status", "source": "Daily Shuttle Errors, Bad Tracker, Quadron Alerts",
             "what": "Live errors, SHUTTLE_PICK_ERROR recurrence, and active alerts."},
        ],
        "entity_verdict": [
            "Anchor the error window to the latest available data, then count this shuttle's faults.",
            "Normalise by cumulative cycles → errors per million cycles (epc).",
            "Start at health 100 and subtract capped penalties: peer-relative epc, absolute epc, "
            "severity, mechanical share, recurrence, fault diversity, reshuffle excess, and current "
            "status (bad-tracker/alert/today's errors).",
            "Map the score to a tier: ok ≥85, watch 65–85, warn 40–65, critical <40.",
            "Estimate time-to-maintenance: cold-start → a coarse band by tier (low confidence); "
            "trend (≥5 snapshots) → fit health vs cumulative cycles for cycles-to-threshold, then "
            "convert to hours via the recent cycle-accrual rate (higher confidence).",
            "Attribute root cause: rank the contributing penalties and name the dominant fault.",
        ],
        "formulas": [
            {"name": "errors_per_mcycle", "formula": "error_count / total_cycles × 1,000,000"},
            {"name": "reshuffle_share", "formula": "RESHUFFLING / (PUTAWAY+PICKING+RESHUFFLING)"},
            {"name": "health", "formula": "clamp(100 − Σ capped_penalties, 0, 100)"},
            {"name": "RUL (trend)", "formula": "cycles_to_critical / cycle_accrual_rate(cycles per hour)"},
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


register(ShuttleModule())
