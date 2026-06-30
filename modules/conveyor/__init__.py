"""CONVEYOR module — self-registers a :class:`PdMModule` on import.

Pipeline: fetch.py -> features.py -> health.py (calls rca.py). Tunables in
module.yaml (via spec.py). Health is a per-zone congestion model (no cycle counter,
no discrete fault events in Grafana for conveyor).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.conveyor.features import compute_features as _compute_features
from modules.conveyor.fetch import fetch as _fetch
from modules.conveyor.health import score as _score
from modules.conveyor.spec import spec


class ConveyorModule(PdMModule):
    name = "conveyor"
    title = "Conveyor PdM"
    component_type = "zone"
    description = (
        "Predictive maintenance for GTP conveyor zones (belts/motors/diverters) from "
        "per-zone congestion — queue depth vs limit, severe-saturation share, peak backups, "
        "buffer fill, and peer deviation."
    )

    methodology = {
        "summary": (
            "Each conveyor zone is scored from how backed-up it runs. A healthy belt clears "
            "totes (queue near or below its limit); a worn/jamming belt, motor, or diverter "
            "lets the queue build above the limit, spike to extreme peaks, and back up into "
            "its buffer. There is no discrete conveyor 'jam event' feed in Grafana, so "
            "congestion — the observable symptom — is the signal."
        ),
        "signals": [
            {"name": "Congestion (actual/limit)", "source": "Conveyor Zone Count",
             "what": "Queue depth vs the zone's limit over the window — the core signal."},
            {"name": "Severe saturation", "source": "Conveyor Zone Count",
             "what": "Share of time the queue runs ≥ the severe ratio (default 1.5× limit)."},
            {"name": "Peak backup", "source": "Conveyor Zone Count",
             "what": "Worst spike (max actual/limit) — extreme stalls."},
            {"name": "Buffer fill", "source": "Conveyor Zone Count (buffer_*)",
             "what": "Buffer filling means downstream isn't clearing — a stronger jam sign."},
            {"name": "Peer deviation", "source": "the 6 zones",
             "what": "Robust z-score of mean congestion vs peer zones."},
        ],
        "entity_verdict": [
            "Pull each zone's queue (conveyor_actual) and limit (conveyor_limit) over the window.",
            "Compute mean/peak/p90 congestion = actual ÷ limit, the severe-saturation share, and buffer fill.",
            "Start at health 100 and subtract capped penalties: congestion above 1.0×, severe-saturation "
            "share, peak above the reference, buffer fill, and peer-relative congestion.",
            "Map the score to a tier: ok ≥85, watch 65–85, warn 40–65, critical <40.",
            "Estimate time-to-maintenance: cold-start → coarse band by tier; trend (≥5 snapshots) → "
            "project the zone's health trajectory over time (higher confidence).",
            "Attribute root cause: rank the contributing penalties and describe the backup.",
        ],
        "formulas": [
            {"name": "congestion", "formula": "conveyor_actual_count / conveyor_limit_count"},
            {"name": "severe_saturation_share", "formula": "fraction of samples with congestion ≥ 1.5"},
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


register(ConveyorModule())
