"""One-off discovery helper: log into Grafana and list dashboards.

Usage:
    .venv/bin/python scripts/discover_dashboards.py            # list all + match LIFT
    .venv/bin/python scripts/discover_dashboards.py "<query>"  # filter by query

Prints, for every dashboard, the uid / folder / title / full URL, and highlights
the best matches for the LIFT module's required dashboards. Read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from core.config import get_config
from core.grafana_auth import GrafanaSession

# LIFT module targets (mapped + cross-relevant), with simple match keys.
LIFT_TARGETS = {
    "Lift Error History": ["lift error history"],
    "QUADRON CYCLES": ["quadron cycles"],
    "Lift_Supply_Tote": ["lift_supply_tote", "lift supply tote", "supply tote"],
    "QUADRON ERROR HISTORY": ["quadron error history"],
    "Bad Tracker Diagnosis": ["bad tracker diagnosis", "bad tracker", "tracker diagnosis"],
}


def full_url(base_url: str, dash_url: str) -> str:
    if dash_url.startswith("http"):
        return dash_url
    p = urlparse(base_url)
    return f"{p.scheme}://{p.netloc}{dash_url}"


def main() -> None:
    cfg = get_config()
    query = sys.argv[1] if len(sys.argv) > 1 else None
    with GrafanaSession() as gs:
        dashboards = gs.search_dashboards(query)
    base = cfg.grafana.base_url

    print(f"\n=== {len(dashboards)} dashboards found ===")
    rows = []
    for d in dashboards:
        rows.append(
            {
                "uid": d.get("uid", ""),
                "folder": d.get("folderTitle", "General"),
                "title": d.get("title", ""),
                "url": full_url(base, d.get("url", "")),
            }
        )
    for r in sorted(rows, key=lambda x: (x["folder"], x["title"])):
        print(f"[{r['folder']:<14}] {r['title']:<40} {r['url']}")

    print("\n=== LIFT module target matches ===")
    for target, keys in LIFT_TARGETS.items():
        matches = [
            r for r in rows if any(k in r["title"].lower() for k in keys)
        ]
        if matches:
            for m in matches:
                print(f"  {target:<24} -> [{m['folder']}] {m['title']}\n      {m['url']}")
        else:
            print(f"  {target:<24} -> (NO MATCH — please confirm the exact name)")


if __name__ == "__main__":
    main()
