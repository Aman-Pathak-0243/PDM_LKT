"""Storage Management operations: export, delete, archive, restore.

Filters reuse the storage filter spec. Exports support CSV / JSON / Excel (SQL is
offered only when the MySQL backend is live). Deletes and archives are always
logged to the audit trail.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from core.audit import record_event
from core.config import get_config
from core.storage import get_storage
from core.storage.base import TABLE_SCHEMAS, now_iso, to_json

# Column used for date-range filtering per table.
DATE_COL = {
    "pdm_run": "created_at",
    "component_health": "created_at",
    "trigger_log": "created_at",
    "event_log": "ts",
    "maintenance_ack": "acked_at",
    "panel_catalog": "updated_at",
    "automation_config": "updated_at",
}


def _exports_dir() -> Path:
    d = get_config().data_dir / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _archive_dir() -> Path:
    d = get_config().data_dir / "archive"
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_filters(
    table: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    trigger_id: Optional[str] = None,
    module: Optional[str] = None,
) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    col = DATE_COL.get(table)
    if col and date_from:
        filters[col] = (">=", date_from)
    if col and date_to:
        # If both bounds given, combine via two-pass (storage supports one op/col),
        # so we encode the upper bound by post-filtering in the caller when needed.
        filters.setdefault(col, (">=", date_from or ""))
    if trigger_id and "trigger_id" in TABLE_SCHEMAS[table].column_names:
        filters["trigger_id"] = trigger_id
    if module and "module" in TABLE_SCHEMAS[table].column_names:
        filters["module"] = module
    return filters


def _select(table: str, date_from, date_to, trigger_id, module) -> List[Dict[str, Any]]:
    storage = get_storage()
    col = DATE_COL.get(table)
    filters: Dict[str, Any] = {}
    if trigger_id and "trigger_id" in TABLE_SCHEMAS[table].column_names:
        filters["trigger_id"] = trigger_id
    if module and "module" in TABLE_SCHEMAS[table].column_names:
        filters["module"] = module
    if col and date_from:
        filters[col] = (">=", date_from)
    rows = storage.select(table, filters or None)
    if col and date_to:  # upper bound applied in Python (one op/col limit)
        rows = [r for r in rows if (r.get(col) or "") <= date_to]
    return rows


def export(
    table: str,
    fmt: str = "csv",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    trigger_id: Optional[str] = None,
    module: Optional[str] = None,
) -> Tuple[str, bytes, str]:
    """Return (filename, content_bytes, media_type) for a filtered export."""
    if table not in TABLE_SCHEMAS:
        raise ValueError(f"unknown table '{table}'")
    rows = _select(table, date_from, date_to, trigger_id, module)
    if fmt.lower() in ("csv", "xlsx", "excel"):
        # Tabular formats: serialise dict/list cells as valid JSON strings.
        rows = [
            {k: (to_json(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()}
            for r in rows
        ]
    df = pd.DataFrame(rows, columns=TABLE_SCHEMAS[table].column_names)
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    base = f"{table}_{ts}"
    fmt = fmt.lower()

    if fmt == "csv":
        content = df.to_csv(index=False).encode("utf-8")
        media, ext = "text/csv", "csv"
    elif fmt == "json":
        content = json.dumps(rows, indent=2, default=str).encode("utf-8")
        media, ext = "application/json", "json"
    elif fmt in ("xlsx", "excel"):
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as xl:
            df.to_excel(xl, index=False, sheet_name=table[:31])
        content = buf.getvalue()
        media, ext = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        )
    else:
        raise ValueError(f"unsupported format '{fmt}' (use csv|json|xlsx)")

    record_event(
        "storage_export", source="storage",
        detail={"table": table, "fmt": ext, "rows": len(rows),
                "date_from": date_from, "date_to": date_to, "trigger_id": trigger_id},
    )
    return f"{base}.{ext}", content, media


def delete(
    table: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    trigger_id: Optional[str] = None,
    module: Optional[str] = None,
    confirm: bool = False,
) -> int:
    """Delete matching rows (requires confirm=True). Logged. Returns count."""
    if not confirm:
        raise ValueError("delete requires confirm=true")
    if table not in TABLE_SCHEMAS:
        raise ValueError(f"unknown table '{table}'")
    storage = get_storage()
    rows = _select(table, date_from, date_to, trigger_id, module)
    deleted = 0
    schema = TABLE_SCHEMAS[table]
    if "id" in schema.column_names:  # delete precisely by id
        ids = [r["id"] for r in rows if r.get("id") is not None]
        for rid in ids:
            deleted += storage.delete(table, {"id": rid})
    else:
        # No surrogate key (e.g. automation_config) — delete by the given filters.
        filt: Dict[str, Any] = {}
        if module:
            filt["module"] = module
        deleted = storage.delete(table, filt or None)
    record_event(
        "storage_delete", level="WARNING", source="storage",
        detail={"table": table, "deleted": deleted, "date_from": date_from,
                "date_to": date_to, "trigger_id": trigger_id, "module": module},
    )
    return deleted


def archive(table: str, before: str) -> Dict[str, Any]:
    """Move rows older than ``before`` (on the table's date column) to an archive
    CSV and delete them from the active store. Returns a summary."""
    if table not in TABLE_SCHEMAS:
        raise ValueError(f"unknown table '{table}'")
    col = DATE_COL.get(table)
    if not col:
        raise ValueError(f"table '{table}' has no date column to archive on")
    storage = get_storage()
    old = [r for r in storage.select(table) if (r.get(col) or "") < before]
    if not old:
        return {"table": table, "archived": 0, "file": None}
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = _archive_dir() / f"{table}_before_{before[:10]}_{ts}.csv"
    pd.DataFrame(old, columns=TABLE_SCHEMAS[table].column_names).to_csv(path, index=False)
    deleted = 0
    if "id" in TABLE_SCHEMAS[table].column_names:
        for r in old:
            deleted += storage.delete(table, {"id": r["id"]})
    record_event(
        "storage_archive", level="WARNING", source="storage",
        detail={"table": table, "archived": deleted, "before": before, "file": str(path)},
    )
    return {"table": table, "archived": deleted, "file": str(path)}


def list_archives() -> List[Dict[str, Any]]:
    out = []
    for p in sorted(_archive_dir().glob("*.csv")):
        st = p.stat()
        out.append(
            {
                "file": p.name,
                "path": str(p),
                "size_bytes": st.st_size,
                "modified": _dt.datetime.fromtimestamp(
                    st.st_mtime, tz=_dt.timezone.utc
                ).isoformat(timespec="seconds"),
            }
        )
    return out


def restore(file_name: str) -> Dict[str, Any]:
    """Re-insert rows from an archive CSV back into its table."""
    path = _archive_dir() / Path(file_name).name  # prevent path traversal
    if not path.exists():
        raise FileNotFoundError(file_name)
    table = path.name.split("_before_")[0]
    if table not in TABLE_SCHEMAS:
        raise ValueError(f"cannot infer a known table from '{file_name}'")
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)
    storage = get_storage()
    rows = df.drop(columns=[c for c in ["id"] if c in df.columns], errors="ignore").to_dict("records")
    ids = storage.insert(table, rows)
    record_event(
        "storage_restore", source="storage",
        detail={"table": table, "restored": len(ids), "file": file_name},
    )
    return {"table": table, "restored": len(ids)}
