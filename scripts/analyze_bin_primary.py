"""Deep-dive the BIN / TOTE-MECHANICAL primaries so features are designed against reality.

Component identity question: is it the bin LOCATION (slot address) that recurs? Decide from
real data (recurrence distribution + location format + windowing behaviour).

Sources probed:
  Bin Blocked Statistics (wNp3FGZNk11) — TIME-WINDOWED ($__timeFrom/$__timeTo):
    #14 "Repeated Location for Bin Block" -> location, COUNT (the recurrence signal)
    #2  "Bin Blocked Data"                -> per-block rows (tracker, container, shuttle, aisle, level, time)
    #6  "Total Bin Blocked" (scalar), #8 "Aisle wise bin Blocked"
  Bin blocked (GOqISik4k) #2 "Bin Blocked report" -> CURRENT blocked set (status=0) with location detail
  Bin Block History (hIVZMtGVz) #2 -> shuttle_command status=10 source/destination bins + bay/zone/date
  Aggregate Error Report (DaVyCb9Hz) #2 -> re-confirm NO location column (drop as bin source)

Questions: windowed vs current-state? recurrence distribution (max repeats)? location format?
current-block count? does history dashboard carry usable per-location events?
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import download_panel_csv

STATS = "http://192.168.24.230/grafana/d/wNp3FGZNk11/bin-blocked-statistics"
TILT = "http://192.168.24.230/grafana/d/GOqISik4k/bin-blocked-i-e-tote-tilted"
HIST = "http://192.168.24.230/grafana/d/hIVZMtGVz/bin-block-history"
AER = "http://192.168.24.230/grafana/d/DaVyCb9Hz/aggregate-error-report"

pd.set_option("display.width", 200); pd.set_option("display.max_columns", 40)


def loc_col(df):
    for c in df.columns:
        if "location" in c.lower():
            return c
    return None


def main() -> None:
    with GrafanaSession() as gs:
        # windowed? repeated-location #14 at three windows
        rep_2d = download_panel_csv(gs, STATS, 14, frm="now-2d", to="now").df
        rep_30d = download_panel_csv(gs, STATS, 14, frm="now-30d", to="now").df
        rep_365 = download_panel_csv(gs, STATS, 14, frm="now-365d", to="now").df
        data_30 = download_panel_csv(gs, STATS, 2, frm="now-30d", to="now").df
        total_30 = download_panel_csv(gs, STATS, 6, frm="now-30d", to="now").df
        aisle_30 = download_panel_csv(gs, STATS, 8, frm="now-30d", to="now").df
        tilt_now = download_panel_csv(gs, TILT, 2, frm="now-2d", to="now").df
        try:
            hist_30 = download_panel_csv(gs, HIST, 2, frm="now-30d", to="now").df
        except Exception as e:  # noqa: BLE001
            hist_30 = pd.DataFrame(); print("hist fail:", e)
        try:
            aer = download_panel_csv(gs, AER, 2, frm="now-30d", to="now").df
        except Exception as e:  # noqa: BLE001
            aer = pd.DataFrame(); print("aer fail:", e)

    print("\n===== #14 Repeated Location for Bin Block — windowed? =====")
    print("rows now-2d:", len(rep_2d), "| now-30d:", len(rep_30d), "| now-365d:", len(rep_365))
    rep = rep_365 if len(rep_365) else (rep_30d if len(rep_30d) else rep_2d)
    print("cols:", list(rep.columns))
    if not rep.empty:
        cnt_col = next((c for c in rep.columns if "count" in c.lower()), rep.columns[-1])
        lc = loc_col(rep)
        print("distinct locations:", rep[lc].nunique() if lc else "?", "of", len(rep), "rows")
        print("count distribution:", rep[cnt_col].describe().to_dict() if cnt_col else "?")
        print("top repeated locations:\n", rep.sort_values(cnt_col, ascending=False).head(12).to_string(index=False))
        if lc:
            shapes = rep[lc].astype(str).map(lambda s: re.sub(r"\d", "N", s))
            print("\nlocation shape patterns:\n", shapes.value_counts().head(6).to_string())
            recur = (rep[cnt_col] > 1).sum() if cnt_col else 0
            print(f"\nlocations blocked >1x (recurring): {recur} / {len(rep)}")

    print("\n===== #2 Bin Blocked Data (window now-30d) =====")
    print("rows:", len(data_30), "cols:", list(data_30.columns))
    if not data_30.empty:
        print(data_30.head(5).to_string(index=False))
        tcol = next((c for c in data_30.columns if c.lower() in ("blocked time","blockedtime","blocked_time")), None)
        if tcol:
            ts = pd.to_datetime(data_30[tcol], errors="coerce")
            print("blocked-time min..max:", ts.min(), "..", ts.max())

    print("\n===== #6 Total / #8 Aisle-wise (now-30d) =====")
    print("total:", None if total_30.empty else total_30.iloc[0].to_dict())
    print("aisle-wise:", None if aisle_30.empty else aisle_30.to_dict("records"))

    print("\n===== Bin blocked (tote tilted) #2 — CURRENT blocked set =====")
    print("rows:", len(tilt_now), "cols:", list(tilt_now.columns))
    if not tilt_now.empty:
        lc = loc_col(tilt_now)
        print("distinct locations:", tilt_now[lc].nunique() if lc else "?")
        print(tilt_now.head(6).to_string(index=False)[:700])

    print("\n===== Bin Block History #2 (now-30d) =====")
    print("rows:", len(hist_30), "cols:", list(hist_30.columns))
    if not hist_30.empty:
        print(hist_30.head(4).to_string(index=False)[:700])

    print("\n===== Aggregate Error Report #2 — any location? (re-verify) =====")
    print("rows:", len(aer), "cols:", list(aer.columns))
    print("location cols?:", [c for c in aer.columns if "location" in c.lower()] or "NONE (shuttle/lift errors, drop)")


if __name__ == "__main__":
    main()
