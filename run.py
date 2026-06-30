#!/usr/bin/env python
"""Start the PdM application (web dashboard + automation scheduler).

    python run.py

The web dashboard binds APP_HOST:APP_PORT (see .env) and is reachable on the
company LAN. Automation runs in this same process via APScheduler, so it keeps
running whether or not a browser is connected — stop the service (Ctrl-C) to halt it.
"""

from __future__ import annotations

import uvicorn

from core.config import get_config


def main() -> None:
    cfg = get_config()
    uvicorn.run(
        "webapp.main:app",
        host=cfg.app.host,
        port=cfg.app.port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
