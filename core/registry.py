"""Module plugin registry + the base class every module implements.

A module is a self-registering plugin: importing ``modules/<name>/`` registers a
:class:`PdMModule` instance here. Adding a module requires **no edits to core/** —
the main dashboard and the runner discover modules from this registry.

The base class defines the per-module pipeline contract (fetch → features → score)
plus health-tiering helpers shared by all modules, keeping the methodology
consistent across equipment types (CLAUDE.md §6).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from core.config import Config, get_config
from core.logging_setup import get_logger

log = get_logger("registry")

# Canonical risk tiers, worst-first ordering for "worst component" rollups.
RISK_TIERS = ("critical", "warn", "watch", "ok")
_TIER_RANK = {t: i for i, t in enumerate(RISK_TIERS)}


def tier_rank(tier: str) -> int:
    """Lower rank = worse. Unknown tiers sort as best (last)."""
    return _TIER_RANK.get((tier or "ok").lower(), len(RISK_TIERS))


def worst_tier(tiers: List[str]) -> str:
    return min(tiers, key=tier_rank) if tiers else "ok"


def score_to_tier(score: float) -> str:
    """Map a 0–100 health score to a risk tier (shared default thresholds)."""
    if score >= 85:
        return "ok"
    if score >= 65:
        return "watch"
    if score >= 40:
        return "warn"
    return "critical"


@dataclass
class ComponentHealth:
    """One scored component for one PdM run — the unit written to component_health."""

    component_id: str
    component_type: str
    health_score: float
    risk_tier: str
    predicted_ttm_hours: Optional[float]
    confidence: float
    prediction_regime: str                 # 'coldstart' | 'trend'
    primary_cause: str = ""
    rca: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def clamp(self) -> "ComponentHealth":
        self.health_score = max(0.0, min(100.0, round(float(self.health_score), 2)))
        self.confidence = max(0.0, min(1.0, round(float(self.confidence), 3)))
        if self.predicted_ttm_hours is not None:
            self.predicted_ttm_hours = round(max(0.0, float(self.predicted_ttm_hours)), 2)
        return self


class HistoryReader(Protocol):
    """Read-only view of prior runs, passed to scoring for baselines/trends."""

    def component_history(self, module: str, component_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        ...

    def run_count(self, module: str) -> int:
        ...


@dataclass
class FetchBundle:
    """What a module's fetch step returns."""

    frames: Dict[str, Any] = field(default_factory=dict)        # name -> pandas DataFrame
    rows_fetched: int = 0
    panels: List[Dict[str, Any]] = field(default_factory=list)  # panel_catalog entries
    notes: Dict[str, Any] = field(default_factory=dict)


class PdMModule(ABC):
    """Base class for all equipment-health modules."""

    name: str = "base"
    title: str = "Base Module"
    component_type: str = "component"
    description: str = ""

    # ---- configuration ---------------------------------------------------- #
    def dashboards(self, cfg: Optional[Config] = None) -> Dict[str, str]:
        """Configured dashboard URLs for this module (``MODULE__*`` env keys)."""
        cfg = cfg or get_config()
        return cfg.module_dashboard_urls(self.name)

    def is_configured(self, cfg: Optional[Config] = None) -> bool:
        return bool(self.dashboards(cfg))

    def default_window(self, cfg: Optional[Config] = None) -> str:
        return (cfg or get_config()).fetch_default_window

    # ---- pipeline (implemented by each module) ---------------------------- #
    @abstractmethod
    def fetch(self, session, window: str) -> FetchBundle:
        """Pull this module's panels into DataFrames for the given window."""

    @abstractmethod
    def compute_features(self, bundle: FetchBundle) -> Dict[str, Dict[str, Any]]:
        """Return ``{component_id: feature_dict}`` (raw + derived features)."""

    @abstractmethod
    def score(
        self, features: Dict[str, Dict[str, Any]], history: HistoryReader
    ) -> List[ComponentHealth]:
        """Return per-component health, tier, TTM, confidence, regime, RCA."""


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
_REGISTRY: Dict[str, PdMModule] = {}


def register(module: PdMModule) -> PdMModule:
    if module.name in _REGISTRY:
        log.debug("module already registered", extra={"module": module.name})
        return _REGISTRY[module.name]
    _REGISTRY[module.name] = module
    log.info("module registered", extra={"module": module.name, "title": module.title})
    return module


def get_module(name: str) -> PdMModule:
    if name not in _REGISTRY:
        raise KeyError(f"Module '{name}' is not registered")
    return _REGISTRY[name]


def all_modules() -> List[PdMModule]:
    return list(_REGISTRY.values())


def module_names() -> List[str]:
    return list(_REGISTRY.keys())
