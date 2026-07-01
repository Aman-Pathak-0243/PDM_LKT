"""DECANTING STATION + SCANNER module — self-registers a :class:`PdMModule` on import.

Pipeline: fetch.py -> features.py -> health.py (calls rca.py). Tunables in module.yaml
(via spec.py). This module scores TWO physical component types:

  * decant_scanner — a decant/compaction-line barcode scan device (9 this snapshot: 7
    aisle_0N_decant_diverter infeed scanners + 2 Compaction_scanner*). Signal = misread rate =
    NoReadCount / (ReadCount + NoReadCount) per device over the window. Reconciled from the GTP
    module in Session 8 (each device now owned by exactly one module).
  * decant_station — a decant operator station (10: DS001..DS010). NO live fault/discrepancy feed,
    so scored coarsely on active/inactive status + offline-persistence + an idle-while-active
    anomaly that escalates only when it persists across runs (store-driven), at low confidence.

A degrading scanner reads fewer barcodes (rising no-reads); a decant station with no live fault
feed can only be inferred from status + persistent idle-while-busy. The scanner is the strong signal.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.decant_station.features import compute_features as _compute_features
from modules.decant_station.fetch import fetch as _fetch
from modules.decant_station.health import score as _score
from modules.decant_station.spec import spec


class DecantStationModule(PdMModule):
    name = "decant_station"
    title = "Decanting Station + Scanner PdM"
    component_type = "station/scanner"
    description = (
        "Predictive maintenance for decant operator stations and decant/compaction-line barcode "
        "scanners. Scanner health is inferred from per-scanner misread rate (NoRead/(Read+NoRead)); "
        "decant stations have no live fault feed, so they are scored coarsely from active/inactive "
        "status, offline-persistence, and a persistent idle-while-active anomaly (low confidence)."
    )

    methodology = {
        "summary": (
            "This module scores two physical component types. A SCANNER (decant/compaction-line scan "
            "device) is scored from its misread rate = NoRead / (Read + NoRead): a healthy scanner reads "
            "nearly every barcode (decant diverters 0.01-0.17% misread), while a dirty/failing/mis-aimed "
            "scanner's no-read rate climbs (both compaction scanners ~4%). This is the strong live signal, "
            "reconciled from the GTP module (each device now owned by exactly one module). A STATION (decant "
            "operator station) has NO live per-station fault/discrepancy feed available in Grafana "
            "(discrepancy_details is a frozen 2022 drill-down with no station key), so it is scored coarsely "
            "and honestly: active/inactive status is context, and only offline-persistence (Inactive across "
            "consecutive runs) or a persistent idle-while-active anomaly (Active but decanting nothing while "
            "the line is busy, across consecutive runs) subtract points. A single idle/Inactive run adds "
            "nothing; station verdicts carry deliberately modest confidence."
        ),
        "signals": [
            {"name": "Scanner misread rate", "source": "GTP Scanner logs #8 (Read/NoRead), filtered to decant/compaction",
             "what": "NoReadCount/(ReadCount+NoReadCount) per decant/compaction device — the core, live scanner-degradation signal."},
            {"name": "Scan volume", "source": "GTP Scanner logs #8 total",
             "what": "Scans per device — scales the misread penalty + confidence (few scans = noisy rate)."},
            {"name": "Scanner peer deviation", "source": "the decant scanner fleet (9 devices)",
             "what": "Robust z of misread% vs peer decant devices with enough volume (gated by a minimum misread)."},
            {"name": "Station active/inactive", "source": "Decanting station report #2 (active_status)",
             "what": "Context (a station may be unstaffed, not broken) + a low-weight offline-persistence signal from the store."},
            {"name": "Station throughput", "source": "StationWise Decanted Cartons Count #2 (carton_count, windowed)",
             "what": "Per-station decanted cartons -> detects idle-while-active (Active + 0 cartons while the line is busy); low throughput alone is NOT penalized."},
            {"name": "Cross-run recurrence / trend", "source": "the accumulated store",
             "what": "Prior runs a scanner read elevated / a station stayed Inactive or idle-while-active; the health trajectory over runs (trend RUL)."},
        ],
        "entity_verdict": [
            "SCANNER: pull per-device ReadCount/NoReadCount over the window (decant/compaction only); misread% = NoRead/(Read+NoRead).",
            "SCANNER: start at 100 and subtract capped penalties — misread% (scaled by scan volume), peer-z vs "
            "the decant fleet (gated), and cross-run recurrence (prior runs elevated).",
            "STATION: read active_status + per-station decanted-carton count; mark idle-while-active if Active + "
            "0 cartons while the whole line is busy.",
            "STATION: start at 100 and subtract only cross-run penalties — consecutive-Inactive persistence and "
            "consecutive idle-while-active persistence (a single idle/Inactive run adds nothing).",
            "Map the score to a tier: ok >=85, watch 65-85, warn 40-65, critical <40.",
            "Estimate time-to-maintenance: cold-start => a coarse band by tier; trend (>=5 runs) => project the "
            "component's health trajectory over time (higher confidence).",
            "There is no 1:1 scanner<->station device mapping for decant (aisle diverters vs operator stations), so "
            "only a LINE-LEVEL corroboration note is added when both entity types look unhealthy in the same run.",
        ],
        "formulas": [
            {"name": "misread_rate", "formula": "NoReadCount / (ReadCount + NoReadCount)"},
            {"name": "volume_factor", "formula": "min(1, total_scans / min_volume_full)"},
            {"name": "idle_while_active", "formula": "is_active AND carton_count <= idle_floor AND line_total_cartons >= line_busy_min"},
            {"name": "health", "formula": "clamp(100 - Sum(capped_penalties), 0, 100)"},
        ],
        "notes": [
            "GTP Scanner logs #8 and StationWise Decanted Cartons Count #2 are time-FILTERED, so a wider window "
            "sharpens the misread rate + throughput. Decanting station report #2 is a current roster snapshot "
            "(10 stations DS001..DS010 regardless of window).",
            "The 9 decant/compaction scan devices were scored by the GTP module until Session 8; GTP now excludes "
            "subtypes decant/compaction, so each device is owned by exactly one module (CLAUDE.md §7). GTP Scanner "
            "logs is a SHARED panel.",
            "There is NO live per-station discrepancy signal: the two 'Discrepancy Marked' dashboards are frozen "
            "2022 drill-downs into discrepancy_details keyed by serial/carton (no station column). The station "
            "model is therefore coarse and low-confidence by necessity; if a live station-keyed discrepancy feed "
            "appears it would slot in as the station primary (mirroring the gtp_station discrepancy model).",
            "Compaction scanners read genuinely harder barcodes (~4% misread this snapshot) — the peer-z gate "
            "(minimum misread) plus the volume gate land them at watch (flag for inspection), not critical.",
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


register(DecantStationModule())
