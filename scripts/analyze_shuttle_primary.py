"""Deep-dive the SHUTTLE primaries so features are designed against reality:
errors (QUADRON ERROR HISTORY) joined to cycles (QUADRON CYCLES) -> errors/cycle,
recency, per-shuttle distribution, error-type vocabulary."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import download_panel_csv

ERR = "http://192.168.24.230/grafana/d/K2QzauWVz/quadron-error-history"
CYC = "http://192.168.24.230/grafana/d/8dDcXomVz/quadron-cycles"
DSE = "http://192.168.24.230/grafana/d/N8QvGxQIk/daily-shuttle-errors"
BTD = "http://192.168.24.230/grafana/d/VAW2nmqIz/bad-tracker-diagnosis"
ALT = "http://192.168.24.230/grafana/d/VxY5Zls7z/quadron-alerts"

pd.set_option("display.width", 170); pd.set_option("display.max_columns", 30)


def main() -> None:
    with GrafanaSession() as gs:
        err = download_panel_csv(gs, ERR, 2, frm="now-365d", to="now").df
        cyc = download_panel_csv(gs, CYC, 2, frm="now-365d", to="now").df
        try:
            dse = download_panel_csv(gs, DSE, 2, frm="now-2d", to="now").df
        except Exception as e:
            dse = pd.DataFrame(); print("DSE fail:", e)
        try:
            btd = download_panel_csv(gs, BTD, 2, frm="now-2d", to="now").df
        except Exception as e:
            btd = pd.DataFrame(); print("BTD fail:", e)
        try:
            alt = download_panel_csv(gs, ALT, 2, frm="now-2d", to="now").df
        except Exception as e:
            alt = pd.DataFrame(); print("ALT fail:", e)

    print("\n===== QUADRON ERROR HISTORY =====")
    print("rows", len(err), "cols", list(err.columns))
    err["ct"] = pd.to_datetime(err["created_time"], errors="coerce")
    print("created_time min..max:", err["ct"].min(), "..", err["ct"].max())
    print("distinct shuttle_id:", err["shuttle_id"].nunique())
    print("top shuttles by errors:\n", err["shuttle_id"].value_counts().head(8).to_string())
    tcol = "error_type" if "error_type" in err.columns else err.columns[1]
    print(f"\n{tcol} distribution (top 12):")
    for (t, d), n in err.groupby([tcol, "error_desc"]).size().sort_values(ascending=False).head(12).items():
        print(f"  {str(t)[:26]:<26} | {str(d)[:42]:<42} n={n}")

    print("\n===== QUADRON CYCLES =====")
    print("rows", len(cyc), "cols", list(cyc.columns))
    for c in ("PUTAWAY", "PICKING", "RESHUFFLING"):
        if c in cyc.columns:
            cyc[c] = pd.to_numeric(cyc[c], errors="coerce").fillna(0)
    cyc["TOTAL"] = cyc[[c for c in ("PUTAWAY", "PICKING", "RESHUFFLING") if c in cyc.columns]].sum(axis=1)
    print("distinct shuttle_id:", cyc["shuttle_id"].nunique())
    print("cycles TOTAL describe:\n", cyc["TOTAL"].describe().to_string())
    print("sample rows:\n", cyc.sort_values("TOTAL", ascending=False).head(5).to_string(index=False))

    print("\n===== JOIN errors <-> cycles =====")
    ec = err["shuttle_id"].value_counts().rename("errors").reset_index().rename(columns={"index": "shuttle_id"})
    ec.columns = ["shuttle_id", "errors"]
    j = ec.merge(cyc[["shuttle_id", "TOTAL"]], on="shuttle_id", how="outer")
    print("shuttles in errors:", err["shuttle_id"].nunique(), "| in cycles:", cyc["shuttle_id"].nunique(),
          "| joined:", j["shuttle_id"].nunique(),
          "| with both:", int(((j["errors"].notna()) & (j["TOTAL"].notna())).sum()))
    j["errors"] = j["errors"].fillna(0); j["TOTAL"] = j["TOTAL"].fillna(0)
    j["err_per_mil_cycles"] = j["errors"] / j["TOTAL"].replace(0, pd.NA) * 1e6
    print("worst by errors/Mcycle (with cycles>0):\n",
          j[j["TOTAL"] > 0].sort_values("err_per_mil_cycles", ascending=False).head(8).to_string(index=False))

    print("\n===== Daily Shuttle Errors =====")
    print("rows", len(dse), "cols", list(dse.columns))
    if len(dse):
        print(dse.head(4).to_string(index=False)[:600])

    print("\n===== Bad Tracker (shuttle_id) =====")
    if len(btd) and "shuttle_id" in btd.columns:
        s = btd.dropna(subset=["shuttle_id"])
        print("rows with shuttle_id:", len(s))
        if len(s):
            print(s["shuttle_id"].value_counts().head(6).to_string())
            if "shuttle Status Description" in btd.columns:
                print("status desc values:", btd["shuttle Status Description"].dropna().unique()[:6])

    print("\n===== Quadron Alerts #2 =====")
    print("rows", len(alt), "cols", list(alt.columns))
    if len(alt):
        print(alt.head(5).to_string(index=False)[:500])


if __name__ == "__main__":
    main()
