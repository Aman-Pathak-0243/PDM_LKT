"""Loads and exposes ``module.yaml`` for the SHUTTLE module."""

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


def error_info(error_type: Any, error_desc: str = "") -> Dict[str, Any]:
    """Resolve ``{category, severity}`` from error_type, with error_desc keyword
    overrides taking precedence (desc carries the specific failure mode)."""
    s = spec()
    desc = (error_desc or "").upper()
    for ov in s.get("desc_overrides", []) or []:
        if str(ov["match"]).upper() in desc:
            return {"category": ov["category"], "severity": float(ov["severity"])}
    catalog = s.get("error_catalog", {})
    if error_type in catalog:
        return catalog[error_type]
    return {"category": s.get("default_category", "other"),
            "severity": float(s.get("default_severity", 0.55))}


def is_mechanical(category: str) -> bool:
    return category in set(spec().get("mechanical_categories", []))


def thresholds() -> Dict[str, Any]:
    return spec().get("thresholds", {})
