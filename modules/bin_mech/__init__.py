"""BIN / TOTE-MECHANICAL module — self-registers a :class:`PdMModule` on import.

Pipeline: fetch.py -> features.py -> health.py (calls rca.py). Tunables in module.yaml
(via spec.py). This is an anomaly/recurrence module: the component is the grid bin
LOCATION (slot), and bin-block (tote-tilt) events that stay unresolved, cluster, or recur
at the same slot — across the frozen history and across our runs — signal a degrading
slot/rail rather than a random block.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.bin_mech.features import compute_features as _compute_features
from modules.bin_mech.fetch import fetch as _fetch
from modules.bin_mech.health import score as _score
from modules.bin_mech.spec import spec


class BinMechModule(PdMModule):
    name = "bin_mech"
    title = "Bin / Tote-Mechanical PdM"
    component_type = "bin_location"
    description = (
        "Predictive maintenance for ASRS storage bin slots / rails from bin-block (tote-tilt) "
        "events — how long a block stays unresolved (block-age), how many totes are blocked at "
        "the slot now, the slot's historical block frequency, and cross-run recurrence/persistence."
    )

    methodology = {
        "summary": (
            "Each component is a physical bin LOCATION (slot address like 001-14-1-119-1-02 = "
            "Aisle-Level-Rack-Location-Deep). A 'bin block' (tote tilt) is a tote that won't seat / "
            "is stuck at a slot. A healthy slot blocks a tote rarely and briefly; a degrading "
            "slot/rail blocks totes repeatedly, keeps a block unresolved for a long time, and recurs "
            "at the SAME location. We score the currently-blocked slots from how long the block has "
            "sat (block-age), how many totes are blocked there now, the slot's historical block "
            "frequency, and — the strongest live signal as it accrues — how many prior PdM runs "
            "flagged the same slot."
        ),
        "signals": [
            {"name": "Block-age", "source": "Bin blocked / tote-tilted #2 (blockedTime)",
             "what": "How long the tote has stayed blocked/unresolved at this slot — a stuck block, not a transient."},
            {"name": "Current cluster", "source": "Bin blocked / tote-tilted #2",
             "what": "How many totes are blocked at this same slot right now."},
            {"name": "Historical block frequency", "source": "Bin Block History #2 (frozen log)",
             "what": "How many times this slot blocked in the historical log — a chronic-slot fingerprint."},
            {"name": "Cross-run recurrence", "source": "the accumulated store",
             "what": "How many prior PdM runs flagged this same slot blocked — the longitudinal signal."},
            {"name": "Peer deviation", "source": "all currently-blocked slots",
             "what": "Robust z-score of this slot's block-age vs peer blocked slots."},
        ],
        "entity_verdict": [
            "Fetch the current set of blocked bins (bin_blocked status=0) and dedupe partition rows.",
            "Group by slot location and measure the block: how long it has been blocked (age), how many "
            "totes are blocked there now, distinct containers, aisle/level.",
            "Look up the slot's historical block frequency (frozen Bin Block History log) and read its "
            "history from the store for cross-run recurrence.",
            "Start at health 100 and subtract capped penalties: blocked-now (base), block-age, current "
            "cluster, historical chronic-slot frequency, cross-run recurrence, and peer-relative age.",
            "Map the score to a tier: ok >=85, watch 65-85, warn 40-65, critical <40.",
            "Estimate time-to-maintenance: cold-start => a coarse band by tier; trend (>=5 runs) => "
            "project the slot's health trajectory over time (higher confidence).",
            "Attribute root cause and raise a cross-module flag when many blocks concentrate on one aisle "
            "(that aisle's shuttle may be mis-seating totes → Shuttle; mislocation → Tracker).",
        ],
        "formulas": [
            {"name": "block_age_hours", "formula": "max(blockedTime) − this block's blockedTime (hours)"},
            {"name": "historical_block_count", "formula": "occurrences of this slot as SOURCE in the frozen block log"},
            {"name": "recurrence_runs", "formula": "number of prior PdM runs that flagged this slot blocked"},
            {"name": "health", "formula": "clamp(100 − Σ capped_penalties, 0, 100)"},
        ],
        "notes": [
            "The blocked-bin panel is current-state (the live bin_blocked table); the store overcomes the "
            "short retention by snapshotting blocked slots each run so recurrence accrues over time — so "
            "regular automation is what makes this module predictive.",
            "Only currently-blocked slots are scored — a slot with no active block is healthy (standard "
            "anomaly-detection semantics). A one-off fresh block stays near ok; recurrence/age/chronic drive risk.",
            "Bin Block History is FROZEN (2022-24) and barely overlaps current blocks, so it enriches "
            "cold-start / RCA (chronic-slot flag) rather than dominating; it is fetched best-effort.",
            "Aggregate Error Report carries no location (it is shuttle+lift errors keyed by robot_id), so it "
            "is not a bin source; Bin Blocked Statistics reads the same live table as tilted #2.",
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


register(BinMechModule())
