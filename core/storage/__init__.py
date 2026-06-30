"""Storage backend factory.

``get_storage()`` returns the active backend based on ``STORAGE_BACKEND``:

* ``csv``  — the CSV backend (default, active).
* ``mysql``— the MySQL backend. Building it requires an explicit second
  confirmation env var (``MYSQL_CONFIRM=ENABLE``) so MySQL can never be reached by
  accident; this enforces the hard rule "never use MySQL until the user allows it".

The returned backend is a singleton for the process.
"""

from __future__ import annotations

import os
from functools import lru_cache

from core.config import get_config
from core.logging_setup import get_logger
from core.storage.base import StorageBackend  # re-exported
from core.storage.csv_backend import CsvBackend

log = get_logger("storage")


class MySQLPermissionError(RuntimeError):
    """Raised when MySQL is requested without the explicit confirmation gate."""


@lru_cache(maxsize=1)
def get_storage() -> StorageBackend:
    cfg = get_config()
    if cfg.storage_backend == "mysql":
        if os.environ.get("MYSQL_CONFIRM", "").strip().upper() != "ENABLE":
            raise MySQLPermissionError(
                "STORAGE_BACKEND=mysql but MySQL use is gated. The user has not "
                "granted permission. To enable later, set MYSQL_CONFIRM=ENABLE and "
                "confirm the real database name. Staying on CSV is the safe default."
            )
        from core.storage.mysql_backend import MySQLBackend

        backend: StorageBackend = MySQLBackend(cfg.database.sqlalchemy_url())
        log.warning("MySQL backend ACTIVE", extra={"host": cfg.database.host})
    else:
        backend = CsvBackend(cfg.data_dir)
        log.info("CSV storage backend active", extra={"dir": str(cfg.data_dir / "store")})
    backend.init_schema()
    return backend


def reset_storage_cache() -> None:
    """Testing helper: clear the singleton so a new backend can be built."""
    get_storage.cache_clear()


__all__ = ["get_storage", "StorageBackend", "MySQLPermissionError", "reset_storage_cache"]
