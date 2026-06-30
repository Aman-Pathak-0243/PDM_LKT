"""Module plugin packages.

Importing this package imports every module package so each self-registers in
``core.registry``. New modules are added here (one import line) and nowhere in
``core/`` — that is the whole plugin contract.
"""

from __future__ import annotations

from core.logging_setup import get_logger

log = get_logger("modules")

# --- registered modules (import to self-register) --------------------------- #
from modules import lift  # noqa: E402,F401
from modules import shuttle  # noqa: E402,F401

# from modules import conveyor   # next session

__all__ = ["lift", "shuttle"]
