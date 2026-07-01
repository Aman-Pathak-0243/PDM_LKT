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
from modules import conveyor  # noqa: E402,F401
from modules import tracker  # noqa: E402,F401
from modules import gate  # noqa: E402,F401
from modules import bin_mech  # noqa: E402,F401
from modules import gtp_station  # noqa: E402,F401
from modules import decant_station  # noqa: E402,F401
from modules import network  # noqa: E402,F401
from modules import controller  # noqa: E402,F401
from modules import meta  # noqa: E402,F401  — registered LAST: correlates the other modules' fresh results

# Module set COMPLETE (11/11 — the mapping's build sequence ends at the meta layer).

__all__ = ["lift", "shuttle", "conveyor", "tracker", "gate", "bin_mech", "gtp_station",
           "decant_station", "network", "controller", "meta"]
