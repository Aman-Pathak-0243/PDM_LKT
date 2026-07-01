"""GATE feature extraction — per-gate current-state + response-latency signals.

The component is each physical gate (id ``aisle_<NN>_level_<NN>_<FG|RG>``). Health is
inferred from the gate table's status enum (1=CLOSED, 2=OPEN REQUEST INITIATED, 3=OPEN)
and, for non-closed gates, how many minutes it has been stuck (response latency, parsed
from Quadron Alerts). A healthy gate rests CLOSED and opens only briefly; a degrading
ACTUATOR gets caught/stuck in OPEN REQUEST INITIATED (issued an open it can't complete)
or stuck OPEN (won't return to closed). Cross-run persistence/recurrence is added in
health.py (which holds the store history); features.py is the within-snapshot view.

Every feature is documented in modules/gate/README.md.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

import pandas as pd

from core.logging_setup import get_logger
from core.registry import FetchBundle
from modules.gate.spec import thresholds

log = get_logger("gate.features")

# gate id: aisle_<NN>_level_<NN>_<FG|RG>  (FG = front gate, RG = rear gate)
_GATE_RE = re.compile(r"aisle[_-]?(\d+)_level[_-]?(\d+)_(FG|RG)", re.I)
# Quadron Alerts message: "<prefix> front_gate|rear_gate open initiated|opened for <N> minutes"
_ALERT_RE = re.compile(
    r"^\s*(\S+)\s+(front_gate|rear_gate)\s+(open initiated|opened)\s+for\s+(-?\d+)\s+minutes",
    re.I,
)


def _col(df: pd.DataFrame, *names: str) -> Optional[str]:
    lower = {c.lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def _parse_gate_id(gate_id: str) -> Dict[str, Any]:
    m = _GATE_RE.search(str(gate_id))
    if not m:
        return {"aisle": None, "level": None, "face": None}
    face = "front" if m.group(3).upper() == "FG" else "rear"
    return {"aisle": f"aisle_{int(m.group(1)):02d}", "level": int(m.group(2)), "face": face}


def _status_code(text: Any) -> Optional[int]:
    """Map the panel's status text back to the gate enum (1/2/3); None if unmapped."""
    t = str(text).strip().upper()
    if t == "CLOSED":
        return 1
    if "REQUEST" in t:            # 'OPEN REQUEST INITIATED'
        return 2
    if t == "OPEN":
        return 3
    return None


def _parse_alert_latency(alerts: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Return {gate_id: {stuck_minutes, alert_state}} parsed from Quadron Alerts #2.

    Reconstructs the gate id from the message prefix + FG/RG (the alert SQL rebuilds a
    label from SUBSTRING(id,1,18) + ' front_gate '/' rear_gate '). Non-gate rows are ignored.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if alerts is None or alerts.empty:
        return out
    msg_col = _col(alerts, "message") or (alerts.columns[0] if len(alerts.columns) else None)
    if not msg_col:
        return out
    for raw in alerts[msg_col].dropna().astype(str):
        m = _ALERT_RE.match(raw)
        if not m:
            continue
        prefix, face_word, state, mins = m.group(1), m.group(2), m.group(3), m.group(4)
        face = "FG" if face_word.lower().startswith("front") else "RG"
        gate_id = f"{prefix}{face}"          # prefix ends with '_' (18-char substring)
        try:
            minutes = max(int(mins), 0)      # DATEDIFF can be slightly negative on clock skew
        except ValueError:
            continue
        # If the same gate somehow appears twice, keep the worst (longest stuck).
        if gate_id not in out or minutes > out[gate_id]["stuck_minutes"]:
            out[gate_id] = {"stuck_minutes": minutes, "alert_state": state.lower()}
    return out


def compute_features(bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
    t = thresholds()
    grace = float(t.get("stuck_grace_minutes", 3))

    gs = bundle.frames.get("gate_status", pd.DataFrame())
    if gs is None or gs.empty:
        log.warning("no gate-status rows fetched")
        return {}

    id_col = _col(gs, "id")
    st_col = _col(gs, "status")
    ai_col = _col(gs, "aisle")
    if not id_col:
        log.warning("gate-status frame has no id column", extra={"cols": list(gs.columns)})
        return {}

    df = gs.copy()
    df = df[df[id_col].notna() & (df[id_col].astype(str).str.strip() != "")]
    df = df.drop_duplicates(subset=[id_col])
    if df.empty:
        return {}

    latency = _parse_alert_latency(bundle.frames.get("alerts", pd.DataFrame()))

    feats: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        gid = str(row[id_col]).strip()
        parsed = _parse_gate_id(gid)
        code = _status_code(row[st_col]) if st_col else None
        is_closed = code == 1
        is_open_request = code == 2
        is_open = code == 3
        is_non_closed = code in (2, 3)
        lat = latency.get(gid, {})
        stuck_minutes = float(lat.get("stuck_minutes", 0.0)) if is_non_closed else 0.0
        stuck_excess = max(stuck_minutes - grace, 0.0)

        feats[gid] = {
            "component_id": gid,
            "gate_id": gid,
            "aisle": parsed["aisle"] or (f"aisle_{str(row[ai_col]).strip()}" if ai_col and pd.notna(row.get(ai_col)) else None),
            "level": parsed["level"],
            "face": parsed["face"],
            "window": bundle.notes.get("window"),
            "status_now": (str(row[st_col]).strip() if st_col and pd.notna(row.get(st_col)) else "UNKNOWN"),
            "status_code": code,
            "is_closed": bool(is_closed),
            "is_open_request": bool(is_open_request),
            "is_open": bool(is_open),
            "is_non_closed": bool(is_non_closed),
            "status_unknown": bool(code is None),
            "stuck_minutes": round(stuck_minutes, 1),
            "stuck_excess_minutes": round(stuck_excess, 1),
            "alert_state": lat.get("alert_state"),
            "grace_minutes": grace,
        }

    # ---- roster context (within-snapshot) --------------------------------
    total = len(feats)
    non_closed_ids = [g for g, f in feats.items() if f["is_non_closed"]]
    aisle_nc: Dict[str, int] = {}
    for g in non_closed_ids:
        a = feats[g]["aisle"]
        if a:
            aisle_nc[a] = aisle_nc.get(a, 0) + 1
    for f in feats.values():
        f["total_gates"] = total
        f["system_non_closed_count"] = len(non_closed_ids)
        f["aisle_non_closed_count"] = aisle_nc.get(f["aisle"], 0) if f["aisle"] else 0

    log.info("gate features computed",
             extra={"gates": total, "non_closed": len(non_closed_ids),
                    "stuck_now": sum(1 for f in feats.values() if f["stuck_excess_minutes"] > 0),
                    "with_latency": len(latency)})
    return feats
