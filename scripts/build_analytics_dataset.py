#!/usr/bin/env python3
"""Build analysis-ready CSV datasets from the live CSV store — for trends / EDA / ML.

The operational store (``database/store/*.csv``) is normalised and keeps flexible
metadata in JSON columns (``metrics_json``, ``rca_json``) — great for the app, awkward
for a data scientist. This script reads that store through the storage layer and writes
**tidy, flat, analysis-ready** CSVs under ``database/analytics/``:

    component_health_timeseries.csv   one row per component per run — the universal
                                      longitudinal table (consistent columns across
                                      every module): keys + score/tier/ttm/confidence/
                                      regime + parsed aisle + split-out date/hour. This
                                      is what you group by component/module/aisle/time to
                                      see TRENDS.
    by_module/<module>.csv            the same rows for one module with every model
                                      feature flattened out of metrics_json (``m_*``
                                      columns) and the RCA summary — a ready ML feature
                                      matrix (consistent columns within a module).
    runs.csv                          one row per PdM run (pdm_run) — run-level trend
                                      (rows fetched, components scored, timing, status).
    data_dictionary.csv               column -> dtype + description for the datasets.
    manifest.json                     what was built, row counts, generated-at.

It is **read-only** on the store, CSV-only (no MySQL), and safe to run any time — on an
empty store it writes header-only files so the structure exists for future runs. Re-run
it after PdM runs (or on a schedule) to refresh the extracts.

Run:  python scripts/build_analytics_dataset.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from core.config import get_config  # noqa: E402
from core.storage import get_storage  # noqa: E402
from core.storage.base import now_iso, to_json  # noqa: E402
from webapp.services import _aisle_of  # noqa: E402  (reuse the dashboard's aisle resolver)

# Universal, module-agnostic columns — the trend/EDA backbone.
UNIVERSAL_COLS = [
    "created_at", "created_date", "created_hour",
    "module", "component_id", "component_type", "aisle", "run_uid",
    "health_score", "risk_tier", "predicted_ttm_hours", "confidence",
    "prediction_regime", "primary_cause", "penalty_total",
]

DICTIONARY = [
    ("component_health_timeseries", "created_at", "datetime (UTC ISO-8601)", "Snapshot time of this component's score for this run — the time axis for trends."),
    ("component_health_timeseries", "created_date", "date (YYYY-MM-DD)", "Date part of created_at — convenient for daily grouping/resampling."),
    ("component_health_timeseries", "created_hour", "int (0-23)", "Hour part of created_at — for intraday patterns."),
    ("component_health_timeseries", "module", "str", "Equipment module name (lift, shuttle, …, meta)."),
    ("component_health_timeseries", "component_id", "str", "Physical unit id (stable per component across runs — the entity key for a trajectory)."),
    ("component_health_timeseries", "component_type", "str", "Unit type within the module (lift, shuttle, zone, bin_slot, …)."),
    ("component_health_timeseries", "aisle", "str|empty", "Aisle the unit belongs to (aisle_NN) where applicable; empty for aisle-less units."),
    ("component_health_timeseries", "run_uid", "str", "Run this snapshot belongs to (join key to runs.csv)."),
    ("component_health_timeseries", "health_score", "float (0-100)", "Predicted health; the primary target/trend series (higher = healthier)."),
    ("component_health_timeseries", "risk_tier", "categorical", "ok | watch | warn | critical (derived from health_score)."),
    ("component_health_timeseries", "predicted_ttm_hours", "float|empty", "Estimated time-to-maintenance in hours (empty when stable/not estimable)."),
    ("component_health_timeseries", "confidence", "float (0-1)", "Confidence in the prediction; rises as store history accumulates."),
    ("component_health_timeseries", "prediction_regime", "categorical", "coldstart (little history) | trend (history-fitted RUL)."),
    ("component_health_timeseries", "primary_cause", "str", "Dominant root cause named by the RCA for this run."),
    ("component_health_timeseries", "penalty_total", "float|empty", "Sum of health penalties applied this run (from metrics_json, where present)."),
    ("by_module/<module>", "m_*", "mixed", "Every raw + derived model feature for the module, flattened out of metrics_json (e.g. m_error_rate_per_day, m_penalties_severity). Consistent within a module; a ready ML feature matrix."),
    ("by_module/<module>", "rca_summary", "str", "One-line RCA summary for the run."),
    ("runs", "run_uid", "str", "Run id (join key from component_health_timeseries.run_uid)."),
    ("runs", "module", "str", "Module the run scored."),
    ("runs", "trigger_type", "categorical", "manual | auto."),
    ("runs", "data_window", "str", "Grafana window the run fetched (e.g. now-2d)."),
    ("runs", "started_at / finished_at", "datetime", "Run start/end (UTC ISO-8601)."),
    ("runs", "status", "categorical", "running | success | partial | failed."),
    ("runs", "rows_fetched", "int", "Raw rows pulled from Grafana for the run."),
    ("runs", "components_scored", "int", "Components scored in the run."),
]


def _flatten(prefix: str, value: Any, out: Dict[str, Any]) -> None:
    """Flatten a nested dict into ``out`` with ``prefix``-joined keys; lists -> JSON."""
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}{k}_" if isinstance(v, dict) else f"{prefix}{k}", v, out)
    elif isinstance(value, (list, tuple)):
        out[prefix.rstrip("_")] = to_json(value)
    else:
        out[prefix.rstrip("_")] = value


def _universal_row(r: Dict[str, Any]) -> Dict[str, Any]:
    metrics = r.get("metrics_json") or {}
    created = str(r.get("created_at") or "")
    hour = None
    if len(created) >= 13 and created[11:13].isdigit():
        hour = int(created[11:13])
    return {
        "created_at": created,
        "created_date": created[:10],
        "created_hour": hour,
        "module": r.get("module"),
        "component_id": r.get("component_id"),
        "component_type": r.get("component_type"),
        "aisle": _aisle_of(r) or "",
        "run_uid": r.get("run_uid"),
        "health_score": r.get("health_score"),
        "risk_tier": r.get("risk_tier"),
        "predicted_ttm_hours": r.get("predicted_ttm_hours"),
        "confidence": r.get("confidence"),
        "prediction_regime": r.get("prediction_regime"),
        "primary_cause": r.get("primary_cause"),
        "penalty_total": metrics.get("penalty_total"),
    }


def _module_row(r: Dict[str, Any]) -> Dict[str, Any]:
    row = {
        "created_at": str(r.get("created_at") or ""),
        "run_uid": r.get("run_uid"),
        "component_id": r.get("component_id"),
        "component_type": r.get("component_type"),
        "aisle": _aisle_of(r) or "",
        "health_score": r.get("health_score"),
        "risk_tier": r.get("risk_tier"),
        "predicted_ttm_hours": r.get("predicted_ttm_hours"),
        "confidence": r.get("confidence"),
        "prediction_regime": r.get("prediction_regime"),
        "primary_cause": r.get("primary_cause"),
    }
    _flatten("m_", r.get("metrics_json") or {}, row)
    rca = r.get("rca_json") or {}
    if isinstance(rca, dict):
        row["rca_summary"] = rca.get("summary", "")
    return row


def build() -> Dict[str, Any]:
    cfg = get_config()
    storage = get_storage()
    out_dir = cfg.data_dir / "analytics"
    by_mod_dir = out_dir / "by_module"
    out_dir.mkdir(parents=True, exist_ok=True)
    by_mod_dir.mkdir(parents=True, exist_ok=True)

    health = storage.select("component_health", order_by=("created_at", "asc"))
    runs = storage.select("pdm_run", order_by=("created_at", "asc"))

    # 1) universal tidy time-series
    uni = pd.DataFrame([_universal_row(r) for r in health], columns=UNIVERSAL_COLS)
    uni.sort_values(["module", "component_id", "created_at"], inplace=True, kind="stable")
    uni.to_csv(out_dir / "component_health_timeseries.csv", index=False)

    # 2) per-module wide feature matrices
    by_module_counts: Dict[str, int] = {}
    modules = sorted({r.get("module") for r in health if r.get("module")})
    for mod in modules:
        rows = [_module_row(r) for r in health if r.get("module") == mod]
        df = pd.DataFrame(rows)
        # stable, human-order columns: keys first, then sorted m_* features
        keys = [c for c in ["created_at", "run_uid", "component_id", "component_type", "aisle",
                            "health_score", "risk_tier", "predicted_ttm_hours", "confidence",
                            "prediction_regime", "primary_cause", "rca_summary"] if c in df.columns]
        feats = sorted(c for c in df.columns if c not in keys)
        df = df[keys + feats]
        df.sort_values(["component_id", "created_at"], inplace=True, kind="stable")
        df.to_csv(by_mod_dir / f"{mod}.csv", index=False)
        by_module_counts[mod] = len(df)

    # 3) run-level table
    run_cols = ["run_uid", "module", "trigger_type", "trigger_id", "data_window",
                "started_at", "finished_at", "status", "rows_fetched",
                "components_scored", "created_at"]
    pd.DataFrame(runs, columns=run_cols).to_csv(out_dir / "runs.csv", index=False)

    # 4) data dictionary
    pd.DataFrame(DICTIONARY, columns=["dataset", "column", "dtype", "description"]).to_csv(
        out_dir / "data_dictionary.csv", index=False
    )

    # 5) manifest
    manifest = {
        "generated_at": now_iso(),
        "store_backend": storage.backend_name,
        "source_store": str(cfg.data_dir / "store"),
        "output_dir": str(out_dir),
        "component_health_rows": len(health),
        "pdm_run_rows": len(runs),
        "modules": by_module_counts,
        "files": [
            "component_health_timeseries.csv",
            "runs.csv",
            "data_dictionary.csv",
            *[f"by_module/{m}.csv" for m in modules],
        ],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    m = build()
    print(f"Analytics datasets built -> {m['output_dir']}")
    print(f"  component_health rows: {m['component_health_rows']} | runs: {m['pdm_run_rows']}")
    if m["modules"]:
        print("  per-module:", ", ".join(f"{k}={v}" for k, v in m["modules"].items()))
    else:
        print("  (store empty — header-only files written; re-run after PdM runs)")
