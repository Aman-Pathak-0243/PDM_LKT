"""Offline unit tests (no network): storage backend + LIFT model logic.

Run: .venv/bin/python -m pytest -q
"""

from __future__ import annotations

import pandas as pd

from core.registry import FetchBundle, score_to_tier, worst_tier
from core.storage.base import now_iso, new_uid
from core.storage.csv_backend import CsvBackend
from modules.lift.features import _parse_window_days, _robust_z, compute_features
from modules.lift.health import score
from modules.lift.spec import error_info


class _NoHistory:
    def component_history(self, module, component_id, limit=200):
        return []

    def run_count(self, module):
        return 0


# --------------------------- storage ------------------------------------- #
def test_csv_storage_roundtrip(tmp_path):
    be = CsvBackend(tmp_path)
    be.init_schema()
    uid = new_uid()
    ids = be.insert("pdm_run", [{
        "run_uid": uid, "module": "lift", "trigger_type": "manual", "trigger_id": "t",
        "data_window": "now-2d", "started_at": now_iso(), "finished_at": now_iso(),
        "status": "success", "rows_fetched": 5, "components_scored": 2, "error": "",
        "created_at": now_iso(),
    }])
    assert ids == [1]
    assert be.count("pdm_run") == 1
    assert be.select("pdm_run", {"status": "success"})[0]["run_uid"] == uid
    assert be.select("pdm_run", {"rows_fetched": (">=", 5)})
    # json column round-trip
    be.insert("component_health", [{
        "run_uid": uid, "module": "lift", "component_id": "L1", "component_type": "lift",
        "health_score": 42.0, "risk_tier": "warn", "predicted_ttm_hours": 96.0,
        "confidence": 0.5, "prediction_regime": "coldstart", "primary_cause": "x",
        "rca_json": {"a": [1, 2]}, "metrics_json": {"n": 3}, "created_at": now_iso(),
    }])
    row = be.select("component_health", {"component_id": "L1"})[0]
    assert row["rca_json"] == {"a": [1, 2]} and row["metrics_json"]["n"] == 3
    # upsert + delete
    be.upsert("automation_config", ["scope"], {"scope": "global", "enabled": True,
              "interval_minutes": 30, "data_window": "now-2d", "updated_at": now_iso()})
    be.upsert("automation_config", ["scope"], {"scope": "global", "enabled": False,
              "interval_minutes": 45, "data_window": "now-2d", "updated_at": now_iso()})
    g = be.select("automation_config", {"scope": "global"})[0]
    assert g["enabled"] is False and g["interval_minutes"] == 45
    assert be.delete("pdm_run", {"run_uid": uid}) == 1 and be.count("pdm_run") == 0


# --------------------------- helpers ------------------------------------- #
def test_window_parse():
    assert _parse_window_days("now-2d") == 2
    assert _parse_window_days("now-30d") == 30
    assert abs(_parse_window_days("now-6h") - 0.25) < 1e-9
    assert _parse_window_days("garbage") == 2  # safe default


def test_robust_z_flags_outlier():
    vals = [1, 1, 1, 1, 10]
    assert _robust_z(10, vals) > 1.5      # clear outlier (std fallback when MAD=0)
    assert _robust_z(1, vals) <= 0.5
    assert _robust_z(5, [5, 5, 5, 5]) == 0.0  # no spread


def test_error_catalog():
    assert error_info(14)["category"] == "drive_motor"
    assert error_info(5)["severity"] == 1.0
    assert error_info(9999)["category"] == "other"  # default


def test_tier_helpers():
    assert score_to_tier(90) == "ok"
    assert score_to_tier(50) == "warn"
    assert score_to_tier(10) == "critical"
    assert worst_tier(["ok", "warn", "critical", "watch"]) == "critical"


# --------------------------- lift model ---------------------------------- #
def _bundle():
    now = pd.Timestamp.now()
    rows = []
    # Unhealthy lift: many high-severity motor faults.
    for i in range(60):
        rows.append({"lift_id": "aisle_01_inbound_lift_02", "error_code": 14,
                     "error_desc": "Lift Motor has exceeded software limit",
                     "created_time": (now - pd.Timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"),
                     "updated_timestamp": ""})
    # Healthy lift: a couple of low-severity faults.
    for i in range(2):
        rows.append({"lift_id": "aisle_02_outbound_lift_01", "error_code": 18,
                     "error_desc": "Bin already present inside carriage",
                     "created_time": (now - pd.Timedelta(hours=i * 5)).strftime("%Y-%m-%d %H:%M:%S"),
                     "updated_timestamp": ""})
    df = pd.DataFrame(rows)
    return FetchBundle(frames={"errors": df}, rows_fetched=len(df), panels=[],
                       notes={"window": "now-7d"})


def test_lift_features_and_scoring():
    feats = compute_features(_bundle())
    assert set(feats) == {"aisle_01_inbound_lift_02", "aisle_02_outbound_lift_01"}
    bad = feats["aisle_01_inbound_lift_02"]
    assert bad["error_count"] == 60 and bad["mechanical_share"] == 1.0
    assert bad["rate_peer_z"] > 0  # above peer

    comps = score(feats, _NoHistory())
    by_id = {c.component_id: c for c in comps}
    bad_c = by_id["aisle_01_inbound_lift_02"]
    good_c = by_id["aisle_02_outbound_lift_01"]
    assert bad_c.health_score < good_c.health_score
    assert bad_c.risk_tier == "critical"
    assert bad_c.prediction_regime == "coldstart"
    assert "14" in bad_c.rca["error_mix"]
    assert comps[0].component_id == "aisle_01_inbound_lift_02"  # sorted worst-first
