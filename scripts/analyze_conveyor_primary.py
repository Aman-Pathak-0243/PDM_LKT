"""Deep-dive the CONVEYOR primary: per-zone congestion from Conveyor Zone Count.

Fetches the snapshot table (#4) + the 6 per-zone timeseries (#6,#8,#10,#12,#14,#16)
and computes congestion/saturation stats per zone, plus recency. Validates the
zone universe and the actual-vs-limit signal before the module is built.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import download_panel_csv

CZC = "http://192.168.24.230/grafana/d/lavIciTDk/conveyor-zone-count"
ZONE_PANELS = {6: "1", 8: "2", 10: "3", 12: "4", 14: "5", 16: "6"}
HT = "http://192.168.24.230/grafana/d/C8jMvAcIk/gtp-hold-transit"

pd.set_option("display.width", 170)


def main() -> None:
    window = sys.argv[1] if len(sys.argv) > 1 else "now-24h"
    with GrafanaSession() as gs:
        print("=== #4 snapshot (latest per zone) ===")
        try:
            snap = download_panel_csv(gs, CZC, 4, frm=window, to="now").df
            print("cols:", list(snap.columns)); print(snap.to_string(index=False)[:900])
        except Exception as e:
            print("snapshot fail:", str(e)[:100])

        print("\n=== per-zone timeseries congestion (window", window, ") ===")
        for pid, zone in ZONE_PANELS.items():
            try:
                df = download_panel_csv(gs, CZC, pid, frm=window, to="now").df
            except Exception as e:
                print(f"  zone {zone} (#{pid}): fetch fail {str(e)[:70]}"); continue
            if df.empty:
                print(f"  zone {zone} (#{pid}): 0 rows"); continue
            ca = pd.to_numeric(df.get("Conveyor Actual"), errors="coerce")
            cl = pd.to_numeric(df.get("Conveyor Limit"), errors="coerce")
            ba = pd.to_numeric(df.get("Buffer Actual"), errors="coerce")
            bl = pd.to_numeric(df.get("Buffer Limit"), errors="coerce")
            ratio = (ca / cl.replace(0, pd.NA)).dropna()
            bratio = (ba / bl.replace(0, pd.NA)).dropna()
            tcol = "time" if "time" in df.columns else df.columns[0]
            tmin, tmax = df[tcol].min(), df[tcol].max()
            print(f"  zone {zone} (#{pid}): rows={len(df)} | conv actual mean={ca.mean():.1f} limit={cl.dropna().iloc[-1] if len(cl.dropna()) else '?'} "
                  f"| cong mean={ratio.mean():.2f} max={ratio.max():.2f} sat>=0.9={ (ratio>=0.9).mean():.2%} "
                  f"| buf cong mean={bratio.mean():.2f} | {tmin}..{tmax}")

        print("\n=== GTP HOLD/TRANSIT (current flow stress) ===")
        for pid, name in [(2, "ON_HOLD"), (4, "Transit")]:
            try:
                df = download_panel_csv(gs, HT, pid, frm="now-2d", to="now").df
                print(f"  {name}: rows={len(df)} cols={list(df.columns)}")
            except Exception as e:
                print(f"  {name}: fail {str(e)[:60]}")


if __name__ == "__main__":
    main()
