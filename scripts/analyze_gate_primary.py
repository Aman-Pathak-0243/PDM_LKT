"""Deep-dive the GATE primary so features are designed against reality (SOP step 4-5).

Quadron-gate-status (5gFdGgwnz) is the resolved primary:
  #2 "Gate status"        : full roster -> id, status(1=CLOSED/2=OPEN REQUEST INITIATED/
                            3=OPEN), aisle  (join gate -> gate_zone_mapping -> aisle_zone)
  #4 "OPEN/REQUESTED gate" : same, filtered to status 2..3 (currently mid-open / open)

The response-latency signal (minutes a gate has been stuck non-closed) is NOT projected
by #2/#4 — it is emitted as a text alert by Quadron Alerts (VxY5Zls7z) #2 subquery H:
  "<id[:18]> front_gate|rear_gate open initiated|opened for <DATEDIFF minutes> minutes".

Questions answered (decide COMPONENT identity + signals before writing module.yaml):
  1. Gate roster size + id format (front/rear split, aisle mapping).
  2. Current status distribution (how many CLOSED vs OPEN REQUEST INITIATED vs OPEN).
  3. Is #2 current-state or windowed? (row count vs window)
  4. Alerts #2: do gate messages appear? parse "for N minutes" (latency).
  5. Re-confirm QUADRON ERROR HISTORY #2 has NO gate column (mapping's claimed secondary).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import download_panel_csv

GATE = "http://192.168.24.230/grafana/d/5gFdGgwnz/quadron-gate-status"
ALERTS = "http://192.168.24.230/grafana/d/VxY5Zls7z/quadron-alerts"
QEH = "http://192.168.24.230/grafana/d/K2QzauWVz/quadron-error-history"

pd.set_option("display.width", 200); pd.set_option("display.max_columns", 40)

_GATE_MSG = re.compile(r"(front_gate|rear_gate).*?(open initiated|opened).*?for\s+(-?\d+)\s+minutes", re.I)


def main() -> None:
    with GrafanaSession() as gs:
        gate2_short = download_panel_csv(gs, GATE, 2, frm="now-2d", to="now").df
        gate2_long = download_panel_csv(gs, GATE, 2, frm="now-90d", to="now").df
        gate4 = download_panel_csv(gs, GATE, 4, frm="now-2d", to="now").df
        try:
            alerts = download_panel_csv(gs, ALERTS, 2, frm="now-2d", to="now").df
        except Exception as e:  # noqa: BLE001
            alerts = pd.DataFrame(); print("alerts fail:", e)
        try:
            qeh = download_panel_csv(gs, QEH, 2, frm="now-2d", to="now").df
        except Exception as e:  # noqa: BLE001
            qeh = pd.DataFrame(); print("qeh fail:", e)

    print("\n===== Gate status #2 — current-state vs windowed? =====")
    print("rows now-2d:", len(gate2_short), "| rows now-90d:", len(gate2_long))
    g = gate2_long if len(gate2_long) else gate2_short
    print("cols:", list(g.columns))
    if not g.empty:
        print(g.head(12).to_string(index=False))

    id_col = next((c for c in g.columns if c.lower() == "id"), None)
    st_col = next((c for c in g.columns if c.lower() == "status"), None)
    ai_col = next((c for c in g.columns if c.lower() == "aisle"), None)

    print("\n===== gate roster =====")
    if id_col:
        print("distinct gate ids:", g[id_col].nunique(), "of", len(g), "rows")
        ids = g[id_col].astype(str)
        print("sample ids:", list(ids.head(8)))
        print("id lengths:", sorted(ids.str.len().unique().tolist()))
        # front/rear split from chars 19-20 (per Alerts SQL: SUBSTRING(id,19,2)='FG')
        suff = ids.str.slice(18, 20)
        print("char[19:21] distribution (FG=front, else rear):\n", suff.value_counts().to_string())
        print("id shape (digits->N):\n", ids.map(lambda s: re.sub(r"\d", "N", s)).value_counts().head(6).to_string())
    if st_col:
        print("\nstatus distribution:\n", g[st_col].astype(str).value_counts().to_string())
    if ai_col:
        print("\naisle distribution:\n", g[ai_col].astype(str).value_counts().to_string())

    print("\n===== Gate status #4 (OPEN / OPEN-REQUEST-INITIATED subset) =====")
    print("rows:", len(gate4), "cols:", list(gate4.columns))
    if not gate4.empty:
        print(gate4.head(20).to_string(index=False))

    print("\n===== Quadron Alerts #2 — gate stuck-duration (latency) messages =====")
    print("rows:", len(alerts), "cols:", list(alerts.columns))
    if not alerts.empty:
        msg_col = next((c for c in alerts.columns if c.lower() == "message"), alerts.columns[0])
        msgs = alerts[msg_col].astype(str)
        gate_msgs = msgs[msgs.str.contains("gate", case=False, na=False)]
        print("gate-related alert messages:", len(gate_msgs))
        for m in gate_msgs.head(20):
            mm = _GATE_MSG.search(m)
            mins = mm.group(3) if mm else "?"
            print(f"   [{mins:>4} min] {m[:120]}")

    print("\n===== QUADRON ERROR HISTORY #2 — any gate column? (re-verify mapping) =====")
    print("rows:", len(qeh), "cols:", list(qeh.columns))
    print("gate/id columns?:", [c for c in qeh.columns if "gate" in c.lower()] or "NONE (shuttle-only, drop as gate source)")


if __name__ == "__main__":
    main()
