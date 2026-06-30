"""Panel enumeration + sampling.

From a Grafana dashboard URL we derive the ``uid`` and pull the dashboard model
via the authenticated JSON API, then enumerate every panel's id/title/type/SQL.
This is the metadata layer that feeds the ``panel_catalog`` and Chapter 2. Panel
ids are always derived from the model — never guessed.

For relevance decisions we also *sample* a panel: fetch a small slice and report
its real column names + a few rows, so a human/agent can judge cheaply before
committing to a full-window fetch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.grafana_auth import GrafanaSession
from core.logging_setup import get_logger

log = get_logger("grafana.inspector")

_UID_RE = re.compile(r"/d/([^/]+)/")


def parse_uid(dashboard_url: str) -> str:
    """Extract the dashboard uid from a ``/d/<uid>/<slug>`` URL."""
    m = _UID_RE.search(dashboard_url)
    if not m:
        raise ValueError(f"Could not parse dashboard uid from URL: {dashboard_url}")
    return m.group(1)


@dataclass
class PanelMeta:
    panel_id: int
    title: str
    type: str
    datasource: Optional[str] = None
    sql_text: str = ""
    targets: List[Dict[str, Any]] = field(default_factory=list)
    fields: List[str] = field(default_factory=list)   # filled in by sampling
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_action_panel(self) -> bool:
        """Heuristic: text/control panels carry no time-series signal."""
        if self.type in {"text", "dashlist", "news", "welcome"}:
            return True
        t = self.title.lower()
        return any(k in t for k in ("update", "insert", "delete ", "button", "no data"))


def _datasource_str(panel: Dict[str, Any]) -> Optional[str]:
    ds = panel.get("datasource")
    if isinstance(ds, dict):
        return ds.get("type") or ds.get("uid")
    return ds if isinstance(ds, str) else None


def _extract_sql(panel: Dict[str, Any]) -> str:
    parts: List[str] = []
    for t in panel.get("targets", []) or []:
        for key in ("rawSql", "rawQuery", "expr", "query"):
            val = t.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
    return "\n---\n".join(parts)


def enumerate_panels(model: Dict[str, Any]) -> List[PanelMeta]:
    """Flatten and describe every panel in a dashboard model (handles row panels)."""
    dashboard = model.get("dashboard", model)
    panels = dashboard.get("panels", []) or []
    out: List[PanelMeta] = []

    def _visit(panel_list: List[Dict[str, Any]]) -> None:
        for panel in panel_list:
            if panel.get("type") == "row":
                _visit(panel.get("panels", []) or [])
                continue
            pid = panel.get("id")
            if pid is None:
                continue
            out.append(
                PanelMeta(
                    panel_id=int(pid),
                    title=panel.get("title", "") or "",
                    type=panel.get("type", "") or "",
                    datasource=_datasource_str(panel),
                    sql_text=_extract_sql(panel),
                    targets=panel.get("targets", []) or [],
                    raw=panel,
                )
            )

    _visit(panels)
    return out


def dashboard_meta(model: Dict[str, Any]) -> Dict[str, Any]:
    dashboard = model.get("dashboard", model)
    meta = model.get("meta", {})
    return {
        "uid": dashboard.get("uid"),
        "title": dashboard.get("title"),
        "folder": meta.get("folderTitle"),
        "templating": [
            v.get("name") for v in (dashboard.get("templating", {}).get("list", []) or [])
        ],
    }


def inspect_dashboard(session: GrafanaSession, dashboard_url: str) -> Dict[str, Any]:
    """Return ``{meta, panels}`` for a dashboard URL (metadata only, no data)."""
    uid = parse_uid(dashboard_url)
    model = session.dashboard_model(uid)
    panels = enumerate_panels(model)
    meta = dashboard_meta(model)
    log.info(
        "enumerated dashboard panels",
        extra={"uid": uid, "title": meta.get("title"), "panels": len(panels)},
    )
    return {"meta": meta, "panels": panels, "model": model}
