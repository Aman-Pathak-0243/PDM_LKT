#!/usr/bin/env python3
"""Backup / export / migrate the PdM store — backend-agnostic.

Purpose (the "database is full → back up and export into another database" workflow):
when the active store (CSV now, or MySQL later) fills up or must be moved, this tool

  * **backup** — dump every table of the ACTIVE store to a portable, timestamped folder of
    JSON-Lines files (+ a manifest) that preserves JSON columns and row types faithfully;
  * **copy**   — stream the ACTIVE store row-by-row into a FRESH target backend (a new CSV
    location on a bigger disk, or — once permitted — a new MySQL database), so you can
    switch to larger storage with zero application-code changes;
  * **load**   — load a backup folder into a target backend (the inverse of backup);
  * **stats**  — per-table row counts + sizes of the active store;
  * **verify** — compare per-table row counts between the active store and a target.

It reads through ``core.storage`` (so the SOURCE respects ``STORAGE_BACKEND``) and never
touches module logic. Relationships between rows use ``run_uid`` / ``trigger_id`` (not the
surrogate ``id``), so surrogate ids are re-assigned by the target on copy/load without
breaking any join.

HARD RULES honoured (see CLAUDE.md):
  * MySQL is NEVER contacted unless ``MYSQL_CONFIRM=ENABLE`` is set (the same gate as
    ``core.storage.get_storage``). Without it, ``--to-mysql`` refuses.
  * The SOURCE is read-only; nothing here deletes source data.

Examples
--------
    # See what's in the active store
    .venv/bin/python scripts/db_migrate_export.py stats

    # Portable backup of everything to a timestamped folder under <DATA_DIR>/exports/
    .venv/bin/python scripts/db_migrate_export.py backup

    # Move the whole store to a fresh CSV location (e.g. a bigger disk)
    .venv/bin/python scripts/db_migrate_export.py copy --to-csv /mnt/big/pdm_store

    # Once MySQL is permitted (MYSQL_CONFIRM=ENABLE + DB_* in .env): migrate into it
    MYSQL_CONFIRM=ENABLE .venv/bin/python scripts/db_migrate_export.py copy --to-mysql

    # Load a previous backup into the active store (or a target)
    .venv/bin/python scripts/db_migrate_export.py load --from database/exports/backup_20260701T120000
    # Confirm a migration moved everything
    MYSQL_CONFIRM=ENABLE .venv/bin/python scripts/db_migrate_export.py verify --to-mysql
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make the repo importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import get_config  # noqa: E402
from core.logging_setup import get_logger, setup_logging  # noqa: E402
from core.storage import get_storage  # noqa: E402
from core.storage.base import StorageBackend, TABLE_SCHEMAS  # noqa: E402

log = get_logger("db_migrate")

BATCH = 1000  # rows per insert batch (bounds memory on large tables)


# --------------------------------------------------------------------------- #
# Target backend construction (explicit, gated)
# --------------------------------------------------------------------------- #
def build_target(args: argparse.Namespace) -> tuple[StorageBackend, str]:
    """Construct the TARGET backend from CLI flags. MySQL is gated."""
    if getattr(args, "to_csv", None):
        from core.storage.csv_backend import CsvBackend

        be = CsvBackend(Path(args.to_csv))
        be.init_schema()
        return be, f"csv:{Path(args.to_csv) / 'store'}"
    if getattr(args, "to_mysql", False):
        if os.environ.get("MYSQL_CONFIRM", "").strip().upper() != "ENABLE":
            raise SystemExit(
                "Refusing to touch MySQL: set MYSQL_CONFIRM=ENABLE (and confirm the real "
                "DB name in .env) before targeting MySQL. This is the project hard rule."
            )
        from core.config import get_config
        from core.storage.mysql_backend import MySQLBackend

        url = get_config().database.sqlalchemy_url()
        be = MySQLBackend(url)
        be.init_schema()
        log.warning("MySQL target ACTIVE", extra={"host": get_config().database.host})
        return be, "mysql"
    raise SystemExit("Choose a target: --to-csv <dir>  or  --to-mysql")


def _keyed_tables() -> Dict[str, List[str]]:
    """Tables that must be UPSERTed (keyed), not appended, to avoid duplicates."""
    out: Dict[str, List[str]] = {}
    for name, schema in TABLE_SCHEMAS.items():
        if any(u for u in schema.unique):
            out[name] = list(schema.unique[0])
        elif any(c.pk and c.type != "int" for c in schema.columns):
            out[name] = [c.name for c in schema.columns if c.pk]
    return out


def _strip_surrogate(row: Dict[str, Any]) -> Dict[str, Any]:
    r = dict(row)
    r.pop("id", None)  # let the target assign a fresh surrogate id
    return r


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #
def op_stats(_args: argparse.Namespace) -> int:
    src = get_storage()
    print(f"Active store backend: {src.backend_name}")
    total_rows = total_bytes = 0
    print(f"{'table':22} {'rows':>10} {'size':>12}  location")
    for s in src.stats():
        total_rows += s.record_count
        total_bytes += s.size_bytes
        print(f"{s.table:22} {s.record_count:>10} {s.size_bytes:>12}  {s.location}")
    print(f"{'TOTAL':22} {total_rows:>10} {total_bytes:>12}")
    return 0


def op_backup(args: argparse.Namespace) -> int:
    src = get_storage()
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_dir = Path(args.out) if args.out else (get_config().data_dir / "exports" / f"backup_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: Dict[str, Any] = {"created_at": ts, "backend": src.backend_name, "tables": {}}
    for table in TABLE_SCHEMAS:
        rows = src.select(table)
        path = out_dir / f"{table}.jsonl"
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        manifest["tables"][table] = len(rows)
        log.info("backed up table", extra={"table": table, "rows": len(rows)})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Backup complete → {out_dir}")
    for t, n in manifest["tables"].items():
        print(f"  {t:22} {n:>10} rows")
    return 0


def _insert_rows(target: StorageBackend, table: str, rows: List[Dict[str, Any]], keyed: Dict[str, List[str]]) -> int:
    """Write rows into the target: upsert keyed tables, batch-insert append tables."""
    if not rows:
        return 0
    if table in keyed:
        key_cols = keyed[table]
        for r in rows:
            target.upsert(table, key_cols, _strip_surrogate(r) if "id" in TABLE_SCHEMAS[table].column_names else dict(r))
        return len(rows)
    written = 0
    buf: List[Dict[str, Any]] = []
    for r in rows:
        buf.append(_strip_surrogate(r))
        if len(buf) >= BATCH:
            target.insert(table, buf)
            written += len(buf)
            buf = []
    if buf:
        target.insert(table, buf)
        written += len(buf)
    return written


def op_copy(args: argparse.Namespace) -> int:
    src = get_storage()
    target, target_desc = build_target(args)
    keyed = _keyed_tables()
    print(f"Copying {src.backend_name} → {target_desc}")
    grand = 0
    for table in TABLE_SCHEMAS:
        rows = src.select(table)
        n = _insert_rows(target, table, rows, keyed)
        grand += n
        log.info("copied table", extra={"table": table, "rows": n})
        print(f"  {table:22} {n:>10} rows")
    print(f"Copy complete: {grand} rows → {target_desc}")
    print("Tip: run 'verify' with the same target flags to confirm row counts match.")
    return 0


def op_load(args: argparse.Namespace) -> int:
    in_dir = Path(args.src)
    if not in_dir.exists():
        raise SystemExit(f"backup folder not found: {in_dir}")
    # Target: an explicit backend if given, else the active store.
    if getattr(args, "to_csv", None) or getattr(args, "to_mysql", False):
        target, target_desc = build_target(args)
    else:
        target, target_desc = get_storage(), f"active({get_storage().backend_name})"
    keyed = _keyed_tables()
    print(f"Loading {in_dir} → {target_desc}")
    grand = 0
    for table in TABLE_SCHEMAS:
        path = in_dir / f"{table}.jsonl"
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        n = _insert_rows(target, table, rows, keyed)
        grand += n
        print(f"  {table:22} {n:>10} rows")
    print(f"Load complete: {grand} rows → {target_desc}")
    return 0


def op_verify(args: argparse.Namespace) -> int:
    src = get_storage()
    target, target_desc = build_target(args)
    print(f"Verifying row counts: {src.backend_name} vs {target_desc}")
    ok = True
    for table in TABLE_SCHEMAS:
        a, b = src.count(table), target.count(table)
        flag = "OK" if b >= a else "MISMATCH"
        if b < a:
            ok = False
        print(f"  {table:22} source={a:>8}  target={b:>8}  {flag}")
    print("All tables present in target." if ok else "WARNING: target is missing rows — re-run copy/load.")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="Backup / export / migrate the PdM store.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats", help="print per-table row counts + sizes of the active store")

    b = sub.add_parser("backup", help="dump the active store to a portable JSONL folder")
    b.add_argument("--out", help="output folder (default: <DATA_DIR>/exports/backup_<ts>)")

    def add_target(sp):
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--to-csv", metavar="DIR", help="target: a fresh CSV store directory")
        g.add_argument("--to-mysql", action="store_true", help="target: MySQL from .env (needs MYSQL_CONFIRM=ENABLE)")

    c = sub.add_parser("copy", help="stream the active store into a fresh target backend")
    add_target(c)

    l = sub.add_parser("load", help="load a backup folder into a target (default: active store)")
    l.add_argument("--from", dest="src", required=True, help="a backup folder produced by 'backup'")
    add_target(l)

    v = sub.add_parser("verify", help="compare row counts between the active store and a target")
    add_target(v)

    args = p.parse_args(argv)
    return {
        "stats": op_stats, "backup": op_backup, "copy": op_copy,
        "load": op_load, "verify": op_verify,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
