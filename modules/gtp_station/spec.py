"""Loads and exposes ``module.yaml`` for the GTP STATION + SCANNER module."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

_YAML = Path(__file__).resolve().parent / "module.yaml"


@lru_cache(maxsize=1)
def spec() -> Dict[str, Any]:
    with open(_YAML, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def thresholds() -> Dict[str, Any]:
    return spec().get("thresholds", {})


def misread_panel() -> int:
    """Panel id of the per-scanner Read/NoRead misread table (#8)."""
    return int(spec()["dashboards"]["gtp_scanner_logs"].get("misread_panel", 8))


def hits_panel() -> int:
    """Panel id of the per-scanner Hits table (#4)."""
    return int(spec()["dashboards"]["gtp_scanner_logs"].get("hits_panel", 4))


def discrepancy_panel() -> int:
    """Panel id of the per-station verification_events table (#2)."""
    return int(spec()["dashboards"]["discrepancy_report_events"].get("signal_panel", 2))


def stations_panel() -> int:
    """Panel id of the station-roster Station Summary table (#2)."""
    return int(spec()["dashboards"]["gtp_stations"].get("signal_panel", 2))
