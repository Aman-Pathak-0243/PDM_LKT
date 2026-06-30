"""Domain/audit event recording.

Writes structured events to the ``event_log`` dataset (searchable in the dashboard
Logs page) and mirrors them to the technical JSON logs. Audit failures are
swallowed so they can never break the main flow.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.logging_setup import get_logger
from core.storage import get_storage
from core.storage.base import now_iso

log = get_logger("audit")


def record_event(
    event: str,
    level: str = "INFO",
    source: str = "app",
    module: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    detail = detail or {}
    try:
        get_storage().insert(
            "event_log",
            [
                {
                    "ts": now_iso(),
                    "level": level.upper(),
                    "source": source,
                    "event": event,
                    "module": module,
                    "detail_json": detail,
                }
            ],
        )
    except Exception:  # noqa: BLE001 - audit must never break the caller
        log.exception("failed to write event_log", extra={"event": event})
    getattr(log, level.lower(), log.info)(event, extra={"module": module, **detail})
