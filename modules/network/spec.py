"""Loads and exposes ``module.yaml`` for the NETWORK / COMMS module."""

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


def _dash() -> Dict[str, Any]:
    return spec()["dashboards"]["quadron_network_status"]


def windowed_panel() -> int:
    """Panel id of the windowed per-shuttle uptime table (#4, ${Date}-scoped)."""
    return int(_dash().get("windowed_panel", 4))


def today_panel() -> int:
    """Panel id of the since-midnight-today per-shuttle uptime table (#2)."""
    return int(_dash().get("today_panel", 2))


def date_var() -> str:
    """Template-var name #4 filters on (set to the window start at fetch time)."""
    return str(_dash().get("date_var", "Date"))
