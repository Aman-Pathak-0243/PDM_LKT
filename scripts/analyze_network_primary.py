"""NETWORK / COMMS primary-signal analysis (SOP step 4 -> threshold calibration).

Pulls the resolved Network source at full window and prints the distributions needed to calibrate
the health thresholds + confirm the component identity:

  Quadron Network status (gL0OBnq7z):
    #4 "Shuttle network status specific date" — per-shuttle network UPTIME% since ${Date}
       (uptime% = (1 - SUM(disconnect_seconds)/elapsed_seconds)*100 over shuttle_error rows with
       error_type='SHUTTLE_NETWORK_STATUS'). We set ${Date} = window start -> WINDOWED uptime.
    #2 "shuttle/day %uptime" — same, scoped to since-midnight TODAY (a recency/intraday signal).

  Component = the per-shuttle comms link (keyed by shuttle_id, QD_Shuttle_<aisle>_<unit>).
  Signal = downtime% = 100 - uptime% (higher downtime = flaky/degrading comms link).

Usage: .venv/bin/python scripts/analyze_network_primary.py [--window now-2d]
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import download_panel_csv

URL = "http://192.168.24.230/grafana/d/gL0OBnq7z/quadron-network-status"
_WINDOW_RE = re.compile(r"now-(\d+)\s*([smhdw])", re.I)
_UNIT_H = {"s": 1 / 3600.0, "m": 1 / 60.0, "h": 1.0, "d": 24.0, "w": 168.0}
_AISLE_RE = re.compile(r"shuttle[_-]?(\d+)", re.I)


def window_start_date(window: str) -> str:
    m = _WINDOW_RE.search(window or "now-2d")
    hours = (float(m.group(1)) * _UNIT_H.get(m.group(2).lower(), 24.0)) if m else 48.0
    start = _dt.datetime.now() - _dt.timedelta(hours=hours)
    return start.strftime("%Y-%m-%d %H:%M:%S")


def _aisle(sid: str):
    m = _AISLE_RE.search(str(sid))
    return f"aisle_{int(m.group(1)):02d}" if m else None


def analyze(window: str) -> None:
    date_str = window_start_date(window)
    with GrafanaSession() as gs:
        w = download_panel_csv(gs, URL, 4, frm=window, to="now", variables={"Date": date_str}).df
        t = download_panel_csv(gs, URL, 2, frm=window, to="now").df

    print(f"\n===== NETWORK uptime — window={window}  (#4 Date='{date_str}') =====")
    print(f"#4 windowed rows={len(w)} cols={list(w.columns)}")
    if w.empty or "shuttle_id" not in w.columns:
        print("no data / unexpected columns"); return
    val_col = [c for c in w.columns if c.lower() in ("value", "uptime")][0]
    w = w.copy()
    w["uptime"] = pd.to_numeric(w[val_col], errors="coerce")
    w["downtime"] = 100.0 - w["uptime"]
    w["aisle"] = w["shuttle_id"].map(_aisle)
    w = w[w["uptime"].notna()]
    print(f"shuttles (roster): {w['shuttle_id'].nunique()}")
    print("\nuptime% distribution:")
    print(w["uptime"].describe(percentiles=[.01, .05, .1, .25, .5]).to_string())
    print("\ndowntime% distribution (100-uptime):")
    print(w["downtime"].describe(percentiles=[.5, .75, .9, .95, .99]).to_string())
    print("\nworst 15 shuttles by downtime%:")
    for _, r in w.sort_values("downtime", ascending=False).head(15).iterrows():
        print(f"  {r['shuttle_id']:<20} downtime={r['downtime']:.2f}%  uptime={r['uptime']:.2f}%")
    print("\ndowntime% by aisle (mean, max, n):")
    ag = w.groupby("aisle").agg(mean_dt=("downtime", "mean"), max_dt=("downtime", "max"),
                                n=("shuttle_id", "count")).sort_values("mean_dt", ascending=False)
    print(ag.to_string())

    # today (#2) recency
    print(f"\n===== NETWORK uptime TODAY (#2 since midnight) =====")
    print(f"#2 rows={len(t)} cols={list(t.columns)}")
    if not t.empty and "shuttle_id" in t.columns:
        tv = [c for c in t.columns if c.lower() in ("value", "uptime")][0]
        t = t.copy()
        t["today_uptime"] = pd.to_numeric(t[tv], errors="coerce")
        t["today_downtime"] = 100.0 - t["today_uptime"]
        print("today downtime% distribution:")
        print(t["today_downtime"].describe(percentiles=[.5, .9, .99]).to_string())
        merged = w.merge(t[["shuttle_id", "today_downtime"]], on="shuttle_id", how="left")
        merged["delta"] = merged["today_downtime"] - merged["downtime"]
        print("\ntop 10 shuttles worse TODAY than window-average (recent degradation):")
        for _, r in merged.sort_values("delta", ascending=False).head(10).iterrows():
            print(f"  {r['shuttle_id']:<20} today={r['today_downtime']:.2f}%  window={r['downtime']:.2f}%  delta=+{r['delta']:.2f}")


def main() -> None:
    window = "now-2d"
    args = sys.argv[1:]
    if "--window" in args:
        window = args[args.index("--window") + 1]
    analyze(window)


if __name__ == "__main__":
    main()
