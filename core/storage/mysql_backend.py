"""MySQL storage backend — DORMANT.

This is a faithful, drop-in implementation of :class:`StorageBackend` for MySQL,
kept ready so the system can switch over with a single config change once the user
grants permission and shares the real database name. **It is never instantiated
while ``STORAGE_BACKEND=csv``** (the factory only builds it for ``mysql``), and even
then it connects lazily — no engine is created at import time.

Behaviour matches the CSV backend exactly: datetimes are stored as ISO-8601
strings so range filters and ordering behave identically across backends.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from core.storage.base import (
    BOOL,
    DATETIME,
    FLOAT,
    INT,
    JSON,
    STR,
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


class MySQLBackend(StorageBackend):
    backend_name = "mysql"

    def __init__(self, sqlalchemy_url: str):
        # Import SQLAlchemy lazily; build nothing that connects yet.
        self._url = sqlalchemy_url
        self._engine = None
        self._meta = None
        self._tables: Dict[str, Any] = {}

    # ----- lazy engine / metadata ---------------------------------------- #
    def _ensure(self):
        if self._engine is not None:
            return
        from sqlalchemy import (
            Boolean,
            Column as SAColumn,
            Float,
            Integer,
            JSON as SAJSON,
            MetaData,
            String,
            Table,
            Text,
            create_engine,
        )

        type_map = {
            INT: Integer,
            FLOAT: Float,
            STR: Text,
            BOOL: Boolean,
            JSON: SAJSON,
            DATETIME: lambda: String(32),
        }
        self._engine = create_engine(
            self._url, pool_pre_ping=True, pool_recycle=1800, future=True
        )
        self._meta = MetaData()
        for name, schema in TABLE_SCHEMAS.items():
            cols = []
            for c in schema.columns:
                sa_type = type_map[c.type]
                sa_type = sa_type() if callable(sa_type) and c.type == DATETIME else sa_type
                cols.append(
                    SAColumn(
                        c.name,
                        sa_type if not callable(sa_type) else sa_type,
                        primary_key=c.pk,
                        autoincrement=c.pk and c.type == INT,
                        nullable=c.nullable,
                    )
                )
            self._tables[name] = Table(name, self._meta, *cols)

    def _t(self, table: str):
        self._ensure()
        return self._tables[table]

    @staticmethod
    def _encode(schema: TableSchema, row: Dict[str, Any]) -> Dict[str, Any]:
        out = {}
        for c in schema.columns:
            v = row.get(c.name)
            out[c.name] = to_json(v) if c.type == JSON and v is not None else v
        return out

    @staticmethod
    def _decode(schema: TableSchema, row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for c in schema.columns:
            if c.type == JSON and out.get(c.name) is not None:
                out[c.name] = from_json(out[c.name])
        return out

    # ----- API ------------------------------------------------------------ #
    def init_schema(self) -> None:
        self._ensure()
        self._meta.create_all(self._engine)

    def insert(self, table: str, rows: Sequence[Dict[str, Any]]) -> List[int]:
        if not rows:
            return []
        schema = self.schema(table)
        t = self._t(table)
        ids: List[int] = []
        with self._engine.begin() as conn:
            for row in rows:
                res = conn.execute(t.insert().values(**self._encode(schema, row)))
                if res.inserted_primary_key:
                    ids.append(res.inserted_primary_key[0])
        return ids

    def _where(self, t, filters: Optional[Filter]):
        from sqlalchemy import and_

        clauses = []
        for col, op, val in normalise_filter(filters):
            c = t.c[col]
            if op == "=":
                clauses.append(c == val)
            elif op == "!=":
                clauses.append(c != val)
            elif op == ">":
                clauses.append(c > val)
            elif op == ">=":
                clauses.append(c >= val)
            elif op == "<":
                clauses.append(c < val)
            elif op == "<=":
                clauses.append(c <= val)
            elif op == "in":
                clauses.append(c.in_(val))
            elif op == "like":
                clauses.append(c.like(f"%{val}%"))
        return and_(*clauses) if clauses else None

    def select(self, table, filters=None, order_by: OrderBy = None, limit=None):
        from sqlalchemy import select as sa_select

        schema = self.schema(table)
        t = self._t(table)
        stmt = sa_select(t)
        where = self._where(t, filters)
        if where is not None:
            stmt = stmt.where(where)
        if order_by:
            col, direction = order_by
            c = t.c[col]
            stmt = stmt.order_by(c.desc() if (direction or "asc").lower() == "desc" else c.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        with self._engine.connect() as conn:
            return [self._decode(schema, dict(r._mapping)) for r in conn.execute(stmt)]

    def count(self, table, filters=None) -> int:
        from sqlalchemy import func, select as sa_select

        t = self._t(table)
        stmt = sa_select(func.count()).select_from(t)
        where = self._where(t, filters)
        if where is not None:
            stmt = stmt.where(where)
        with self._engine.connect() as conn:
            return int(conn.execute(stmt).scalar() or 0)

    def delete(self, table, filters) -> int:
        t = self._t(table)
        stmt = t.delete()
        where = self._where(t, filters)
        if where is not None:
            stmt = stmt.where(where)
        with self._engine.begin() as conn:
            return int(conn.execute(stmt).rowcount or 0)

    def distinct(self, table, column, filters=None) -> List[Any]:
        from sqlalchemy import select as sa_select

        t = self._t(table)
        stmt = sa_select(t.c[column]).distinct()
        where = self._where(t, filters)
        if where is not None:
            stmt = stmt.where(where)
        with self._engine.connect() as conn:
            return [r[0] for r in conn.execute(stmt)]

    def upsert(self, table, key_cols, row) -> None:
        # Use row.get(k) (not row[k]) to match the CSV backend: a missing key
        # column is treated as NULL rather than raising KeyError.
        existing = self.select(table, {k: row.get(k) for k in key_cols}, limit=1)
        if existing:
            schema = self.schema(table)
            t = self._t(table)
            where = self._where(t, {k: row.get(k) for k in key_cols})
            with self._engine.begin() as conn:
                conn.execute(t.update().where(where).values(**self._encode(schema, row)))
        else:
            self.insert(table, [row])

    def latest_per(self, table, group_cols, order_col, filters=None):
        rows = self.select(table, filters, order_by=(order_col, "asc"))
        latest: Dict[tuple, Dict[str, Any]] = {}
        for r in rows:
            latest[tuple(r.get(c) for c in group_cols)] = r
        return list(latest.values())

    def stats(self) -> List[DatasetStat]:
        from sqlalchemy import text

        out: List[DatasetStat] = []
        self._ensure()
        with self._engine.connect() as conn:
            for table in TABLE_SCHEMAS:
                count = int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
                size = conn.execute(
                    text(
                        "SELECT (data_length + index_length) FROM information_schema.tables "
                        "WHERE table_schema = DATABASE() AND table_name = :t"
                    ),
                    {"t": table},
                ).scalar()
                out.append(
                    DatasetStat(
                        table=table,
                        record_count=count,
                        size_bytes=int(size or 0),
                        last_modified=None,
                        location=f"mysql:{table}",
                    )
                )
        return out
