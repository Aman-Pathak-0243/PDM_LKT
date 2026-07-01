"""GTP STATION + SCANNER primary-signal analysis (SOP step 4 → threshold calibration).

Pulls the resolved GTP sources at full window and prints the distributions needed to
calibrate the health thresholds + confirm the component identity:

  Scanner misread   : GTP Scanner logs #8 (scanner, ReadCount, NoReadCount, efficiency)
                      + #4 (scanner, hits) → per-scanner misread rate + scan volume, subtype
                      breakdown, worst offenders.
  Station discrepancy: Discrepancy Report Events #2 (verification_events) → per-station
                      discrepancy counts, type + discrepancy_type mix.
  Station roster     : GTP Stations #2 (id, active_status, operation_type) → the 63-station
                      universe + active/inactive split; cross-check vs discrepancy stations.

Usage: .venv/bin/python scripts/analyze_gtp_primary.py [--window now-2d]
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
DISCREPANCY = "http://192.168.24.230/grafana/d/D6sQle2Vz/discrepancy-report-events"
STATIONS = "http://192.168.24.230/grafana/d/GlGBwgY4z/gtp-stations"


def _pct(x):
    return f"{100*x:.2f}%"


def _subtype(scanner: str) -> str:
    s = str(scanner).lower()
    for kind in ("inbound_scanner", "outbound_scanner", "decant_diverter", "diverter",
                 "scanner", "induct", "reject"):
        if kind in s:
            return kind
    return "other"


def analyze(window: str) -> None:
    with GrafanaSession() as gs:
        # ---- Scanner misread (#8) + hits (#4) --------------------------------
        rr = download_panel_csv(gs, SCANNER_LOGS, 8, frm=window, to="now").df
        hits = download_panel_csv(gs, SCANNER_LOGS, 4, frm=window, to="now").df
        print(f"\n===== SCANNER Read/NoRead (#8) — window={window} =====")
        print(f"rows(scanners)={len(rr)}  cols={list(rr.columns)}")
        if not rr.empty:
            rr = rr.copy()
            rr["ReadCount"] = pd.to_numeric(rr["ReadCount"], errors="coerce").fillna(0)
            rr["NoReadCount"] = pd.to_numeric(rr["NoReadCount"], errors="coerce").fillna(0)
            rr["total"] = rr["ReadCount"] + rr["NoReadCount"]
            rr["misread_rate"] = rr["NoReadCount"] / rr["total"].replace(0, pd.NA)
            rr["subtype"] = rr["scanner"].map(_subtype)
            print(f"total scans across all scanners: {int(rr['total'].sum()):,}")
            print(f"scanners with >=1 no-read: {(rr['NoReadCount'] > 0).sum()} / {len(rr)}")
            print(f"scanners with 0 scans (idle): {(rr['total'] == 0).sum()}")
            active = rr[rr["total"] > 0]
            print("\nmisread_rate distribution (scanners with >=1 scan):")
            print(active["misread_rate"].describe(percentiles=[.5, .75, .9, .95, .99]).to_string())
            print("\nvolume (total scans) distribution:")
            print(active["total"].describe(percentiles=[.5, .9, .99]).to_string())
            print("\nsubtype breakdown:")
            print(active.groupby("subtype").agg(
                n=("scanner", "count"), scans=("total", "sum"),
                mean_misread=("misread_rate", "mean"),
                noreads=("NoReadCount", "sum")).to_string())
            print("\nworst 15 scanners by misread_rate (>=50 scans):")
            worst = active[active["total"] >= 50].sort_values("misread_rate", ascending=False).head(15)
            for _, r in worst.iterrows():
                print(f"  {r['scanner']:<34} misread={_pct(r['misread_rate'])}  "
                      f"noread={int(r['NoReadCount'])}/{int(r['total'])}  eff={r.get('efficiency_percentage')}")
            print("\nworst 10 by absolute no-reads:")
            for _, r in rr.sort_values("NoReadCount", ascending=False).head(10).iterrows():
                print(f"  {r['scanner']:<34} noread={int(r['NoReadCount'])}  total={int(r['total'])}  misread={_pct(r['misread_rate']) if r['total'] else 'n/a'}")
        if not hits.empty:
            print(f"\n#4 Scanner Hits: rows={len(hits)}  e.g. {hits.head(3).to_dict('records')}")

        # ---- Station discrepancies (#2) --------------------------------------
        dr = download_panel_csv(gs, DISCREPANCY, 2, frm=window, to="now").df
        print(f"\n\n===== STATION Discrepancies (Discrepancy Report Events #2) — window={window} =====")
        print(f"rows(events)={len(dr)}  cols={list(dr.columns)}")
        if not dr.empty and "station" in dr.columns:
            per = dr.groupby("station").size().sort_values(ascending=False)
            print(f"distinct stations with discrepancies: {per.size}")
            print("per-station discrepancy count distribution:")
            print(per.describe(percentiles=[.5, .75, .9, .95, .99]).to_string())
            print("\ntop 15 stations by discrepancy count:")
            for st, n in per.head(15).items():
                print(f"  {st:<10} {n}")
            if "discrepancy_type" in dr.columns:
                print("\ndiscrepancy_type mix:", dict(Counter(dr["discrepancy_type"].dropna()).most_common(10)))
            if "type" in dr.columns:
                print("type mix:", dict(Counter(dr["type"].dropna()).most_common(10)))
            if "operation_type" in dr.columns:
                print("operation_type mix:", dict(Counter(dr["operation_type"].dropna()).most_common()))
            if "create_time" in dr.columns:
                ct = pd.to_datetime(dr["create_time"], errors="coerce")
                print(f"time span: {ct.min()} .. {ct.max()}")

        # ---- Station roster + active status (#2) -----------------------------
        st = download_panel_csv(gs, STATIONS, 2, frm=window, to="now").df
        print(f"\n\n===== STATION roster (GTP Stations #2) — window={window} =====")
        print(f"rows(stations)={len(st)}  cols={list(st.columns)}")
        if not st.empty and "id" in st.columns:
            if "active_status" in st.columns:
                print("active_status:", dict(Counter(st["active_status"].dropna())))
            if "operation_type" in st.columns:
                print("operation_type:", dict(Counter(st["operation_type"].dropna())))
            if "Type" in st.columns:
                print("Type:", dict(Counter(st["Type"].dropna())))
            roster = set(st["id"].dropna().astype(str))
            print(f"station universe: {len(roster)} ids, e.g. {sorted(roster)[:8]}")
            if not dr.empty and "station" in dr.columns:
                disc_st = set(dr["station"].dropna().astype(str))
                print(f"discrepancy stations in roster: {len(disc_st & roster)}/{len(disc_st)} "
                      f"(not in roster: {sorted(disc_st - roster)[:8]})")


def main() -> None:
    window = "now-2d"
    args = sys.argv[1:]
    if "--window" in args:
        window = args[args.index("--window") + 1]
    analyze(window)


if __name__ == "__main__":
    main()
