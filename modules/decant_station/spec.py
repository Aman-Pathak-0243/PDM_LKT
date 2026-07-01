"""Loads and exposes ``module.yaml`` for the DECANTING STATION + SCANNER module."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml

_YAML = Path(__file__).resolve().parent / "module.yaml"


@lru_cache(maxsize=1)
def spec() -> Dict[str, Any]:
    with open(_YAML, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def thresholds() -> Dict[str, Any]:
    return spec().get("thresholds", {})


def misread_panel() -> int:
    """Panel id of the per-scanner Read/NoRead misread table (GTP Scanner logs #8, shared)."""
    return int(spec()["dashboards"]["gtp_scanner_logs"].get("misread_panel", 8))


def include_subtypes() -> List[str]:
    """Scanner subtypes this module OWNS (decant/compaction) — the rest belong to gtp_station."""
    return [str(s).lower() for s in spec()["dashboards"]["gtp_scanner_logs"].get("include_subtypes", ["decant", "compaction"])]


def station_report_panel() -> int:
    """Panel id of the decant station-roster table (Decanting station report #2)."""
    return int(spec()["dashboards"]["decanting_station_report"].get("signal_panel", 2))


def cartons_panel() -> int:
    """Panel id of the per-station decanted-carton throughput table (StationWise Decanted Cartons Count #2)."""
    return int(spec()["dashboards"]["stationwise_decanted_cartons"].get("signal_panel", 2))
