"""Storage abstraction: schema definitions + backend interface.

This module is the **single runtime source of truth** for the persistence schema.
``db/schema.sql`` is its MySQL twin (kept consistent by hand). All persistence in
the system flows through a :class:`StorageBackend`, so the same calling code works
whether the active backend is CSV (current) or MySQL (dormant, gated by permission).

Design goals (from CLAUDE.md §7): timestamps in UTC ISO-8601, JSON columns for
flexible metadata, an explicit longitudinal store (``component_health``), and a
shape that does not block future AI/ML, analytics, forecasting, or warehouse export.
"""

from __future__ import annotations

import datetime as _dt
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# --------------------------------------------------------------------------- #
# Column types
# --------------------------------------------------------------------------- #
INT = "int"
FLOAT = "float"
STR = "str"
BOOL = "bool"
JSON = "json"
DATETIME = "datetime"  # stored as UTC ISO-8601 string


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    pk: bool = False
    nullable: bool = True
    default: Any = None


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: Tuple[Column, ...]
    indexes: Tuple[Tuple[str, ...], ...] = ()
    unique: Tuple[Tuple[str, ...], ...] = ()

    @property
    def column_names(self) -> List[str]:
        return [c.name for c in self.columns]

    def column(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(f"{self.name} has no column '{name}'")


# --------------------------------------------------------------------------- #
# Schema — keep consistent with db/schema.sql
# --------------------------------------------------------------------------- #
TABLE_SCHEMAS: Dict[str, TableSchema] = {
    "pdm_run": TableSchema(
        "pdm_run",
        (
            Column("id", INT, pk=True, nullable=False),
            Column("run_uid", STR, nullable=False),
            Column("module", STR, nullable=False),
            Column("trigger_type", STR, nullable=False),       # manual | auto
            Column("trigger_id", STR),
            Column("data_window", STR),
            Column("started_at", DATETIME),
            Column("finished_at", DATETIME),
            Column("status", STR),                             # running|success|partial|failed
            Column("rows_fetched", INT, default=0),
            Column("components_scored", INT, default=0),
            Column("error", STR),
            Column("created_at", DATETIME, nullable=False),
        ),
        indexes=(("module", "created_at"),),
        unique=(("run_uid",),),
    ),
    "component_health": TableSchema(
        "component_health",
        (
            Column("id", INT, pk=True, nullable=False),
            Column("run_uid", STR, nullable=False),
            Column("module", STR, nullable=False),
            Column("component_id", STR, nullable=False),
            Column("component_type", STR),
            Column("health_score", FLOAT),
            Column("risk_tier", STR),                          # ok|watch|warn|critical
            Column("predicted_ttm_hours", FLOAT),
            Column("confidence", FLOAT),
            Column("prediction_regime", STR),                  # coldstart|trend
            Column("primary_cause", STR),
            Column("rca_json", JSON),
            Column("metrics_json", JSON),
            Column("created_at", DATETIME, nullable=False),
        ),
        indexes=(("module", "component_id", "created_at"),),
    ),
    "panel_catalog": TableSchema(
        "panel_catalog",
        (
            Column("id", INT, pk=True, nullable=False),
            Column("module", STR, nullable=False),
            Column("dashboard_uid", STR, nullable=False),
            Column("dashboard_name", STR),
            Column("panel_id", INT, nullable=False),
            Column("panel_title", STR),
            Column("panel_type", STR),
            Column("fields_json", JSON),
            Column("sql_text", STR),
            Column("is_signal", BOOL, default=False),
            Column("role", STR),                               # primary|secondary|none
            Column("notes", STR),
            Column("updated_at", DATETIME, nullable=False),
        ),
        unique=(("module", "dashboard_uid", "panel_id"),),
    ),
    "automation_config": TableSchema(
        "automation_config",
        (
            Column("scope", STR, pk=True, nullable=False),     # 'global' or module name
            Column("enabled", BOOL, default=False),
            Column("interval_minutes", INT, default=60),
            Column("data_window", STR),
            Column("updated_at", DATETIME, nullable=False),
        ),
    ),
    "maintenance_ack": TableSchema(
        "maintenance_ack",
        (
            Column("id", INT, pk=True, nullable=False),
            Column("module", STR, nullable=False),
            Column("component_id", STR, nullable=False),
            Column("acked_by", STR),
            Column("acked_at", DATETIME, nullable=False),
            Column("note", STR),
        ),
        indexes=(("module", "component_id"),),
    ),
    "trigger_log": TableSchema(
        "trigger_log",
        (
            Column("id", INT, pk=True, nullable=False),
            Column("trigger_id", STR, nullable=False),
            Column("trigger_type", STR),                       # manual | auto
            Column("module", STR),                             # module name or 'all'
            Column("status", STR),                             # pending|running|success|partial|failed
            Column("data_window", STR),
            Column("started_at", DATETIME),
            Column("finished_at", DATETIME),
            Column("duration_ms", INT),
            Column("records_processed", INT, default=0),
            Column("success_count", INT, default=0),
            Column("failure_count", INT, default=0),
            Column("retry_count", INT, default=0),
            Column("run_uids_json", JSON),
            Column("message", STR),
            Column("created_at", DATETIME, nullable=False),
        ),
        indexes=(("created_at",), ("trigger_type", "status")),
        unique=(("trigger_id",),),
    ),
    "event_log": TableSchema(
        "event_log",
        (
            Column("id", INT, pk=True, nullable=False),
            Column("ts", DATETIME, nullable=False),
            Column("level", STR),                              # INFO|WARNING|ERROR|...
            Column("source", STR),                             # logger / subsystem
            Column("event", STR, nullable=False),              # short event name
            Column("module", STR),
            Column("detail_json", JSON),
        ),
        indexes=(("ts",), ("level",), ("event",)),
    ),
}


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
# A filter value is either a scalar (equality) or a (op, value) tuple where op is
# one of: "=", "!=", ">", ">=", "<", "<=", "in", "like".
Filter = Dict[str, Union[Any, Tuple[str, Any]]]
OrderBy = Optional[Tuple[str, str]]  # (column, "asc"|"desc")

_VALID_OPS = {"=", "!=", ">", ">=", "<", "<=", "in", "like"}


def normalise_filter(filters: Optional[Filter]) -> List[Tuple[str, str, Any]]:
    """Expand a filter dict into ``[(column, op, value), ...]`` triples."""
    out: List[Tuple[str, str, Any]] = []
    if not filters:
        return out
    for col, cond in filters.items():
        if isinstance(cond, tuple) and len(cond) == 2 and cond[0] in _VALID_OPS:
            out.append((col, cond[0], cond[1]))
        else:
            out.append((col, "=", cond))
    return out


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
@dataclass
class DatasetStat:
    table: str
    record_count: int
    size_bytes: int
    last_modified: Optional[str]   # UTC ISO-8601 or None
    location: str                  # file path or db identifier


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    """Current time as a UTC ISO-8601 string (millisecond precision)."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


def new_uid() -> str:
    return uuid.uuid4().hex


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def from_json(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


# --------------------------------------------------------------------------- #
# Backend interface
# --------------------------------------------------------------------------- #
class StorageBackend(ABC):
    """Table-oriented persistence interface (CSV today, MySQL when permitted)."""

    backend_name: str = "abstract"

    @abstractmethod
    def init_schema(self) -> None:
        """Create tables/datasets idempotently."""

    @abstractmethod
    def insert(self, table: str, rows: Sequence[Dict[str, Any]]) -> List[int]:
        """Insert rows; return assigned integer ids (in input order)."""

    @abstractmethod
    def select(
        self,
        table: str,
        filters: Optional[Filter] = None,
        order_by: OrderBy = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def count(self, table: str, filters: Optional[Filter] = None) -> int:
        ...

    @abstractmethod
    def delete(self, table: str, filters: Optional[Filter]) -> int:
        """Delete matching rows; return number deleted. ``None``/empty deletes all."""

    @abstractmethod
    def distinct(self, table: str, column: str, filters: Optional[Filter] = None) -> List[Any]:
        ...

    @abstractmethod
    def upsert(self, table: str, key_cols: Sequence[str], row: Dict[str, Any]) -> None:
        """Insert or update a single row matched on ``key_cols``."""

    @abstractmethod
    def latest_per(
        self,
        table: str,
        group_cols: Sequence[str],
        order_col: str,
        filters: Optional[Filter] = None,
    ) -> List[Dict[str, Any]]:
        """Return the row with the greatest ``order_col`` for each group."""

    @abstractmethod
    def stats(self) -> List[DatasetStat]:
        """Per-table size/record-count/last-modified for the Storage dashboard."""

    def schema(self, table: str) -> TableSchema:
        if table not in TABLE_SCHEMAS:
            raise KeyError(f"Unknown table '{table}'")
        return TABLE_SCHEMAS[table]
