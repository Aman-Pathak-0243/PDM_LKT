"""CONTROLLER / COMPUTE feature extraction — per compute node from the CPU snapshot.

From CPU Stats #17 (EXEC getCPUDetails -> cpu_idle, cpu_sql):
  utilization_pct = 100 - cpu_idle   (the core compute signal; higher = less headroom)
  cpu_sql_pct     = cpu_sql          (SQL Server's CPU share)
  cpu_other_pct   = 100 - cpu_idle - cpu_sql
  sql_share       = cpu_sql / utilization  (share of USED cpu that is SQL — context)

The proc returns one aggregate row today (-> component_id 'db_controller'). If it ever returns a
host/node column per row, we key by it so the module scales to N nodes with no code change. All
cross-run signals (sustained-high, trend) live in health.py, which holds the store history. Every
feature is documented in modules/controller/README.md.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from core.logging_setup import get_logger
from core.registry import FetchBundle

log = get_logger("controller.features")

_DEFAULT_NODE = "db_controller"


def _col(df: pd.DataFrame, *names: str) -> Optional[str]:
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _num1(v) -> float:
    n = pd.to_numeric(pd.Series([v]), errors="coerce").iloc[0]
    return float(n) if pd.notna(n) else 0.0


def _row_features(row: pd.Series, idle_col: str, sql_col: str, node_id: str, window) -> Dict[str, Any]:
    idle = _num1(row[idle_col]) if idle_col else 0.0
    sql = _num1(row[sql_col]) if sql_col else 0.0
    # clamp idle to [0,100]; utilization is the complement.
    idle = min(max(idle, 0.0), 100.0)
    util = round(max(0.0, 100.0 - idle), 3)
    sql = min(max(sql, 0.0), 100.0)
    other = round(max(0.0, 100.0 - idle - sql), 3)
    sql_share = round(sql / util, 4) if util > 0 else 0.0
    return {
        "component_id": node_id,
        "component_type": "compute_node",
        "entity": "compute_node",
        "node": node_id,
        "window": window,
        "cpu_idle_pct": round(idle, 3),
        "cpu_sql_pct": round(sql, 3),
        "cpu_other_pct": other,
        "utilization_pct": util,
        "sql_share": sql_share,
    }


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    window = bundle.notes.get("window")
    df = bundle.frames.get("cpu", pd.DataFrame())
    if df is None or df.empty:
        log.warning("no CPU data — no compute components")
        return {}

    idle_col = _col(df, "cpu_idle", "idle", "cpu idle")
    sql_col = _col(df, "cpu_sql", "sql", "cpu sql")
    if not idle_col and not sql_col:
        log.warning("CPU frame missing cpu_idle/cpu_sql", extra={"cols": list(df.columns)})
        return {}
    # scalable: key by a host/node column if the proc ever returns one per row.
    node_col = _col(df, "host", "hostname", "node", "server", "instance", "name", "machine")

    feats: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        node_id = str(row[node_col]).strip() if node_col and pd.notna(row.get(node_col)) else _DEFAULT_NODE
        if not node_id:
            node_id = _DEFAULT_NODE
        feats[node_id] = _row_features(row, idle_col, sql_col, node_id, window)

    log.info("controller features computed",
             extra={"nodes": len(feats),
                    "worst_util": round(max((f["utilization_pct"] for f in feats.values()), default=0), 2),
                    "keyed_by_host": bool(node_col)})
    return feats
