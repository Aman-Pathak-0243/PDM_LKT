"""Loads and exposes ``module.yaml`` (the LIFT module's resolved config)."""

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


def error_info(code: Any) -> Dict[str, Any]:
    """Return ``{desc, category, severity}`` for an error code (with defaults)."""
    s = spec()
    catalog = s.get("error_catalog", {})
    try:
        key = int(code)
    except (TypeError, ValueError):
        key = code
    if key in catalog:
        return catalog[key]
    return {
        "desc": f"Unknown error code {code}",
        "category": s.get("default_category", "other"),
        "severity": float(s.get("default_severity", 0.5)),
    }


def is_mechanical(category: str) -> bool:
    return category in set(spec().get("mechanical_categories", []))


def thresholds() -> Dict[str, Any]:
    return spec().get("thresholds", {})
