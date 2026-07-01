"""CONTROLLER / COMPUTE module — self-registers a :class:`PdMModule` on import.

Pipeline: fetch.py -> features.py -> health.py (calls rca.py). Tunables in module.yaml (via spec.py).
Single component type:

  * compute_node — a controller compute node (a SINGLE node this snapshot: 'db_controller', the SQL/DBA
    database-controller server). Signal = CPU utilization% = 100 - cpu_idle (CPU Stats / getCPUDetails),
    with the SQL CPU share as context. A healthy controller keeps idle headroom (44% utilization this
    snapshot); a saturating one (util climbing toward 80-95%) is a crash/throttle precursor.

The feed is a current-state CPU snapshot (no in-feed trend, no memory, no per-host breakdown), so the
STORE provides the sustained-high + trend signal across runs. A saturated controller starves the WES,
so the module raises a system-wide 'meta' cross-flag — the hook for the meta-module (Module 11).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.config import Config
from core.registry import ComponentHealth, FetchBundle, HistoryReader, PdMModule, register
from modules.controller.features import compute_features as _compute_features
from modules.controller.fetch import fetch as _fetch
from modules.controller.health import score as _score
from modules.controller.spec import spec


class ControllerModule(PdMModule):
    name = "controller"
    title = "Controller / Compute PdM"
    component_type = "compute_node"
    description = (
        "Predictive maintenance for the controller compute node(s). CPU health is inferred from current "
        "CPU utilization% (100 - cpu_idle, from CPU Stats / getCPUDetails), with the SQL CPU share as "
        "context. The feed is a current-state snapshot, so the store provides the sustained-high + trend "
        "signal across runs. A saturating controller starves the WES — a system-wide throttle cross-feature."
    )

    methodology = {
        "summary": (
            "This module scores the controller COMPUTE NODE(S) — a single node this snapshot, the SQL/DBA "
            "database-controller server ('db_controller'). The signal is CPU utilization% = 100 - cpu_idle "
            "(from CPU Stats' getCPUDetails proc), with the SQL Server's CPU share (cpu_sql) as context. A "
            "healthy controller keeps plenty of idle headroom (44% utilization / 56% idle this snapshot); a "
            "saturating controller (utilization climbing toward 80-95%) is a crash/throttle precursor that "
            "starves the WES and slows EVERY shuttle/lift/GTP operation. A node starts at 100 and loses "
            "points for CPU utilization above a fleet-normal floor (saturation) and for being pinned high "
            "across consecutive runs (sustained_high). The feed is a current-state snapshot with no in-feed "
            "trend or memory metric, so the store provides the sustained-high + trend history. When the node "
            "is saturated the RCA raises a system-wide 'meta' cross-flag — the hook for the meta-module to "
            "chain compute-saturation -> system-wide throttle -> downstream shuttle/lift errors."
        ),
        "signals": [
            {"name": "CPU utilization%", "source": "CPU Stats #17 (getCPUDetails: cpu_idle)",
             "what": "100 - cpu_idle per node — the core compute-saturation signal (less idle = less headroom)."},
            {"name": "SQL CPU share", "source": "CPU Stats #17 (cpu_sql)",
             "what": "The SQL Server's share of CPU — context (a DB-controller is expected to be SQL-heavy)."},
            {"name": "Sustained-high", "source": "the accumulated store",
             "what": "Consecutive recent runs with utilization% >= the high threshold — persistent saturation, not a spike."},
            {"name": "Trend", "source": "the accumulated store",
             "what": "The node's health trajectory over runs (rising CPU -> falling health -> projected RUL)."},
        ],
        "entity_verdict": [
            "Read the current CPU snapshot (cpu_idle, cpu_sql); utilization% = 100 - cpu_idle; sql_share = cpu_sql / utilization.",
            "Start at 100 and subtract capped penalties — utilization above the saturation floor, and "
            "consecutive-run persistence above the high threshold (store-driven).",
            "Map the score to a tier: ok >=85, watch 65-85, warn 40-65, critical <40.",
            "Estimate time-to-maintenance: cold-start => a coarse band by tier (tighter than event modules, "
            "since saturation escalates fast); trend (>=5 runs) => project the node's health trajectory.",
            "When the node is saturated (warn or worse), raise a system-wide 'meta' cross-flag: a starved "
            "controller slows every robot — the chain the meta-module correlates.",
        ],
        "formulas": [
            {"name": "utilization_pct", "formula": "100 - cpu_idle"},
            {"name": "sql_share", "formula": "cpu_sql / utilization_pct"},
            {"name": "health", "formula": "clamp(100 - Sum(capped_penalties), 0, 100)"},
        ],
        "notes": [
            "CPU Stats #17 is a CURRENT-STATE snapshot (EXEC getCPUDetails returns the same single row at "
            "now-6h/2d/30d — the window does not filter it). Like Gate/Bin, the store overcomes this: each "
            "run snapshots the current utilization, so sustained-high + trend accrue across runs. Regular "
            "automation is what makes this predictive.",
            "The mapping billed this as 'CPU / memory utilization trend' across 'controller compute nodes' "
            "(plural). Live SQL shows CPU-ONLY, a SINGLE node, and a current-state snapshot (no in-feed trend, "
            "no memory, no per-host breakdown). Scoped honestly. The feature extractor keys by a host/node "
            "column if the proc ever returns per-host rows, so it scales to N nodes with no code change.",
            "A saturated controller is a system-wide cross-feature (it runs the WES that drives every robot); "
            "a future per-host CPU+memory feed (or the OPC/Kepware dataloggers, no CSV today) would extend "
            "this toward the mapping's original intent. Ruled out: JIT Frame Unallocated (JIT order frames, "
            "inventory), OPC dataloggers (raw per-device telemetry, no CPU).",
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


register(ControllerModule())
