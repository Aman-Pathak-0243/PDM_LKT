"""DECANTING STATION + SCANNER primary-signal analysis (SOP step 4 -> threshold calibration).

Pulls the resolved decant sources at full window and prints the distributions needed to
calibrate the health thresholds + confirm the (dual) component identity:

  Scanner misread  : GTP Scanner logs #8 (scanner, ReadCount, NoReadCount, efficiency) FILTERED
                     to the decant/compaction scan devices (*_decant_diverter, Compaction_*) ->
                     per-device misread rate + scan volume. These surface in the GTP scanner feed
                     but are the DECANT line's scan points (reconciled here from Module 7).
  Station roster   : Decanting station report #2 (station_id, active_status, user) -> the decant
                     station universe (DS001..DS0NN) + Active/Inactive split.
  Station throughput: StationWise Decanted Cartons Count #2 (station_id, carton_count) -> per-station
                     decanted-carton throughput over the window (utilization / activity baseline).

The two "Discrepancy Marked" dashboards are drill-downs into discrepancy_details keyed by
serial/carton (no station column, data frozen 2022-23) -> they cannot yield a live per-station
discrepancy rate; this script confirms that so the module leans on the scanner-misread signal.

Usage: .venv/bin/python scripts/analyze_decant_primary.py [--window now-2d]
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import download_panel_csv

SCANNER_LOGS = "http://192.168.24.230/grafana/d/pK7-8NmVz/gtp-scanner-logs"
STATION_REPORT = "http://192.168.24.230/grafana/d/B4i1-HpVz/decanting-station-report"
STATIONWISE_CARTONS = "http://192.168.24.230/grafana/d/n1oZnY_Vz/stationwise-decanted-cartons-count"
DISCREPANCY_BARCODE = "http://192.168.24.230/grafana/d/E_nYUnU4z/discrepancy-marked-barcode"

_DECANT_RE = re.compile(r"decant", re.I)
_COMPACT_RE = re.compile(r"compaction", re.I)


def _pct(x):
    try:
        return f"{100 * float(x):.3f}%"
    except (TypeError, ValueError):
        return "n/a"


def _decant_subtype(name: str) -> str:
    s = str(name).lower()
    if _DECANT_RE.search(s):
        return "decant"
    if _COMPACT_RE.search(s):
        return "compaction"
    return "other"


def analyze(window: str) -> None:
    with GrafanaSession() as gs:
        # ---- Scanner misread (#8) filtered to decant/compaction -------------
        rr = download_panel_csv(gs, SCANNER_LOGS, 8, frm=window, to="now").df
        print(f"\n===== DECANT/COMPACTION SCANNER misread (GTP Scanner logs #8) — window={window} =====")
        print(f"total scanner rows={len(rr)}  cols={list(rr.columns)}")
        if not rr.empty and "scanner" in rr.columns:
            rr = rr.copy()
            rr["ReadCount"] = pd.to_numeric(rr["ReadCount"], errors="coerce").fillna(0)
            rr["NoReadCount"] = pd.to_numeric(rr["NoReadCount"], errors="coerce").fillna(0)
            rr["total"] = rr["ReadCount"] + rr["NoReadCount"]
            rr["misread_rate"] = rr["NoReadCount"] / rr["total"].replace(0, pd.NA)
            rr["subtype"] = rr["scanner"].map(_decant_subtype)
            dec = rr[rr["subtype"].isin(["decant", "compaction"])].copy()
            print(f"decant/compaction scan devices: {len(dec)}")
            print("subtype breakdown:")
            print(dec.groupby("subtype").agg(
                n=("scanner", "count"), scans=("total", "sum"),
                mean_misread=("misread_rate", "mean"),
                noreads=("NoReadCount", "sum")).to_string())
            print("\nper-device (decant/compaction), worst misread first:")
            for _, r in dec.sort_values("misread_rate", ascending=False, na_position="last").iterrows():
                print(f"  {r['scanner']:<34} [{r['subtype']:<10}] misread={_pct(r['misread_rate'])}  "
                      f"noread={int(r['NoReadCount'])}/{int(r['total'])}  eff={r.get('efficiency_percentage')}")
            # fleet context: how the decant devices compare to the whole scanner fleet
            active = rr[rr["total"] > 0]
            print(f"\nfleet misread median={_pct(active['misread_rate'].median())}  "
                  f"p90={_pct(active['misread_rate'].quantile(.9))}  (n={len(active)})")

        # ---- Station roster + active status (Decanting station report #2) ----
        st = download_panel_csv(gs, STATION_REPORT, 2, frm=window, to="now").df
        print(f"\n\n===== DECANT STATION roster (Decanting station report #2) — window={window} =====")
        print(f"rows(stations)={len(st)}  cols={list(st.columns)}")
        id_col = next((c for c in st.columns if c.lower() in ("station id", "station_id", "id")), None)
        as_col = next((c for c in st.columns if "active" in c.lower()), None)
        if id_col:
            roster = set(st[id_col].dropna().astype(str))
            print(f"station universe: {len(roster)} ids -> {sorted(roster)}")
            if as_col:
                print("active_status:", dict(Counter(st[as_col].dropna().astype(str))))

        # ---- Station throughput (StationWise Decanted Cartons Count #2) ------
        cc = download_panel_csv(gs, STATIONWISE_CARTONS, 2, frm=window, to="now").df
        print(f"\n\n===== DECANT STATION throughput (StationWise Decanted Cartons Count #2) — window={window} =====")
        print(f"rows={len(cc)}  cols={list(cc.columns)}")
        if not cc.empty and "station_id" in cc.columns and "carton_count" in cc.columns:
            cc = cc.copy()
            cc["carton_count"] = pd.to_numeric(cc["carton_count"], errors="coerce").fillna(0)
            per = cc.groupby("station_id")["carton_count"].sum().sort_values(ascending=False)
            print(f"stations with throughput this window: {per.size}")
            for sid, n in per.items():
                print(f"  {sid:<10} {int(n)} cartons")
            print("throughput distribution:")
            print(per.describe(percentiles=[.5, .75, .9]).to_string())
            if id_col:
                busy = set(per.index.astype(str))
                print(f"roster stations idle this window (Active but 0 cartons possible): "
                      f"{sorted(roster - busy)}")

        # ---- Confirm discrepancy feed is a frozen drill-down (no station key) --
        db = download_panel_csv(gs, DISCREPANCY_BARCODE, 2, frm=window, to="now").df
        print(f"\n\n===== Discrepancy Marked Barcode #2 (drill-down check) — window={window} =====")
        print(f"rows={len(db)}  cols={list(db.columns)}  (keyed by serial/carton; no station column)")
        if not db.empty and "create_timestamp" in db.columns:
            ct = pd.to_datetime(db["create_timestamp"], errors="coerce")
            print(f"create_timestamp span: {ct.min()} .. {ct.max()}  (frozen/historical if 2022-23)")
        if not db.empty and "discrepancy_type" in db.columns:
            print("discrepancy_type mix:", dict(Counter(db["discrepancy_type"].dropna())))


def main() -> None:
    window = "now-2d"
    args = sys.argv[1:]
    if "--window" in args:
        window = args[args.index("--window") + 1]
    analyze(window)


if __name__ == "__main__":
    main()
