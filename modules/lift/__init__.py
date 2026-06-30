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

    def default_window(self, cfg: Optional[Config] = None) -> str:
        return spec().get("default_window") or super().default_window(cfg)

    def fetch(self, session, window: str) -> FetchBundle:
        return _fetch(session, window)

    def compute_features(self, bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
        return _compute_features(bundle)

    def score(self, features: Dict[str, Dict[str, Any]], history: HistoryReader) -> List[ComponentHealth]:
        return _score(features, history)


register(LiftModule())
