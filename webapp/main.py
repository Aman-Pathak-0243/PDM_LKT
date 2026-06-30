"""FastAPI application: main dashboard, per-module pages, and JSON APIs.

On startup the lifespan: configures logging, initialises the storage schema,
imports ``modules`` (so every module self-registers), and starts the automation
scheduler. The scheduler runs in this process independently of any connected
browser — closing the dashboard never stops automation; only stopping the service
does (CLAUDE.md §9).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.config import get_config
from core.logging_setup import get_logger, setup_logging
from core.registry import all_modules
from core.scheduler import get_scheduler
from core.storage import get_storage
from webapp import services
from webapp.api import router as api_router

HERE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
log = get_logger("webapp")

NAV = [
    ("/", "Overview"),
    ("/triggers", "PdM Triggers"),
    ("/automation", "Automation"),
    ("/storage", "Storage"),
    ("/logs", "Logs"),
    ("/system", "System"),
    ("/plugins", "Plugins"),
    ("/settings", "Settings"),
]

WINDOWS = ["now-6h", "now-24h", "now-2d", "now-7d", "now-30d", "now-90d", "now-365d"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    get_storage()              # init schema (CSV datasets)
    import modules             # noqa: F401  -> self-register all modules
    get_scheduler().start()    # automation, independent of the dashboard
    log.info("application started", extra={"modules": [m.name for m in all_modules()]})
    try:
        yield
    finally:
        get_scheduler().shutdown()
        log.info("application stopped")


def create_app() -> FastAPI:
    cfg = get_config()
    app = FastAPI(title=cfg.app.title, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    app.include_router(api_router)

    def ctx(request: Request, page: str, **extra: Any) -> Dict[str, Any]:
        base = {
            "request": request,
            "app_title": cfg.app.title,
            "nav": NAV,
            "page": page,
            "windows": WINDOWS,
            "default_window": cfg.fetch_default_window,
            "backend": get_storage().backend_name,
        }
        base.update(extra)
        return base

    # ---- HTML pages ------------------------------------------------------- #
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(
            request, "index.html", ctx(request, "overview", modules=services.module_summaries())
        )

    @app.get("/module/{name}", response_class=HTMLResponse)
    def module_page(request: Request, name: str):
        mod = next((m for m in all_modules() if m.name == name), None)
        title = mod.title if mod else name
        return templates.TemplateResponse(
            request, "module.html", ctx(request, "overview", module_name=name, module_title=title)
        )

    @app.get("/triggers", response_class=HTMLResponse)
    def triggers_page(request: Request):
        return templates.TemplateResponse(request, "triggers.html", ctx(request, "triggers"))

    @app.get("/automation", response_class=HTMLResponse)
    def automation_page(request: Request):
        return templates.TemplateResponse(request, "automation.html", ctx(request, "automation"))

    @app.get("/storage", response_class=HTMLResponse)
    def storage_page(request: Request):
        return templates.TemplateResponse(request, "storage.html", ctx(request, "storage"))

    @app.get("/logs", response_class=HTMLResponse)
    def logs_page(request: Request):
        return templates.TemplateResponse(request, "logs.html", ctx(request, "logs"))

    @app.get("/system", response_class=HTMLResponse)
    def system_page(request: Request):
        return templates.TemplateResponse(request, "system.html", ctx(request, "system"))

    @app.get("/plugins", response_class=HTMLResponse)
    def plugins_page(request: Request):
        return templates.TemplateResponse(request, "plugins.html", ctx(request, "plugins"))

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        return templates.TemplateResponse(
            request, "settings.html",
            ctx(request, "settings",
                grafana_base=cfg.grafana.base_url, app_host=cfg.app.host, app_port=cfg.app.port),
        )

    return app


app = create_app()
