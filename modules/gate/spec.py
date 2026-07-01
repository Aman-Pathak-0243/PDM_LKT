"""Loads and exposes ``module.yaml`` for the GATE module."""

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
    """Panel id of the gate-status roster (#2)."""
    return int(spec()["dashboards"]["quadron_gate_status"].get("signal_panel", 2))


def context_panel() -> int:
    """Panel id of the OPEN/REQUESTED subset (#4)."""
    return int(spec()["dashboards"]["quadron_gate_status"].get("context_panel", 4))


def alerts_panel() -> int:
    """Panel id of the Quadron Alerts message table (#2) — parsed for gate latency."""
    return int(spec()["dashboards"]["quadron_alerts"].get("signal_panel", 2))
