"""Panel CSV fetching via Grafana's inspector "Download CSV" flow.

Builds ``${dashboardURL}&inspect=<panelId>&inspectTab=data`` (merging query params
correctly), opens it with the authenticated Playwright context, ensures the Data
tab is active, clicks the ``GRAFANA_DOWNLOAD_BUTTON_TEXT`` button, captures the
download, and loads it into a pandas DataFrame.

Time window (``from``/``to``) and template variables (``var-<Name>``) are always
parameterised. An empty result is returned as an empty DataFrame (not an error).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import pandas as pd

from core.config import get_config
from core.grafana_auth import GrafanaSession
from core.logging_setup import get_logger

log = get_logger("grafana.fetcher")


class PanelFetchError(RuntimeError):
    pass


@dataclass
class FetchResult:
    panel_id: int
    dashboard_url: str
    columns: List[str]
    row_count: int
    df: pd.DataFrame
    window: str


def build_inspect_url(
    dashboard_url: str,
    panel_id: int,
    frm: str,
    to: str,
    variables: Optional[Dict[str, str]] = None,
) -> str:
    """Merge inspector + time + variable params into a dashboard URL."""
    parsed = urlparse(dashboard_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.setdefault("orgId", "1")
    params["from"] = frm
    params["to"] = to
    params["inspect"] = str(panel_id)
    params["inspectTab"] = "data"
    for name, value in (variables or {}).items():
        params[f"var-{name}"] = value
    return urlunparse(parsed._replace(query=urlencode(params)))


def _click_download(page, download_text: str):
    """Locate and click the Download CSV button; return the download object."""
    # Make sure the Data tab is active (defensive; inspectTab=data usually does it).
    for tab_label in ("Data",):
        try:
            tab = page.get_by_role("tab", name=tab_label)
            if tab and tab.count() > 0 and tab.first.is_visible():
                tab.first.click()
        except Exception:  # noqa: BLE001
            pass

    locators = [
        lambda: page.get_by_role("button", name=download_text, exact=False),
        lambda: page.get_by_text(download_text, exact=False),
    ]
    # Give the inspector Data tab time to render the button (panel query must run
    # first). Retry the whole locator sweep a few times for slow/heavy panels.
    for attempt in range(3):
        for make in locators:
            try:
                loc = make()
                if loc and loc.count() > 0:
                    loc.first.wait_for(state="visible", timeout=20000)
                    with page.expect_download(timeout=45000) as dl_info:
                        loc.first.click()
                    return dl_info.value
            except Exception:  # noqa: BLE001
                continue
        try:
            page.wait_for_timeout(2000)
        except Exception:  # noqa: BLE001
            break
    raise PanelFetchError(
        f"'{download_text}' button not found in the panel inspector. "
        "The panel may have no data, or the Grafana UI differs from expectations."
    )


def download_panel_csv(
    session: GrafanaSession,
    dashboard_url: str,
    panel_id: int,
    frm: Optional[str] = None,
    to: str = "now",
    variables: Optional[Dict[str, str]] = None,
) -> FetchResult:
    """Download one panel's data as CSV and load it into a DataFrame."""
    cfg = get_config()
    frm = frm or cfg.fetch_default_window
    url = build_inspect_url(dashboard_url, panel_id, frm, to, variables)
    window = f"{frm}..{to}"
    page = session.new_page()
    try:
        # Load fast, then give fast panels a brief chance to reach network idle.
        # Heavy live dashboards never idle, so the timeout is swallowed and the
        # Download-CSV button wait (below) is what actually gates readiness.
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        download = _click_download(page, cfg.grafana.download_button_text)
        path = download.path()
        if path is None:
            raise PanelFetchError("Download did not produce a file")
        try:
            df = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame()
    finally:
        page.close()

    result = FetchResult(
        panel_id=panel_id,
        dashboard_url=dashboard_url,
        columns=list(df.columns),
        row_count=len(df),
        df=df,
        window=window,
    )
    log.info(
        "fetched panel CSV",
        extra={"panel_id": panel_id, "rows": result.row_count, "window": window},
    )
    return result


def sample_panel(
    session: GrafanaSession,
    dashboard_url: str,
    panel_id: int,
    window: str = "now-6h",
    n: int = 8,
) -> Dict:
    """Fetch a small slice of a panel to reveal its real columns + a few rows."""
    res = download_panel_csv(session, dashboard_url, panel_id, frm=window, to="now")
    head = res.df.head(n)
    return {
        "panel_id": panel_id,
        "columns": res.columns,
        "row_count": res.row_count,
        "sample_rows": head.to_dict("records"),
        "dtypes": {c: str(t) for c, t in res.df.dtypes.items()},
    }
