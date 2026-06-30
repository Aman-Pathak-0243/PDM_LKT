"""Loads and exposes ``module.yaml`` for the TRACKER module."""

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


def signal_panel() -> int:
    """Panel id of the current bad-tracker set (#2)."""
    return int(spec()["dashboards"]["bad_tracker_diagnosis"].get("signal_panel", 2))
