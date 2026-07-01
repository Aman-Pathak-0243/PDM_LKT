"""DECANTING STATION + SCANNER root-cause attribution (per entity type).

Scanner: ranks misread / peer / recurrence and names the dominant symptom; notes the device subtype
  (decant infeed diverter for aisle N, or compaction scanner) and records that it was reconciled
  from the GTP module (Module 7) in Session 8.
Station: ranks offline-persistence / idle-recurrence and names the dominant symptom; a station idle
  while Active and the line is busy is flagged as a candidate station-down / scanner-blind, but only
  as it persists across runs. Low-signal by necessity (no live discrepancy feed) — RCA says so.

``line_level_corroboration`` runs after both entity types are scored. Decant scanners are per-aisle
and stations are operator stations (no 1:1 device mapping, unlike GTP's GS<NN>-SL<NN> <-> GS<NN>),
so it adds only a LINE-LEVEL note when both the decant scanners AND the decant stations look unhealthy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

_MATERIAL = 5.0

_SCANNER_LABEL = {
    "misread": "High no-read (misread) rate",
    "peer_z": "Misreads far above peer decant scanners",
    "recurrence": "Elevated misread across prior runs",
}
_STATION_LABEL = {
    "offline_persistence": "Inactive across consecutive runs",
    "idle_recurrence": "Idle while Active (line busy) across consecutive runs",
}


def _contributors(penalties: Dict[str, float], labels: Dict[str, str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, pts in sorted(penalties.items(), key=lambda kv: -kv[1]):
        if pts <= 0.01:
            continue
        out.append({"factor": key, "label": labels.get(key, key), "points": round(pts, 2)})
    return out


# --------------------------------------------------------------------------- #
# Scanner
# --------------------------------------------------------------------------- #
def build_scanner_rca(feat: Dict[str, Any], penalties: Dict[str, float], recurrence: int) -> Tuple[str, Dict[str, Any]]:
    contributors = _contributors(penalties, _SCANNER_LABEL)
    mp = feat.get("misread_pct", 0.0)
    total = feat.get("total_scans", 0)
    subtype = feat.get("subtype")
    aisle = feat.get("aisle")
    where = f"decant infeed diverter ({aisle})" if subtype == "decant" and aisle else \
            ("decant infeed diverter" if subtype == "decant" else
             ("compaction-line scanner" if subtype == "compaction" else "decant scan device"))

    cross: List[Dict[str, str]] = [
        {"module": "gtp_station",
         "reason": "reconciled from the GTP scanner feed in Session 8 — this decant/compaction "
                   "scan device is now owned by Module 8 (each device owned by exactly one module)"}
    ]

    material = [c for c in contributors if c["points"] >= _MATERIAL]
    if not material:
        primary = f"Reading cleanly ({mp:.2f}% misread over {int(total):,} scans) — {where}"
    else:
        top = material[0]["factor"]
        if top == "misread":
            primary = f"High no-read rate: {mp:.1f}% ({feat.get('no_read_count', 0)}/{int(total):,}) — {where} failing/dirty/mis-aimed"
        elif top == "peer_z":
            primary = f"Misread {mp:.1f}% — far above peer decant scanners ({where})"
        elif top == "recurrence":
            primary = f"Misread elevated across {recurrence} prior runs — persistent {where} degradation"
        else:
            primary = f"Misread {mp:.1f}% ({where})"

    rca = {
        "summary": primary,
        "entity": "scanner",
        "contributors": contributors,
        "scanner": feat.get("scanner"),
        "subtype": subtype,
        "aisle": aisle,
        "misread_pct": mp,
        "no_read_count": feat.get("no_read_count"),
        "total_scans": total,
        "misread_peer_z": feat.get("misread_peer_z"),
        "recurrence_runs": recurrence,
        "cross_module_flags": cross,
    }
    return primary, rca


# --------------------------------------------------------------------------- #
# Station
# --------------------------------------------------------------------------- #
def build_station_rca(feat: Dict[str, Any], penalties: Dict[str, float], consec_inactive: int, consec_idle_active: int) -> Tuple[str, Dict[str, Any]]:
    contributors = _contributors(penalties, _STATION_LABEL)
    count = feat.get("carton_count", 0)
    tpd = feat.get("throughput_per_day", 0.0)

    material = [c for c in contributors if c["points"] >= _MATERIAL]
    if not material:
        if feat.get("is_active") is False:
            primary = f"Station Inactive (offline) — {count} cartons this window (context, may be unstaffed)"
        elif feat.get("idle_while_active"):
            primary = f"Idle while Active — 0 cartons while the decant line is busy (watch if it persists)"
        else:
            primary = f"Nominal — {count} cartons decanted ({tpd:.0f}/day)"
    else:
        top = material[0]["factor"]
        if top == "offline_persistence":
            primary = f"Inactive across {consec_inactive} consecutive runs — station down (verify if intentional)"
        elif top == "idle_recurrence":
            primary = (f"Idle while Active across {consec_idle_active} consecutive runs (line busy, 0 cartons) — "
                       f"station down / scanner-blind suspect")
        else:
            primary = f"{count} cartons decanted"

    rca = {
        "summary": primary,
        "entity": "station",
        "contributors": contributors,
        "station": feat.get("station"),
        "active_status": feat.get("active_status"),
        "user": feat.get("user"),
        "carton_count": count,
        "throughput_per_day": tpd,
        "throughput_peer_z": feat.get("throughput_peer_z"),
        "idle_while_active": feat.get("idle_while_active"),
        "line_busy": feat.get("line_busy"),
        "consecutive_inactive": consec_inactive,
        "consecutive_idle_active": consec_idle_active,
        "note": "no live per-station discrepancy feed exists (discrepancy_details is frozen 2022 and "
                "has no station key) — the station verdict is coarse/low-confidence by necessity",
        "cross_module_flags": [],
    }
    return primary, rca


# --------------------------------------------------------------------------- #
# Line-level corroboration (no 1:1 scanner<->station device mapping for decant)
# --------------------------------------------------------------------------- #
def line_level_corroboration(components: List[Any]) -> None:
    """Add a line-level note when BOTH the decant scanners AND the decant stations look unhealthy in
    the same run — a decant-line issue (rather than an isolated device), since the two entity types
    share the decant line but have no per-device mapping."""
    bad_scanners = [c for c in components if c.component_type == "decant_scanner" and c.risk_tier != "ok"]
    bad_stations = [c for c in components if c.component_type == "decant_station" and c.risk_tier != "ok"]
    if not bad_scanners or not bad_stations:
        return
    worst_sc = min(bad_scanners, key=lambda c: c.health_score)
    worst_st = min(bad_stations, key=lambda c: c.health_score)
    sc_note = {"module": "corroboration",
               "reason": f"decant line also shows {len(bad_stations)} flagged station(s) "
                         f"(worst {worst_st.component_id}, tier {worst_st.risk_tier}) — possible decant-line issue"}
    st_note = {"module": "corroboration",
               "reason": f"decant line also shows {len(bad_scanners)} flagged scanner(s) "
                         f"(worst {worst_sc.component_id} at {worst_sc.rca.get('misread_pct', 0):.1f}% misread) — possible decant-line issue"}
    for c in bad_scanners:
        c.rca.setdefault("cross_module_flags", []).append(sc_note)
    for c in bad_stations:
        c.rca.setdefault("cross_module_flags", []).append(st_note)
