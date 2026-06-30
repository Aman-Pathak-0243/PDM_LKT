"""Loads and exposes ``module.yaml`` for the CONVEYOR module."""

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


def zone_panels() -> Dict[int, str]:
    """Return ``{panel_id: zone}`` for the per-zone timeseries panels."""
    raw = spec()["dashboards"]["conveyor_zone_count"].get("zone_panels", {})
    return {int(k): str(v) for k, v in raw.items()}
