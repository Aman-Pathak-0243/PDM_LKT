"""Deep-dive the TRACKER primary so features are designed against reality.

Bad Tracker Diagnosis #2 ("Bad Tracker") is the core signal: the CURRENT set of
mislocated totes — each row is a tracker (tote position tag) stuck at an anomalous
grid location (entity type 11), with the shuttle/lift that last errored on it.

Questions answered (decide the COMPONENT identity — tracker vs location vs aisle):
  1. Is the panel current-state or windowed?  (does row count change with window?)
  2. tracker recurrence: do tracker IDs repeat within a snapshot?
  3. location clustering: do locations repeat?  what is the location format?
  4. aisle distribution; shuttle_id / lift_id association; status / task_type mix.
  5. Aggregate Error Report: does it actually carry tracker/location? (mapping check)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re

import pandas as pd

from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import download_panel_csv

BTD = "http://192.168.24.230/grafana/d/VAW2nmqIz/bad-tracker-diagnosis"
AER = "http://192.168.24.230/grafana/d/DaVyCb9Hz/aggregate-error-report"

pd.set_option("display.width", 180); pd.set_option("display.max_columns", 40)

_AISLE_RE = re.compile(r"aisle[_-]?(\d+)", re.I)


def aisle_of(loc: str):
    m = _AISLE_RE.search(str(loc))
    return f"aisle_{int(m.group(1)):02d}" if m else None


def main() -> None:
    with GrafanaSession() as gs:
        bt_short = download_panel_csv(gs, BTD, 2, frm="now-2d", to="now").df
        bt_long = download_panel_csv(gs, BTD, 2, frm="now-90d", to="now").df
        try:
            aer = download_panel_csv(gs, AER, 2, frm="now-90d", to="now").df
        except Exception as e:  # noqa: BLE001
            aer = pd.DataFrame(); print("AER fail:", e)

    print("\n===== Bad Tracker #2 — current-state vs windowed? =====")
    print("rows now-2d:", len(bt_short), "| rows now-90d:", len(bt_long))
    print("cols:", list(bt_long.columns))
    bt = bt_long if len(bt_long) else bt_short

    if "created_time" in bt.columns:
        ct = pd.to_datetime(bt["created_time"], errors="coerce")
        print("created_time min..max:", ct.min(), "..", ct.max())

    print("\n===== tracker recurrence (within snapshot) =====")
    if "tracker" in bt.columns:
        vc = bt["tracker"].value_counts()
        print("distinct trackers:", bt["tracker"].nunique(), "of", len(bt), "rows")
        print("max repeats of one tracker:", int(vc.max()) if len(vc) else 0)
        print("trackers appearing >1x:", int((vc > 1).sum()))

    print("\n===== location clustering =====")
    if "location" in bt.columns:
        lc = bt["location"].value_counts()
        print("distinct locations:", bt["location"].nunique(), "of", len(bt), "rows")
        print("top locations:\n", lc.head(12).to_string())
        bt["_aisle"] = bt["location"].map(aisle_of)
        print("\nby aisle:\n", bt["_aisle"].value_counts(dropna=False).to_string())
        # location prefix shape (strip trailing index)
        shapes = bt["location"].map(lambda s: re.sub(r"\d+", "N", str(s)))
        print("\nlocation shape patterns:\n", shapes.value_counts().head(8).to_string())

    print("\n===== associations =====")
    for col in ("shuttle_id", "lift_id", "task_type"):
        if col in bt.columns:
            nn = bt[col].dropna()
            print(f"{col}: {len(nn)} non-null / {len(bt)}  distinct={nn.nunique()}")
            if len(nn):
                print("   top:", dict(nn.value_counts().head(5)))
    for col in ("shuttle Status Description", "lift Status Description", "status", "lift_status"):
        if col in bt.columns:
            print(f"{col} values:", list(pd.Series(bt[col].dropna().unique())[:6]))

    print("\n===== Aggregate Error Report #2 — does it carry tracker/location? =====")
    print("rows", len(aer), "cols", list(aer.columns))
    if len(aer):
        print("any tracker/location col?:",
              [c for c in aer.columns if "track" in c.lower() or "location" in c.lower()] or "NONE")
        if "robotType" in aer.columns:
            print("robotType mix:", dict(aer["robotType"].value_counts()))
        print(aer.head(4).to_string(index=False)[:500])


if __name__ == "__main__":
    main()
