"""NETWORK / COMMS module — self-registers a :class:`PdMModule` on import.

Pipeline: fetch.py -> features.py -> health.py (calls rca.py). Tunables in module.yaml (via spec.py).
Single component type:

  * network_link — a per-SHUTTLE comms link (124: QD_Shuttle_<aisle>_<unit>, keyed by shuttle_id).
    Signal = network downtime% = 100 - uptime% (Quadron Network status, from shuttle_error rows with
    error_type='SHUTTLE_NETWORK_STATUS'). A healthy link is disconnected ~0-3% of the time; a flaky/
    degrading link's downtime% climbs. Scored on downtime peer deviation + absolute rate + a today-vs-
    window recency spike + cross-run recurrence/trend.

This is the "controller communication layer" observed per shuttle (the only granularity the data
provides). It is a CROSS-FEATURE: comms drops precede/cause shuttle pick/handling errors, so a flagged
link cross-links to the Shuttle module, and clustered downtime on an aisle raises an aisle AP/controller
flag for the future meta-module. It does NOT double-count the Shuttle module (a different error subset).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.network.features import compute_features as _compute_features
from modules.network.fetch import fetch as _fetch
from modules.network.health import score as _score
from modules.network.spec import spec


class NetworkModule(PdMModule):
    name = "network"
    title = "Network / Comms PdM"
    component_type = "network_link"
    description = (
        "Predictive maintenance for the controller communication layer, observed per shuttle. Each "
        "shuttle's comms link is scored from its network downtime% (100 - uptime%, from Quadron Network "
        "status / SHUTTLE_NETWORK_STATUS): peer deviation, absolute rate, a today-vs-window recency spike, "
        "and cross-run recurrence/trend. A cross-feature that precedes shuttle/lift operational errors."
    )

    methodology = {
        "summary": (
            "This module scores the per-shuttle COMMS LINK — the wireless channel between the controller "
            "and each shuttle (124 links, keyed by shuttle_id). The signal is network downtime% = 100 - "
            "uptime%, where uptime% comes from Quadron Network status: the fraction of window time each "
            "shuttle spent in a SHUTTLE_NETWORK_STATUS disconnect. A healthy link is disconnected only ~0-3% "
            "of the time (fleet median 3.25%); a flaky/degrading link's downtime% climbs (worst 29.7% this "
            "snapshot). A link starts at 100 and loses points for high absolute downtime, downtime far above "
            "the fleet (peer-z), a today-vs-window recency spike (degrading right now), and cross-run "
            "recurrence. This is a cross-feature: comms drops precede/cause shuttle pick errors, so a flagged "
            "link cross-links to the Shuttle module, and downtime clustering on one aisle raises an aisle "
            "AP/controller flag for the meta-module. It scores a DIFFERENT error subset than the Shuttle "
            "module (SHUTTLE_NETWORK_STATUS vs FORK/TELESCOPIC), so it does not double-count shuttle wear."
        ),
        "signals": [
            {"name": "Network downtime%", "source": "Quadron Network status #4 (windowed, ${Date}=window start)",
             "what": "100 - uptime% per shuttle link over the window — the core comms-degradation signal."},
            {"name": "Peer deviation", "source": "the shuttle-link fleet (124)",
             "what": "Robust z of downtime% vs peer links (within-snapshot), gated by a minimum absolute downtime."},
            {"name": "Today recency spike", "source": "Quadron Network status #2 (since midnight today)",
             "what": "Today's downtime% above a floor AND worse than the window average — the link is degrading NOW."},
            {"name": "Aisle clustering", "source": "per-aisle mean downtime",
             "what": "Downtime clustering on one aisle -> a candidate aisle AP/controller common cause (cross-feature)."},
            {"name": "Cross-run recurrence / trend", "source": "the accumulated store",
             "what": "Prior runs a link's downtime% was elevated; the health trajectory over runs (trend RUL)."},
        ],
        "entity_verdict": [
            "Pull per-shuttle uptime% over the window (#4 with ${Date}=window start); downtime% = 100 - uptime%.",
            "Join today's uptime% (#2) by shuttle_id to detect a link worse TODAY than its window average.",
            "Start at 100 and subtract capped penalties — absolute downtime above the fleet floor, peer-z vs "
            "the fleet (gated), a today-vs-window recency spike, and cross-run recurrence (prior runs elevated).",
            "Map the score to a tier: ok >=85, watch 65-85, warn 40-65, critical <40.",
            "Estimate time-to-maintenance: cold-start => a coarse band by tier; trend (>=5 runs) => project the "
            "link's health trajectory over time (higher confidence).",
            "Cross-link a flagged link to its SHUTTLE (comms drops precede pick errors) and, when downtime "
            "clusters on an aisle, raise an aisle AP/controller flag for the meta-module.",
        ],
        "formulas": [
            {"name": "uptime_pct", "formula": "(1 - SUM(disconnect_seconds) / elapsed_seconds) * 100  (SHUTTLE_NETWORK_STATUS)"},
            {"name": "downtime_pct", "formula": "100 - uptime_pct"},
            {"name": "today_delta", "formula": "today_downtime_pct - window_downtime_pct  (>0 = degrading now)"},
            {"name": "health", "formula": "clamp(100 - Sum(capped_penalties), 0, 100)"},
        ],
        "notes": [
            "Quadron Network status #4 is parameterised by a ${Date} var, so a wider window (${Date}=now-N) "
            "smooths the downtime average; #2 is scoped to today (recency). Both are live-computed from "
            "shuttle_error (error_type='SHUTTLE_NETWORK_STATUS').",
            "The mapping called this 'latency, packet loss, link state' — the live signal is actually per-shuttle "
            "uptime%/disconnect-duration (link state over time); there is no latency-ms or packet-loss-% metric.",
            "Component = the per-shuttle comms LINK, a different facet than the Shuttle module's mechanical wear "
            "(and a different error subset), so the two do not double-count; this module is the cross-feature "
            "counterpart to the '-> network' flags Lift (comm codes 3/4) and Shuttle (servo-drive) already emit.",
            "Downtime is partly environmental (RF interference, congestion), so the model leans on peer deviation "
            "+ recurrence + the today-vs-window spike to isolate a genuinely degrading link from fleet-wide noise.",
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


register(NetworkModule())
