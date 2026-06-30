"""LIFT data-source inspection (SOP steps 3-4).

Enumerates panels (id/title/type/SQL) for every lift-relevant dashboard and,
optionally, samples each non-action panel (small window) to reveal real column
names, dtypes, and row counts. Writes a machine-readable report to
``data/inspection/`` and prints a concise summary so panel relevance can be judged.

Modes:
    meta            enumerate panel metadata for all candidates (fast, API only)
    sample [keys..] sample panels (CSV download) for the given candidate keys
                    (default: all). Use --window to override (default now-2d).
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

# All lift-relevant candidates discovered via /api/search.
CANDIDATES = {
    "lift_error_history": ("Lift Error History", "http://192.168.24.230/grafana/d/wQds52G4z/lift-error-history"),
    "quadron_cycles": ("QUADRON CYCLES", "http://192.168.24.230/grafana/d/8dDcXomVz/quadron-cycles"),
    "lift_supply_tote": ("Lift_Supply_Tote", "http://192.168.24.230/grafana/d/lPsUfQ4Ska/lift-supply-tote"),
    "quadron_error_history": ("QUADRON ERROR HISTORY", "http://192.168.24.230/grafana/d/K2QzauWVz/quadron-error-history"),
    "bad_tracker_diagnosis": ("Bad Tracker Diagnosis", "http://192.168.24.230/grafana/d/VAW2nmqIz/bad-tracker-diagnosis"),
    "opc_lift_datalogger": ("OPC - Lift Datalogger", "http://192.168.24.230/grafana/d/SBaBnPb4z/opc-lift-datalogger"),
    "lift_error_analysis": ("Lift Error Analysis", "http://192.168.24.230/grafana/d/EqDhnQ9Sz/lift-error-analysis"),
    "lift_error_time_graph": ("Lift Error-time Graph", "http://192.168.24.230/grafana/d/R25cf1RHz/lift-error-time-graph"),
    "process_lift": ("Process - Lift", "http://192.168.24.230/grafana/d/Z0Ls6L7Sk/process-lift"),
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
        report[key] = {
            "name": name,
            "url": url,
            "meta": info["meta"],
            "panels": [
                {
                    "panel_id": p.panel_id,
                    "title": p.title,
                    "type": p.type,
                    "datasource": p.datasource,
                    "is_action": p.is_action_panel,
                    "sql_text": p.sql_text,
                }
                for p in panels
            ],
        }
        print(f"\n### {name}  (uid={info['meta'].get('uid')}, vars={info['meta'].get('templating')})")
        for p in panels:
            flag = " [ACTION]" if p.is_action_panel else ""
            sql = (p.sql_text[:120].replace("\n", " ") + "…") if p.sql_text else ""
            print(f"  #{p.panel_id:<3} {p.type:<14} {p.title[:42]:<42}{flag}  {sql}")
    (OUT / "lift_panels_meta.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nwrote {OUT / 'lift_panels_meta.json'}")


def do_sample(session, keys, window) -> None:
    meta_path = OUT / "lift_panels_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    keys = keys or list(CANDIDATES.keys())
    for key in keys:
        if key not in CANDIDATES:
            print(f"!! unknown key {key}")
            continue
        name, url = CANDIDATES[key]
        panels = meta.get(key, {}).get("panels")
        if panels is None:
            info = inspect_dashboard(session, url)
            panels = [{"panel_id": p.panel_id, "title": p.title, "type": p.type,
                       "is_action": p.is_action_panel} for p in info["panels"]]
        samples = {}
        print(f"\n### sampling {name} (window={window})")
        for p in panels:
            if p.get("is_action"):
                continue
            pid = p["panel_id"]
            try:
                s = sample_panel(session, url, pid, window=window, n=5)
            except Exception as exc:  # noqa: BLE001
                print(f"  #{pid} {p['title'][:36]:<36} -> sample failed: {str(exc)[:80]}")
                samples[pid] = {"error": str(exc)}
                continue
            samples[pid] = {"title": p["title"], **s}
            print(f"  #{pid:<3} {p['title'][:36]:<36} rows={s['row_count']:<6} cols={s['columns']}")
        (OUT / f"{key}_samples.json").write_text(json.dumps(samples, indent=2, default=str))
        print(f"  wrote {OUT / (key + '_samples.json')}")


def main() -> None:
    cfg = get_config()
    args = sys.argv[1:]
    mode = args[0] if args else "meta"
    window = cfg.fetch_default_window
    if "--window" in args:
        window = args[args.index("--window") + 1]
        args = [a for i, a in enumerate(args) if i not in (args.index("--window"), args.index("--window") + 1)]
    keys = [a for a in args[1:] if not a.startswith("--")]

    with GrafanaSession() as gs:
        if mode == "meta":
            do_meta(gs)
        elif mode == "sample":
            do_sample(gs, keys, window)
        else:
            print(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
