"""Loads and exposes ``module.yaml`` for the CONTROLLER / COMPUTE module."""

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


def cpu_panel() -> int:
    """Panel id of the CPU Utilisation table (#17, EXEC getCPUDetails)."""
    return int(spec()["dashboards"]["cpu_stats"].get("cpu_panel", 17))
