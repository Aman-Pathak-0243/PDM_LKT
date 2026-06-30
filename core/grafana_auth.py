"""Grafana authentication + session.

Logs into Grafana once with Playwright (Chromium, username+password) and reuses
the authenticated session for both:

* **JSON API calls** (httpx, reusing the login cookie) — dashboard search and
  dashboard models; and
* **browser page operations** (the panel CSV "Download CSV" flow).

Synchronous on purpose: PdM runs always execute on a worker thread (APScheduler
executor or the webapp's thread pool), never on the asyncio event loop, so the
sync Playwright API is safe and the modelling code stays plain Python.

The password is read from config and **never logged**.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from core.config import GrafanaConfig, get_config
from core.logging_setup import get_logger

log = get_logger("grafana.auth")


class GrafanaAuthError(RuntimeError):
    """Login failed or the session is not authenticated."""


class GrafanaSession:
    """Authenticated Grafana session. Use as a context manager.

    >>> with GrafanaSession() as gs:
    ...     dashboards = gs.api_json("/api/search", params={"type": "dash-db"})
    """

    def __init__(self, cfg: Optional[GrafanaConfig] = None):
        self.cfg = cfg or get_config().grafana
        self._pw = None
        self._browser = None
        self.context = None
        self._http: Optional[httpx.Client] = None

    # ----- lifecycle ------------------------------------------------------ #
    def __enter__(self) -> "GrafanaSession":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> "GrafanaSession":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.cfg.headless)
        self.context = self._browser.new_context(accept_downloads=True)
        self.context.set_default_navigation_timeout(self.cfg.nav_timeout_ms)
        self.context.set_default_timeout(self.cfg.nav_timeout_ms)
        self._login()
        self._build_http_client()
        self._verify()
        return self

    def close(self) -> None:
        for closer in (
            lambda: self._http and self._http.close(),
            lambda: self.context and self.context.close(),
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
        ):
            try:
                closer()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        self._http = self.context = self._browser = self._pw = None

    # ----- login ---------------------------------------------------------- #
    def _login(self) -> None:
        page = self.context.new_page()
        try:
            log.info("logging into Grafana", extra={"url": self.cfg.login_url})
            page.goto(self.cfg.login_url, wait_until="domcontentloaded")
            page.fill(self.cfg.username_selector, self.cfg.username)
            page.fill(self.cfg.password_selector, self.cfg.password)
            page.click(self.cfg.submit_selector)
            # Wait for the SPA to settle after the login POST.
            try:
                page.wait_for_load_state("networkidle", timeout=self.cfg.nav_timeout_ms)
            except Exception:  # noqa: BLE001
                pass
            # Some Grafana builds show an optional "change password" step with a Skip.
            for label in ("Skip", "Skip now", "skip"):
                try:
                    btn = page.get_by_text(label, exact=False)
                    if btn and btn.count() > 0 and btn.first.is_visible():
                        btn.first.click()
                        page.wait_for_load_state("networkidle", timeout=5000)
                        break
                except Exception:  # noqa: BLE001
                    continue
        finally:
            page.close()

    def _build_http_client(self) -> None:
        cookies = {c["name"]: c["value"] for c in self.context.cookies()}
        self._http = httpx.Client(
            timeout=httpx.Timeout(self.cfg.nav_timeout_ms / 1000.0),
            cookies=cookies,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )

    def _verify(self) -> None:
        """Confirm authentication via /api/user; raise a clean error otherwise."""
        try:
            resp = self._http.get(f"{self.cfg.api_base}/api/user")
        except Exception as exc:  # noqa: BLE001
            raise GrafanaAuthError(f"Could not reach Grafana API: {exc}") from exc
        if resp.status_code != 200:
            raise GrafanaAuthError(
                f"Grafana login appears to have failed (GET /api/user -> "
                f"{resp.status_code}). Check credentials/selectors in .env."
            )
        login = resp.json().get("login", "?")
        log.info("Grafana session authenticated", extra={"login": login})

    # ----- API helpers ----------------------------------------------------- #
    def api_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if self._http is None:
            raise GrafanaAuthError("Session not started")
        url = f"{self.cfg.api_base}{path}" if path.startswith("/") else f"{self.cfg.api_base}/{path}"
        resp = self._http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def search_dashboards(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """List dashboards (uid, title, folder, url) via /api/search."""
        params: Dict[str, Any] = {"type": "dash-db", "limit": 5000}
        if query:
            params["query"] = query
        return self.api_json("/api/search", params=params)

    def dashboard_model(self, uid: str) -> Dict[str, Any]:
        """Full dashboard model + meta via /api/dashboards/uid/<uid>."""
        return self.api_json(f"/api/dashboards/uid/{uid}")

    def new_page(self):
        if self.context is None:
            raise GrafanaAuthError("Session not started")
        return self.context.new_page()
