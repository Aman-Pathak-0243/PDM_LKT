"""CONVEYOR data-source inspection (SOP steps 3-4).

Enumerates + samples the conveyor-relevant GTP dashboards. The mapping's panel
guesses are unverified, so this derives the real fields/zones from live data.

    .venv/bin/python scripts/inspect_conveyor.py meta
    .venv/bin/python scripts/inspect_conveyor.py sample [--window now-7d] [keys...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import get_config
from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import sample_panel
from core.panel_inspector import inspect_dashboard

CANDIDATES = {
    "conveyor_zone_count": ("Conveyor Zone Count", "http://192.168.24.230/grafana/d/lavIciTDk/conveyor-zone-count"),
    "discrepancy_report_events": ("Discrepancy Report Events", "http://192.168.24.230/grafana/d/D6sQle2Vz/discrepancy-report-events"),
    "gtp_hold_transit": ("GTP (HOLD, TRANSIT)", "http://192.168.24.230/grafana/d/C8jMvAcIk/gtp-hold-transit"),
}

OUT = Path(__file__).resolve().parent.parent / "data" / "inspection"
OUT.mkdir(parents=True, exist_ok=True)


def do_meta(session) -> None:
    report = {}
    for key, (name, url) in CANDIDATES.items():
        try:
            info = inspect_dashboard(session, url)
        except Exception as exc:  # noqa: BLE001
            print(f"!! {name}: enumeration failed: {exc}")
            continue
        panels = info["panels"]
        report[key] = {"name": name, "url": url, "meta": info["meta"],
                       "panels": [{"panel_id": p.panel_id, "title": p.title, "type": p.type,
                                   "is_action": p.is_action_panel, "sql_text": p.sql_text} for p in panels]}
        print(f"\n### {name}  (uid={info['meta'].get('uid')}, vars={info['meta'].get('templating')})")
        for p in panels:
            flag = " [ACTION]" if p.is_action_panel else ""
            sql = (p.sql_text[:120].replace("\n", " ") + "…") if p.sql_text else ""
            print(f"  #{p.panel_id:<3} {p.type:<12} {p.title[:40]:<40}{flag}  {sql}")
    (OUT / "conveyor_panels_meta.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nwrote {OUT / 'conveyor_panels_meta.json'}")


def do_sample(session, keys, window) -> None:
    meta_path = OUT / "conveyor_panels_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    keys = keys or list(CANDIDATES.keys())
    for key in keys:
        name, url = CANDIDATES[key]
        panels = meta.get(key, {}).get("panels") or [
            {"panel_id": p.panel_id, "title": p.title, "is_action": p.is_action_panel}
            for p in inspect_dashboard(session, url)["panels"]
        ]
        samples = {}
        print(f"\n### sampling {name} (window={window})")
        for p in panels:
            if p.get("is_action"):
                continue
            pid = p["panel_id"]
            try:
                s = sample_panel(session, url, pid, window=window, n=6)
                samples[pid] = {"title": p["title"], **s}
                print(f"  #{pid:<3} {p['title'][:34]:<34} rows={s['row_count']:<6} cols={s['columns']}")
                if s["sample_rows"]:
                    print(f"        e.g. {json.dumps(s['sample_rows'][0], default=str)[:220]}")
            except Exception as exc:  # noqa: BLE001
                samples[pid] = {"error": str(exc)}
                print(f"  #{pid:<3} {p['title'][:34]:<34} -> {str(exc)[:70]}")
        (OUT / f"conveyor_{key}_samples.json").write_text(json.dumps(samples, indent=2, default=str))


def main() -> None:
    cfg = get_config()
    args = sys.argv[1:]
    mode = args[0] if args else "meta"
    window = cfg.fetch_default_window
    if "--window" in args:
        i = args.index("--window")
        window = args[i + 1]
        args = args[:i] + args[i + 2:]
    keys = [a for a in args[1:] if not a.startswith("--")]
    with GrafanaSession() as gs:
        do_meta(gs) if mode == "meta" else do_sample(gs, keys, window)


if __name__ == "__main__":
    main()
