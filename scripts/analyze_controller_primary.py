"""CONTROLLER / COMPUTE primary-signal analysis (SOP step 4 -> threshold calibration).

Reads CPU Stats #17 (EXEC [DBA].[dbo].[getCPUDetails]) at a few windows and prints the current CPU
snapshot needed to confirm the component identity + calibrate the saturation thresholds:

  cpu_idle / cpu_sql -> utilization% = 100 - cpu_idle, SQL CPU share = cpu_sql / utilization.

The panel is CURRENT-STATE (the window does not filter the proc), so this mainly confirms the single-row
shape + current headroom; the sustained-high + trend signal is built from the store across PdM runs.

Usage: .venv/bin/python scripts/analyze_controller_primary.py [--window now-2d]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import download_panel_csv

URL = "http://192.168.24.230/grafana/d/CwTEp_GSz/cpu-stats"


def analyze(window: str) -> None:
    with GrafanaSession() as gs:
        print(f"\n===== CONTROLLER CPU (CPU Stats #17) — probing windows =====")
        for w in (window, "now-6h", "now-30d"):
            r = download_panel_csv(gs, URL, 17, frm=w, to="now").df
            if r.empty:
                print(f"  window={w:<8} rows=0"); continue
            row = r.iloc[0]
            idle = pd.to_numeric(pd.Series([row.get("cpu_idle")]), errors="coerce").iloc[0]
            sql = pd.to_numeric(pd.Series([row.get("cpu_sql")]), errors="coerce").iloc[0]
            util = 100 - idle if pd.notna(idle) else None
            share = (sql / util) if (util and pd.notna(sql) and util > 0) else None
            print(f"  window={w:<8} rows={len(r)} cols={list(r.columns)} -> "
                  f"idle={idle} sql={sql} utilization={util}% sql_share={round(share,3) if share else None}")
        print("\n(current-state: identical across windows confirms the store must provide the trend)")


def main() -> None:
    window = "now-2d"
    args = sys.argv[1:]
    if "--window" in args:
        window = args[args.index("--window") + 1]
    analyze(window)


if __name__ == "__main__":
    main()
