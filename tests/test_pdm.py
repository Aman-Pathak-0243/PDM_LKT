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


# --------------------------- shuttle model ------------------------------- #
def _shuttle_bundle():
    from core.registry import FetchBundle as FB
    now = pd.Timestamp.now()
    erows = []
    for i in range(40):  # heavy fork faulter
        erows.append({"shuttle_id": "QD_Shuttle_03_06", "error_type": "FORK_ERROR",
                      "error_desc": "REAR_SIDE_RIGHT_FORK_DOWN_IS_FAULTY",
                      "created_time": (now - pd.Timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"),
                      "updated_timestamp": ""})
    err = pd.DataFrame(erows)
    cyc = pd.DataFrame([
        {"shuttle_id": "QD_Shuttle_03_06", "PUTAWAY": 9000, "PICKING": 9000, "RESHUFFLING": 9000},
        {"shuttle_id": "QD_Shuttle_05_04", "PUTAWAY": 24896, "PICKING": 26680, "RESHUFFLING": 28004},
        {"shuttle_id": "QD_Shuttle_01_01", "PUTAWAY": 13000, "PICKING": 14000, "RESHUFFLING": 14000},
    ])
    return FB(frames={"errors": err, "cycles": cyc}, rows_fetched=len(err) + len(cyc),
              panels=[], notes={"window": "now-30d"})


def test_shuttle_cycles_normalisation_and_scoring():
    from modules.shuttle.features import compute_features as scf
    from modules.shuttle.health import score as ssc
    feats = scf(_shuttle_bundle())
    assert len(feats) == 3  # roster from cycles
    bad = feats["QD_Shuttle_03_06"]
    assert bad["error_count"] == 40 and bad["total_cycles"] == 27000
    # errors per million cycles = 40/27000*1e6 ≈ 1481
    assert 1400 < bad["errors_per_mcycle"] < 1600
    assert bad["mechanical_share"] == 1.0 and bad["epc_peer_z"] > 1.0  # positive outlier (n=3 fixture)

    comps = ssc(feats, _NoHistory())
    by_id = {c.component_id: c for c in comps}
    assert by_id["QD_Shuttle_03_06"].risk_tier == "critical"
    assert by_id["QD_Shuttle_01_01"].risk_tier == "ok"        # no errors
    assert comps[0].component_id == "QD_Shuttle_03_06"        # worst-first
    assert "FORK" in (by_id["QD_Shuttle_03_06"].primary_cause or "")


# --------------------------- conveyor model ------------------------------ #
def _conveyor_bundle():
    from core.registry import FetchBundle as FB
    rows = []
    # zone_2: heavily congested (queue ~1.6x limit). zone_5: flowing (~0.7x).
    for i in range(120):
        rows.append({"time": f"2026-06-30 10:{i%60:02d}:00", "Conveyor Actual": 64,
                     "Conveyor Limit": 40, "Buffer Actual": 6, "Buffer Limit": 40, "zone": "2"})
        rows.append({"time": f"2026-06-30 10:{i%60:02d}:00", "Conveyor Actual": 28,
                     "Conveyor Limit": 40, "Buffer Actual": 4, "Buffer Limit": 40, "zone": "5"})
    df = pd.DataFrame(rows)
    return FB(frames={"zone_counts": df}, rows_fetched=len(df), panels=[],
              notes={"window": "now-24h", "system_on_hold": 10, "system_in_transit": 12})


def test_conveyor_congestion_and_scoring():
    from modules.conveyor.features import compute_features as ccf
    from modules.conveyor.health import score as csc
    feats = ccf(_conveyor_bundle())
    assert set(feats) == {"zone_2", "zone_5"}
    assert feats["zone_2"]["congestion_mean"] == 1.6           # 64/40
    assert feats["zone_5"]["congestion_mean"] == 0.7           # 28/40
    assert feats["zone_2"]["severe_saturation_share"] == 1.0   # always >= 1.5

    comps = csc(feats, _NoHistory())
    by_id = {c.component_id: c for c in comps}
    assert by_id["zone_2"].health_score < by_id["zone_5"].health_score
    assert by_id["zone_5"].risk_tier == "ok"
    assert comps[0].component_id == "zone_2"                    # worst-first
    assert "limit" in (by_id["zone_2"].primary_cause or "").lower()


# --------------------------- tracker model ------------------------------- #
def _tracker_bundle():
    from core.registry import FetchBundle as FB
    now = pd.Timestamp.now()

    def row(loc, trk, shuttle, age_h, lift=None, lift_desc=None):
        return {
            "tracker": trk, "container": f"TL{trk}", "location": loc,
            "created_time": (now - pd.Timedelta(hours=age_h)).strftime("%Y-%m-%d %H:%M:%S"),
            "shuttle_id": shuttle, "task_type": "PICKING", "status": 8.0,
            "shuttle Status Description": "SHUTTLE_PICK_ERROR" if shuttle else None,
            "lift_id": lift, "lift_status": 2.0 if lift else None,
            "lift Status Description": lift_desc,
        }

    rows = []
    # Degrading position: a recent cluster of 4 mislocated totes, two distinct shuttles.
    for i in range(4):
        rows.append(row("aisle_03_bt_10", 1000 + i, "QD_Shuttle_03_10" if i < 3 else "QD_Shuttle_03_11", i + 1))
    # Healthy position: a single long-stale (old) tote.
    rows.append(row("aisle_05_bt_9", 2000, "QD_Shuttle_05_09", 24 * 300))
    # A position with a lift in ERROR.
    rows.append(row("aisle_04_bt_2", 3000, None, 2, lift="aisle_04_inbound_lift_02", lift_desc="ERROR"))
    df = pd.DataFrame(rows)
    return FB(frames={"bad_tracker": df}, rows_fetched=len(df), panels=[],
              notes={"window": "now-7d", "total_bt_totes": len(df)})


def test_tracker_clustering_and_scoring():
    from modules.tracker.features import compute_features as tcf, _parse_window_days
    from modules.tracker.health import score as tsc

    assert _parse_window_days("now-7d") == 7
    assert abs(_parse_window_days("now-12h") - 0.5) < 1e-9

    feats = tcf(_tracker_bundle())
    assert set(feats) == {"aisle_03_bt_10", "aisle_05_bt_9", "aisle_04_bt_2"}
    bad = feats["aisle_03_bt_10"]
    assert bad["bad_count"] == 4 and bad["recent_bad_count"] == 4
    assert bad["distinct_shuttles"] == 2 and bad["aisle"] == "aisle_03"
    assert bad["bad_count_peer_z"] > 0
    assert feats["aisle_05_bt_9"]["recent_bad_count"] == 0   # long-stale single tote
    assert feats["aisle_04_bt_2"]["lift_error_count"] == 1

    comps = tsc(feats, _NoHistory())
    by_id = {c.component_id: c for c in comps}
    assert comps[0].component_id == "aisle_03_bt_10"          # worst-first
    assert by_id["aisle_03_bt_10"].health_score < by_id["aisle_05_bt_9"].health_score
    assert by_id["aisle_05_bt_9"].risk_tier == "ok"          # isolated stale tote
    assert by_id["aisle_03_bt_10"].prediction_regime == "coldstart"
    # Cross-module flags: one shuttle dominates the cluster -> shuttle; lift ERROR -> lift.
    assert any(x["module"] == "shuttle" for x in by_id["aisle_03_bt_10"].rca["cross_module_flags"])
    assert any(x["module"] == "lift" for x in by_id["aisle_04_bt_2"].rca["cross_module_flags"])


def test_tracker_recurrence_lowers_health():
    """Longitudinal store: a position flagged in prior runs scores worse (recurrence)."""
    from modules.tracker.features import compute_features as tcf
    from modules.tracker.health import score as tsc

    class _Hist:
        def __init__(self, n):
            self._n = n

        def component_history(self, module, component_id, limit=200):
            if component_id == "aisle_03_bt_10":
                return [{"created_at": now_iso(), "health_score": 50.0} for _ in range(self._n)]
            return []

        def run_count(self, module):
            return self._n

    feats = tcf(_tracker_bundle())
    cold = {c.component_id: c for c in tsc(feats, _NoHistory())}
    recur = {c.component_id: c for c in tsc(feats, _Hist(3))}
    assert recur["aisle_03_bt_10"].health_score < cold["aisle_03_bt_10"].health_score
    assert recur["aisle_03_bt_10"].metrics["recurrence_runs"] == 3


def test_methodology_doc_present_for_modules():
    import modules  # registers lift + shuttle + conveyor + tracker
    from core.registry import all_modules, module_methodology
    for m in all_modules():
        md = module_methodology(m)
        assert md["module"] == m.name
        assert md["overall_status"]["rules"]          # shared rollup doc present
        if m.name in ("lift", "shuttle", "conveyor", "tracker"):
            assert md["entity_verdict"] and md["signals"]  # module-specific content
