"""CSV storage backend (active backend until MySQL permission is granted).

Each table is a CSV file under ``<DATA_DIR>/store/<table>.csv`` with a header row
matching the schema. A sidecar ``<table>.seq`` file holds the last integer id.
Writes take an OS-level advisory lock (``fcntl.flock``) plus an in-process lock,
and are atomic (write-temp-then-rename), so concurrent manual + scheduled runs in
the same process — or a stray second process — cannot corrupt a file.

All values are stored as strings; types are coerced on read using
:data:`core.storage.base.TABLE_SCHEMAS`, so the data round-trips faithfully and
the calling code is identical to what the MySQL backend will expose.
"""

from __future__ import annotations

import csv
import datetime as _dt
import fcntl
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from core.storage.base import (
    BOOL,
    DATETIME,
    FLOAT,
    INT,
    JSON,
    TABLE_SCHEMAS,
    DatasetStat,
    Filter,
    OrderBy,
    StorageBackend,
    TableSchema,
    from_json,
    normalise_filter,
    to_json,
)


class CsvBackend(StorageBackend):
    backend_name = "csv"

    def __init__(self, data_dir: Path):
        self.store_dir = Path(data_dir) / "store"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {
            t: threading.Lock() for t in TABLE_SCHEMAS
        }

    # ----- paths ---------------------------------------------------------- #
    def _path(self, table: str) -> Path:
        return self.store_dir / f"{table}.csv"

    def _seq_path(self, table: str) -> Path:
        return self.store_dir / f"{table}.seq"

    def _lockfile(self, table: str) -> Path:
        return self.store_dir / f"{table}.lock"

    # ----- value (de)serialisation ---------------------------------------- #
    @staticmethod
    def _serialise(value: Any, ctype: str) -> str:
        if value is None:
            return ""
        if ctype == BOOL:
            # Interpret string boolean literals symmetrically with ``_coerce`` so a
            # value round-tripped as the string "false" (archive/restore, or a raw
            # CSV re-insert) is not silently flipped to "true" by ``bool("false")``.
            if isinstance(value, str):
                return "true" if value.strip().lower() in {"true", "1", "yes", "on"} else "false"
            return "true" if bool(value) else "false"
        if ctype == JSON:
            return to_json(value)
        return str(value)

    @staticmethod
    def _coerce(value: str, ctype: str) -> Any:
        if value == "" or value is None:
            return None
        if ctype == INT:
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return None
        if ctype == FLOAT:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        if ctype == BOOL:
            return str(value).strip().lower() in {"true", "1", "yes", "on"}
        if ctype == JSON:
            return from_json(value)
        return value  # STR / DATETIME stored/returned as string

    def _coerce_row(self, schema: TableSchema, raw: Dict[str, str]) -> Dict[str, Any]:
        return {c.name: self._coerce(raw.get(c.name, ""), c.type) for c in schema.columns}

    # ----- low-level file IO (caller holds the lock) ---------------------- #
    def _read_raw(self, table: str) -> List[Dict[str, str]]:
        path = self._path(table)
        if not path.exists() or path.stat().st_size == 0:
            return []
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)
        return df.to_dict("records")  # type: ignore[return-value]

    def _write_all(self, table: str, schema: TableSchema, rows: List[Dict[str, str]]) -> None:
        """Atomically rewrite the whole table file (used by delete/upsert)."""
        tmp = self._path(table).with_suffix(".csv.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=schema.column_names)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in schema.column_names})
        os.replace(tmp, self._path(table))

    def _max_existing_id(self, table: str) -> int:
        """Largest integer id currently in the table file (0 if none). Used to
        self-heal a missing/corrupt ``.seq`` so ids can never collide after a crash."""
        top = 0
        for raw in self._read_raw(table):
            try:
                top = max(top, int(float(raw.get("id", "") or 0)))
            except (TypeError, ValueError):
                continue
        return top

    def _next_ids(self, table: str, n: int) -> List[int]:
        seq = self._seq_path(table)
        last: Optional[int] = None
        if seq.exists():
            try:
                last = int(seq.read_text().strip())
            except ValueError:
                last = None
        if last is None:
            # Missing/corrupt counter (e.g. a crash between the row append and the
            # .seq write, or a lost .seq) — recompute from the data so we never
            # reissue an id that already exists.
            last = self._max_existing_id(table)
        ids = list(range(last + 1, last + 1 + n))
        # Atomic write (temp + os.replace) so a crash mid-write cannot truncate the
        # counter to an empty/partial value.
        tmp = seq.with_suffix(".seq.tmp")
        tmp.write_text(str(last + n))
        os.replace(tmp, seq)
        return ids

    # ----- locking -------------------------------------------------------- #
    class _FileLock:
        def __init__(self, backend: "CsvBackend", table: str):
            self.backend, self.table = backend, table
            self._tl = backend._locks[table]
            self._fh = None

        def __enter__(self):
            self._tl.acquire()
            try:
                self._fh = open(self.backend._lockfile(self.table), "w")
                fcntl.flock(self._fh, fcntl.LOCK_EX)
            except BaseException:
                # If the OS-lock setup fails (fd/disk exhaustion), never leak the
                # in-process lock — release it and re-raise.
                if self._fh is not None:
                    self._fh.close()
                    self._fh = None
                self._tl.release()
                raise
            return self

        def __exit__(self, *exc):
            try:
                if self._fh is not None:
                    fcntl.flock(self._fh, fcntl.LOCK_UN)
                    self._fh.close()
                    self._fh = None
            finally:
                self._tl.release()

    def _locked(self, table: str) -> "_FileLock":
        return CsvBackend._FileLock(self, table)

    # ----- StorageBackend API --------------------------------------------- #
    def init_schema(self) -> None:
        for table, schema in TABLE_SCHEMAS.items():
            path = self._path(table)
            if not path.exists():
                with self._locked(table):
                    if not path.exists():
                        self._write_all(table, schema, [])

    def insert(self, table: str, rows: Sequence[Dict[str, Any]]) -> List[int]:
        if not rows:
            return []
        schema = self.schema(table)
        has_id = any(c.pk and c.type == INT for c in schema.columns)
        with self._locked(table):
            ids = self._next_ids(table, len(rows)) if has_id else []
            # Append without rewriting the whole file.
            path = self._path(table)
            new_file = not path.exists() or path.stat().st_size == 0
            with open(path, "a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=schema.column_names)
                if new_file:
                    writer.writeheader()
                for i, row in enumerate(rows):
                    record = dict(row)
                    if has_id:
                        record["id"] = ids[i]
                    writer.writerow(
                        {c.name: self._serialise(record.get(c.name), c.type) for c in schema.columns}
                    )
        return ids

    def _filtered_rows(self, table: str) -> List[Dict[str, Any]]:
        schema = self.schema(table)
        return [self._coerce_row(schema, r) for r in self._read_raw(table)]

    @staticmethod
    def _matches(row: Dict[str, Any], triples) -> bool:
        for col, op, val in triples:
            cell = row.get(col)
            if op == "=":
                ok = cell == val
            elif op == "!=":
                ok = cell != val
            elif op == "in":
                ok = cell in val
            elif op == "like":
                ok = cell is not None and str(val).lower() in str(cell).lower()
            elif cell is None:
                ok = False
            elif op == ">":
                ok = cell > val
            elif op == ">=":
                ok = cell >= val
            elif op == "<":
                ok = cell < val
            elif op == "<=":
                ok = cell <= val
            else:
                ok = False
            if not ok:
                return False
        return True

    def select(
        self,
        table: str,
        filters: Optional[Filter] = None,
        order_by: OrderBy = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        triples = normalise_filter(filters)
        with self._locked(table):
            rows = self._filtered_rows(table)
        if triples:
            rows = [r for r in rows if self._matches(r, triples)]
        if order_by:
            col, direction = order_by
            reverse = (direction or "asc").lower() == "desc"
            sec = "id" if any(c.name == "id" for c in self.schema(table).columns) else None
            present = [r for r in rows if r.get(col) is not None]
            missing = [r for r in rows if r.get(col) is None]
            # Deterministic tiebreak on the surrogate id (so equal-timestamp rows
            # order by insertion, newest-first under desc); NULLs always sort last
            # regardless of direction.
            present.sort(
                key=lambda r: (r.get(col), r.get(sec) if sec is not None else 0),
                reverse=reverse,
            )
            rows = present + missing
        if limit is not None:
            rows = rows[:limit]
        return rows

    def count(self, table: str, filters: Optional[Filter] = None) -> int:
        if not filters:
            with self._locked(table):
                return len(self._read_raw(table))
        return len(self.select(table, filters))

    def delete(self, table: str, filters: Optional[Filter]) -> int:
        schema = self.schema(table)
        triples = normalise_filter(filters)
        with self._locked(table):
            raw = self._read_raw(table)
            if not triples:
                self._write_all(table, schema, [])
                return len(raw)
            coerced = [self._coerce_row(schema, r) for r in raw]
            keep_raw, deleted = [], 0
            for raw_row, row in zip(raw, coerced):
                if self._matches(row, triples):
                    deleted += 1
                else:
                    keep_raw.append(raw_row)
            if deleted:
                self._write_all(table, schema, keep_raw)
            return deleted

    def distinct(self, table: str, column: str, filters: Optional[Filter] = None) -> List[Any]:
        rows = self.select(table, filters)
        seen, out = set(), []
        for r in rows:
            v = r.get(column)
            if v not in seen:
                seen.add(v)
                out.append(v)
        return out

    def upsert(self, table: str, key_cols: Sequence[str], row: Dict[str, Any]) -> None:
        schema = self.schema(table)
        has_id = any(c.pk and c.type == INT for c in schema.columns)
        with self._locked(table):
            raw = self._read_raw(table)
            coerced = [self._coerce_row(schema, r) for r in raw]
            idx = None
            for i, existing in enumerate(coerced):
                if all(existing.get(k) == row.get(k) for k in key_cols):
                    idx = i
                    break
            if idx is not None:
                merged = dict(coerced[idx])
                merged.update(row)
                raw[idx] = {
                    c.name: self._serialise(merged.get(c.name), c.type) for c in schema.columns
                }
                self._write_all(table, schema, raw)
            else:
                new_row = dict(row)
                if has_id:
                    new_row["id"] = self._next_ids(table, 1)[0]
                raw.append(
                    {c.name: self._serialise(new_row.get(c.name), c.type) for c in schema.columns}
                )
                self._write_all(table, schema, raw)

    def latest_per(
        self,
        table: str,
        group_cols: Sequence[str],
        order_col: str,
        filters: Optional[Filter] = None,
    ) -> List[Dict[str, Any]]:
        rows = self.select(table, filters, order_by=(order_col, "asc"))
        latest: Dict[tuple, Dict[str, Any]] = {}
        for r in rows:
            key = tuple(r.get(c) for c in group_cols)
            latest[key] = r  # ascending order => last write wins = greatest order_col
        return list(latest.values())

    def stats(self) -> List[DatasetStat]:
        out: List[DatasetStat] = []
        for table in TABLE_SCHEMAS:
            path = self._path(table)
            if path.exists():
                size = path.stat().st_size
                with self._locked(table):
                    count = len(self._read_raw(table))
                mtime = _dt.datetime.fromtimestamp(
                    path.stat().st_mtime, tz=_dt.timezone.utc
                ).isoformat(timespec="seconds")
            else:
                size, count, mtime = 0, 0, None
            out.append(
                DatasetStat(
                    table=table,
                    record_count=count,
                    size_bytes=size,
                    last_modified=mtime,
                    location=str(path),
                )
            )
        return out
