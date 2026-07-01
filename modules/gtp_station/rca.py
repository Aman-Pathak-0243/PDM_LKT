"""GTP STATION + SCANNER root-cause attribution (per entity type).

Scanner: ranks misread / peer / recurrence and names the dominant symptom; flags decant/
  compaction scanners as belonging to other modules; links a GS<NN>-SL<NN> scanner to its
  parent pick station.
Station: ranks discrepancy peer/absolute/recurrence/offline and names the dominant symptom;
  a station with elevated discrepancies is flagged as a candidate scanner/PTL/mechanism fault.

``cross_link_entities`` runs after both entity types are scored to add a corroboration flag
when a pick station AND its slot scanner are both flagged (same physical cause).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

_MATERIAL = 5.0

_SCANNER_LABEL = {
    "misread": "High no-read (misread) rate",
    "peer_z": "Misreads far above peer scanners",
    "recurrence": "Elevated misread across prior runs",
}
_STATION_LABEL = {
    "discrepancy_peer_z": "Discrepancies far above peer stations",
    "discrepancy_abs": "Very high pick-discrepancy rate",
    "recurrence": "Flagged across prior runs",
    "offline_persistence": "Inactive across consecutive runs",
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
    parent = feat.get("parent_station")

    cross: List[Dict[str, str]] = []
    if subtype == "decant":
        cross.append({"module": "decant_station",
                      "reason": "decant-line scan device (Module 8, Decanting Station + Scanner) surfacing in the GTP scanner feed"})
    elif subtype == "compaction":
        cross.append({"module": "compaction",
                      "reason": "compaction-line scan device surfacing in the GTP scanner feed"})
    if parent:
        cross.append({"module": "gtp_station",
                      "reason": f"slot scanner for pick station {parent} — cross-check that station's discrepancy rate"})

    material = [c for c in contributors if c["points"] >= _MATERIAL]
    if not material:
        primary = f"Reading cleanly ({mp:.1f}% misread over {int(total):,} scans)"
    else:
        top = material[0]["factor"]
        if top == "misread":
            primary = f"High no-read rate: {mp:.1f}% ({feat.get('no_read_count', 0)}/{int(total):,}) — scanner failing/dirty/mis-aimed"
        elif top == "peer_z":
            primary = f"Misread {mp:.1f}% — far above peer scanners"
        elif top == "recurrence":
            primary = f"Misread elevated across {recurrence} prior runs — persistent scanner degradation"
        else:
            primary = f"Misread {mp:.1f}%"

    rca = {
        "summary": primary,
        "entity": "scanner",
        "contributors": contributors,
        "scanner": feat.get("scanner"),
        "subtype": subtype,
        "parent_station": parent,
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
def build_station_rca(feat: Dict[str, Any], penalties: Dict[str, float], recurrence: int, consec_inactive: int) -> Tuple[str, Dict[str, Any]]:
    contributors = _contributors(penalties, _STATION_LABEL)
    count = feat.get("discrepancy_count", 0)
    dpd = feat.get("discrepancy_per_day", 0.0)
    z = feat.get("discrepancy_peer_z", 0.0)

    cross: List[Dict[str, str]] = []
    material = [c for c in contributors if c["points"] >= _MATERIAL]
    if not material:
        if feat.get("is_active") is False:
            primary = f"Station Inactive (offline) — {count} discrepancies (context, may be intentional)"
        else:
            primary = f"Nominal — {count} pick discrepancies ({dpd:.1f}/day)"
    else:
        top = material[0]["factor"]
        if top in ("discrepancy_peer_z", "discrepancy_abs"):
            primary = f"Elevated pick discrepancies: {count} ({dpd:.1f}/day, {z:+.1f}σ vs peers) — scanner/PTL/pick mechanism suspect"
            cross.append({"module": "gtp_scanner",
                          "reason": f"check this station's slot scanner(s) ({feat['component_id']}-SL*) misread rate"})
        elif top == "recurrence":
            primary = f"Discrepancies flagged across {recurrence} prior runs — persistent station degradation"
        elif top == "offline_persistence":
            primary = f"Inactive across {consec_inactive} consecutive runs — station down (verify if intentional)"
        else:
            primary = f"{count} pick discrepancies"

    rca = {
        "summary": primary,
        "entity": "station",
        "contributors": contributors,
        "station": feat.get("station"),
        "active_status": feat.get("active_status"),
        "operation_type": feat.get("operation_type"),
        "station_type": feat.get("station_type"),
        "discrepancy_count": count,
        "discrepancy_per_day": dpd,
        "short_count": feat.get("short_count"),
        "discrepancy_type_mix": feat.get("discrepancy_type_mix"),
        "discrepancy_peer_z": z,
        "recurrence_runs": recurrence,
        "consecutive_inactive": consec_inactive,
        "cross_module_flags": cross,
    }
    return primary, rca


# --------------------------------------------------------------------------- #
# Cross-entity corroboration (station <-> its slot scanner)
# --------------------------------------------------------------------------- #
def cross_link_entities(components: List[Any]) -> None:
    """Add a corroboration flag when a station AND its GS<NN>-SL<NN> scanner are both flagged."""
    scanners_by_station: Dict[str, List[Any]] = {}
    stations: Dict[str, Any] = {}
    for c in components:
        if c.component_type == "gtp_scanner":
            parent = (c.rca or {}).get("parent_station")
            if parent:
                scanners_by_station.setdefault(parent, []).append(c)
        elif c.component_type == "gtp_station":
            stations[c.component_id] = c

    for sid, station in stations.items():
        # Corroboration requires BOTH the station AND its slot scanner to be flagged (same
        # physical cause). A healthy station is not made to "corroborate" a bad scanner — the
        # scanner already carries a one-directional parent_station cross-check in its own RCA.
        if station.risk_tier == "ok":
            continue
        bad_scanners = [s for s in scanners_by_station.get(sid, []) if s.risk_tier != "ok"]
        if not bad_scanners:
            continue
        worst = min(bad_scanners, key=lambda s: s.health_score)
        note = {"module": "corroboration",
                "reason": f"scanner {worst.component_id} at {worst.rca.get('misread_pct', 0):.1f}% misread "
                          f"(tier {worst.risk_tier}) — likely a hardware fault at station {sid}"}
        station.rca.setdefault("cross_module_flags", []).append(note)
        # And point the (also-flagged) scanner back at its station's verdict.
        for s in bad_scanners:
            s.rca.setdefault("cross_module_flags", []).append(
                {"module": "corroboration",
                 "reason": f"station {sid} tier {station.risk_tier} "
                           f"({station.rca.get('discrepancy_count', 0)} discrepancies) corroborates this scanner"})
