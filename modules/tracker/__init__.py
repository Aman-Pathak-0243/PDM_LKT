"""TRACKER / Position-Sensor module — self-registers a :class:`PdMModule` on import.

Pipeline: fetch.py -> features.py -> health.py (calls rca.py). Tunables in module.yaml
(via spec.py). This is an anomaly/recurrence module: the component is the grid
``location`` (the fixed position sensor / tracker reader), and bad-tracker events that
cluster on the same location — and recur across runs — signal a pre-failing sensor.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.tracker.features import compute_features as _compute_features
from modules.tracker.fetch import fetch as _fetch
from modules.tracker.health import score as _score
from modules.tracker.spec import spec


class TrackerModule(PdMModule):
    name = "tracker"
    title = "Tracker / Position-Sensor PdM"
    component_type = "position_sensor"
    description = (
        "Predictive maintenance for ASRS grid position sensors / tracker readers, from "
        "bad-tracker events that cluster on the same grid location — cluster size, recency, "
        "breadth of affected robots, peer deviation, and cross-run recurrence/persistence."
    )

    methodology = {
        "summary": (
            "Each component is a grid LOCATION (e.g. aisle_03_bt_10) — the fixed position "
            "sensor / tracker reader installed at that cell. When the system loses track of a "
            "tote, the tote's tracker tag sticks at an anomalous location: a 'bad tracker' "
            "event. A healthy sensor produces isolated one-offs; a degrading one accumulates a "
            "CLUSTER of mislocated totes at the same location and keeps recurring across runs. "
            "The tracker tag itself is per-tote (unique per event, no recurrence), so the "
            "location — not the tag — is the unit that physically degrades and is scored."
        ),
        "signals": [
            {"name": "Cluster size", "source": "Bad Tracker Diagnosis #2",
             "what": "How many totes are currently mislocated at this grid location (the core signal)."},
            {"name": "Recency (active vs stale)", "source": "Bad Tracker Diagnosis #2 (created_time)",
             "what": "Totes stuck recently (within the window) weigh more than long-abandoned ones."},
            {"name": "Cross-run recurrence", "source": "the accumulated store",
             "what": "How many prior PdM runs flagged this same location — the longitudinal signal."},
            {"name": "Robot breadth", "source": "Bad Tracker Diagnosis #2 (shuttle_id/lift_id)",
             "what": "Many distinct shuttles failing at one location => the position is the common cause."},
            {"name": "Peer deviation", "source": "all bad locations",
             "what": "Robust z-score of this location's cluster size vs peer locations."},
        ],
        "entity_verdict": [
            "Fetch the current bad-tracker set (one row per mislocated tote: tracker tag, location, "
            "created_time, the shuttle/lift that errored on it).",
            "Group by grid location and measure the cluster: total stuck totes, how many are recent, "
            "distinct shuttles affected, lift involvement, and age.",
            "Read this location's history from the store to count cross-run recurrence.",
            "Start at health 100 and subtract capped penalties: cluster size, recent cluster, "
            "recurrence across runs, multiple shuttles, lift-in-ERROR, and peer-relative cluster.",
            "Map the score to a tier: ok ≥85, watch 65–85, warn 40–65, critical <40.",
            "Estimate time-to-maintenance: cold-start => coarse band by tier; trend (≥5 runs) => "
            "project the location's health trajectory over time (higher confidence).",
            "Attribute root cause and raise cross-module flags (one shuttle dominating => Shuttle; "
            "lift in ERROR => Lift).",
        ],
        "formulas": [
            {"name": "bad_count", "formula": "count of mislocated totes currently at the location"},
            {"name": "recurrence_runs", "formula": "number of prior PdM runs that flagged this location"},
            {"name": "health", "formula": "clamp(100 − Σ capped_penalties, 0, 100)"},
        ],
        "notes": [
            "The Bad Tracker panel is current-state (the dashboard window does not filter it); the "
            "store overcomes the 2-day retention by snapshotting bad locations each run so recurrence "
            "accrues over time.",
            "Only locations with active bad-tracker events are scored — absence of a location means it "
            "is healthy (standard anomaly-detection semantics).",
            "Aggregate Error Report carries no tracker/location field (it is shuttle+lift errors keyed "
            "by robot_id), so it is not a tracker source — it is covered by the Shuttle + Lift modules.",
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


register(TrackerModule())
