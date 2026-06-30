"""Structured JSON logging for the whole application.

Logs are emitted as one JSON object per line to ``logs/app.log.jsonl`` (rotating)
and, in a human-readable form, to the console. The JSON-lines file is what the
dashboard's *Logs* page searches/filters. Logging never raises into the caller.

Use :func:`get_logger` everywhere; call :func:`setup_logging` once at startup.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import logging.handlers
from pathlib import Path
from typing import Any, Optional

from core.config import get_config

_CONFIGURED = False

# Standard LogRecord attributes we do not want to duplicate inside "extra".
_RESERVED = set(
    vars(logging.makeLogRecord({})).keys()
) | {"message", "asctime", "taskName"}


class _PdmLogger(logging.Logger):
    """Logger that renames reserved keys in ``extra`` (e.g. ``module``) instead of
    raising ``KeyError``, so structured logging never crashes a caller."""

    def makeRecord(self, name, level, fn, lno, msg, args, exc_info,
                   func=None, extra=None, sinfo=None):
        if extra:
            extra = {
                (k if k not in _RESERVED else f"{k}_"): v for k, v in extra.items()
            }
        return super().makeRecord(
            name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
        )


# Install before any "pdm.*" logger is created so they use this class.
logging.setLoggerClass(_PdmLogger)


def _utc_iso(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat(timespec="milliseconds")


class JsonLineFormatter(logging.Formatter):
    """Render each record as a single compact JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _utc_iso(record.created),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Promote any structured fields passed via logger.info(..., extra={...}).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)  # ensure serialisable
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Compact, readable console line with a trailing field summary."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"{_utc_iso(record.created)} {record.levelname:<7} {record.name}: {record.getMessage()}"
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_")
        }
        if extras:
            base += " | " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(level: int = logging.INFO) -> Path:
    """Configure root logging handlers idempotently. Returns the log file path."""
    global _CONFIGURED
    cfg = get_config()
    log_file = cfg.log_dir / "app.log.jsonl"
    if _CONFIGURED:
        return log_file

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):  # avoid duplicate handlers on reload
        root.removeHandler(handler)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(JsonLineFormatter())
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(ConsoleFormatter())
    root.addHandler(console)

    # Quieten noisy third-party loggers.
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    logging.getLogger("pdm").info("logging initialised", extra={"log_file": str(log_file)})
    return log_file


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a namespaced logger (``pdm`` root namespace)."""
    if not _CONFIGURED:
        setup_logging()
    return logging.getLogger(f"pdm.{name}" if name else "pdm")
