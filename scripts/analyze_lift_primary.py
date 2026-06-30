"""Deep-dive the LIFT primary signal so features are designed against reality.

Fetches Lift Error History (#2) + Bad Tracker (#2) + Lift Error Analysis (#2)
and reports recency, per-lift distribution, and error-code/description mix.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import download_panel_csv

LEH = "http://192.168.24.230/grafana/d/wQds52G4z/lift-error-history"
BTD = "http://192.168.24.230/grafana/d/VAW2nmqIz/bad-tracker-diagnosis"
LEA = "http://192.168.24.230/grafana/d/EqDhnQ9Sz/lift-error-analysis"

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 30)


def main() -> None:
    with GrafanaSession() as gs:
        leh = download_panel_csv(gs, LEH, 2, frm="now-30d", to="now").df
        btd = download_panel_csv(gs, BTD, 2, frm="now-2d", to="now").df
        try:
            lea = download_panel_csv(gs, LEA, 2, frm="now-2d", to="now").df
        except Exception as exc:  # noqa: BLE001
            lea = pd.DataFrame()
            print("LEA #2 fetch failed:", exc)

    print("\n===== LIFT ERROR HISTORY =====")
    print("rows:", len(leh), "| columns:", list(leh.columns))
    leh["ct"] = pd.to_datetime(leh["created_time"], errors="coerce")
    leh["ut"] = pd.to_datetime(leh["updated_timestamp"], errors="coerce")
    print("created_time min..max:", leh["ct"].min(), "..", leh["ct"].max())
    now = pd.Timestamp.utcnow().tz_localize(None)
    for label, days in [("2d", 2), ("7d", 7), ("30d", 30), ("180d", 180), ("730d", 730)]:
        cnt = (leh["ct"] >= now - pd.Timedelta(days=days)).sum()
        print(f"  rows in last {label}: {cnt}")
    print("distinct lift_id:", leh["lift_id"].nunique())
    print("top lift_id by error count:\n", leh["lift_id"].value_counts().head(10).to_string())
    print("\nerror_code -> desc (top 15 by frequency):")
    mix = leh.groupby(["error_code", "error_desc"]).size().sort_values(ascending=False).head(15)
    for (code, desc), n in mix.items():
        print(f"  code={code:<4} n={n:<6} {str(desc)[:70]}")
    # resolution time (updated - created) as an MTTR proxy
    leh["resolve_min"] = (leh["ut"] - leh["ct"]).dt.total_seconds() / 60.0
    rt = leh["resolve_min"].dropna()
    rt = rt[(rt >= 0) & (rt < 60 * 24 * 30)]
    if len(rt):
        print(f"\nresolve_min (clean): median={rt.median():.1f} p90={rt.quantile(0.9):.1f} max={rt.max():.1f}")

    print("\n===== BAD TRACKER (#2) =====")
    print("rows:", len(btd), "| columns:", list(btd.columns))
    if "lift_id" in btd.columns:
        lift_rows = btd[btd["lift_id"].notna()]
        print("rows with lift_id populated:", len(lift_rows))
        if len(lift_rows):
            print("lift_id counts:\n", lift_rows["lift_id"].value_counts().head(10).to_string())
        if "lift Status Description" in btd.columns:
            print("lift status desc values:", btd["lift Status Description"].dropna().unique()[:10])

    print("\n===== LIFT ERROR ANALYSIS (#2 task counts) =====")
    if len(lea):
        print(lea.to_string(index=False))


if __name__ == "__main__":
    main()
