"""GTP STATION + SCANNER module — self-registers a :class:`PdMModule` on import.

Pipeline: fetch.py -> features.py -> health.py (calls rca.py). Tunables in module.yaml
(via spec.py). This module scores TWO physical component types:

  * gtp_scanner  — a barcode scan device (272 this snapshot: pick-station slot scanners
    GS<NN>-SL<NN>, inbound scanners, GTP/zone/compaction scanners, diverters). Signal =
    misread rate = NoReadCount / (ReadCount + NoReadCount) per scanner over the window.
  * gtp_station  — a GTP pick station (63: GS001..GS063). Signal = per-station
    pick-verification discrepancy rate + peer deviation + cross-run recurrence/trend, with
    active/inactive status as context.

A degrading scanner reads fewer barcodes (rising no-reads); a degrading station's pick
verification throws more discrepancies. The two corroborate for pick-station scanners.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.gtp_station.features import compute_features as _compute_features
from modules.gtp_station.fetch import fetch as _fetch
from modules.gtp_station.health import score as _score
from modules.gtp_station.spec import spec


class GtpStationModule(PdMModule):
    name = "gtp_station"
    title = "GTP Station + Scanner PdM"
    component_type = "station/scanner"
    description = (
        "Predictive maintenance for GTP pick stations and barcode scanners. Scanner health is "
        "inferred from per-scanner misread rate (NoRead/(Read+NoRead)); station health from the "
        "per-station pick-verification discrepancy rate, peer deviation, and cross-run "
        "recurrence/trend, with active/inactive status as context."
    )

    methodology = {
        "summary": (
            "This module scores two physical component types. A SCANNER (barcode scan device) is "
            "scored from its misread rate = NoRead / (Read + NoRead): a healthy scanner reads nearly "
            "every barcode (fleet median 0.3% misread), while a dirty/failing/mis-aimed scanner's "
            "no-read rate climbs. A STATION (GTP pick station) is scored from its pick-verification "
            "discrepancy rate: mainly how far its discrepancies/day sit above peer stations (isolating "
            "station-specific degradation from plant-wide inventory shorts), plus a very-high absolute "
            "rate, cross-run recurrence, and a low-weight offline-persistence signal. The pick-station "
            "scanner is the GS<NN>-SL<NN> device, so a station's discrepancy climb and its scanner's "
            "misread climb corroborate each other (the RCA cross-links them)."
        ),
        "signals": [
            {"name": "Scanner misread rate", "source": "GTP Scanner logs #8 (Read/NoRead)",
             "what": "NoReadCount/(ReadCount+NoReadCount) per scanner — the core scanner-degradation signal."},
            {"name": "Scan volume", "source": "GTP Scanner logs #8 total + #4 hits",
             "what": "Usage per scanner — scales the misread penalty + confidence (few scans = noisy rate)."},
            {"name": "Scanner peer deviation", "source": "the scanner fleet",
             "what": "Robust z of misread% vs peer scanners with enough volume (within-snapshot)."},
            {"name": "Station discrepancy rate", "source": "Discrepancy Report Events #2 (verification_events)",
             "what": "Per-station pick-verification discrepancies/day (EMPTY_SUPPLY_CONTAINER_CONFIRM / SHORT)."},
            {"name": "Station peer deviation", "source": "the verifying stations",
             "what": "Robust z of discrepancies/day vs peer stations — the dominant station penalty."},
            {"name": "Active/Inactive status", "source": "GTP Stations #2 (active_status)",
             "what": "Context (many stations legitimately Inactive) + a low-weight offline-persistence signal from the store."},
            {"name": "Cross-run recurrence / trend", "source": "the accumulated store",
             "what": "Prior runs a scanner/station read elevated; the health trajectory over runs (trend RUL)."},
        ],
        "entity_verdict": [
            "SCANNER: pull per-scanner ReadCount/NoReadCount over the window; misread% = NoRead/(Read+NoRead).",
            "SCANNER: start at 100 and subtract capped penalties — misread% (scaled by scan volume), "
            "peer-z vs the fleet, and cross-run recurrence (prior runs elevated).",
            "STATION: count per-station discrepancies over the window -> discrepancies/day; read active_status.",
            "STATION: start at 100 and subtract capped penalties — peer-z of discrepancies/day (dominant), "
            "very-high absolute rate, cross-run recurrence, and consecutive-Inactive persistence (low weight).",
            "Map the score to a tier: ok >=85, watch 65-85, warn 40-65, critical <40.",
            "Estimate time-to-maintenance: cold-start => a coarse band by tier; trend (>=5 runs) => project "
            "the component's health trajectory over time (higher confidence).",
            "Cross-link a flagged station to its flagged slot scanner (GS<NN>-SL<NN>) as a same-cause corroboration.",
        ],
        "formulas": [
            {"name": "misread_rate", "formula": "NoReadCount / (ReadCount + NoReadCount)"},
            {"name": "volume_factor", "formula": "min(1, total_scans / min_volume_full)"},
            {"name": "discrepancy_per_day", "formula": "discrepancy_count / window_days"},
            {"name": "health", "formula": "clamp(100 − Σ capped_penalties, 0, 100)"},
        ],
        "notes": [
            "GTP Scanner logs #8 and Discrepancy Report Events #2 are time-FILTERED, so a wider window "
            "sharpens the misread/discrepancy rates (unlike the current-state Gate/Bin panels). GTP Stations "
            "#2 is a current roster snapshot (63 stations regardless of window).",
            "Absolute discrepancy counts are partly inventory-driven (plant-wide SHORTs), so the station model "
            "leans on peer deviation + recurrence to isolate station-specific degradation; a very-high absolute "
            "rate adds a smaller penalty.",
            "active_status is context, not a hard fault (14 of 63 stations were Inactive this snapshot). Only "
            "persistent Inactivity across consecutive runs adds a small penalty; the future true-downtime signal "
            "is GTP Stations #6 (minutes a tote has sat inside a station — a gauge, no CSV yet).",
            "decant_* / Compaction_* scan devices appear in the GTP scanner feed but belong to the Decanting "
            "Station (Module 8) / compaction line — scored here and tagged by subtype so Module 8 can reconcile.",
            "GTP Station Information + Live GTP Summary were dropped (pendency/inventory, not health); GTP "
            "Throughput v2 is a documented future secondary (trend already accrues in our store).",
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


register(GtpStationModule())
