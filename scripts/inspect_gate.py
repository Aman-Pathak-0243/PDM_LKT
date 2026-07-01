"""GATE / Door-actuator data-source discovery + inspection (SOP steps 2-4).

The mapping (§4) lists the GATE primary as *Quadron-gate-status* (Maintenance folder)
and a secondary of *QUADRON ERROR HISTORY* — but the kickoff warns the mapping has been
wrong repeatedly (QUADRON ERROR HISTORY turned out shuttle-only; a panel once listed
under Gate had no lift_id and was reassigned to Shuttle). So this helper **re-verifies
by live inspection** rather than trusting the mapping:

  discover : /api/search for gate/door candidates -> uid / folder / title / full URL.
  meta     : enumerate every panel of the candidate dashboards (id/title/type/SQL) +
             the dashboard's template vars. Panel ids come from the model, never guessed.
  sample   : pull a small slice of each non-action panel to reveal real columns + rows,
             so a gate/door COMPONENT identity + open/close-fault + latency signals can be
             judged against reality before any module.yaml/features are written.

Usage:
    .venv/bin/python scripts/inspect_gate.py discover
    .venv/bin/python scripts/inspect_gate.py meta   [--window now-2d] [url ...]
    .venv/bin/python scripts/inspect_gate.py sample [--window now-2d] [url ...]

If no dashboard URLs are passed to meta/sample, the candidates found by `discover`
(cached in data/inspection/gate_candidates.json) are used; otherwise a live discovery
is run first. Read-only — writes only reports under data/inspection/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import get_config
from core.grafana_auth import GrafanaSession
from core.grafana_fetcher import sample_panel
from core.panel_inspector import inspect_dashboard

OUT = Path(__file__).resolve().parent.parent / "data" / "inspection"
OUT.mkdir(parents=True, exist_ok=True)
CAND_PATH = OUT / "gate_candidates.json"

# Title substrings that plausibly carry a gate / door / actuator signal. Broad on
# purpose (discovery is cheap); relevance is decided from sampled fields, not names.
GATE_KEYS = ["gate", "door", "actuator", "shutter", "barrier", "flap", "hatch"]
# QUADRON ERROR HISTORY is the mapping's claimed secondary — pull it too so we can
# confirm/deny whether it actually carries a gate column (it was shuttle-only for the
# Shuttle module; re-verify for gate error codes here).
EXTRA_KEYS = ["quadron error history", "quadron alerts", "quadron"]


def _full_url(base_url: str, dash_url: str) -> str:
    if dash_url.startswith("http"):
        return dash_url
    p = urlparse(base_url)
    return f"{p.scheme}://{p.netloc}{dash_url}"


def do_discover(session) -> list:
    base = get_config().grafana.base_url
    dashboards = session.search_dashboards()
    rows = [
        {
            "uid": d.get("uid", ""),
            "folder": d.get("folderTitle", "General"),
            "title": d.get("title", ""),
            "url": _full_url(base, d.get("url", "")),
        }
        for d in dashboards
    ]
    print(f"\n=== {len(rows)} dashboards total ===")

    def _match(keys):
        return [r for r in rows if any(k in r["title"].lower() for k in keys)]

    gate_hits = _match(GATE_KEYS)
    extra_hits = [r for r in _match(EXTRA_KEYS) if r not in gate_hits]

    print("\n=== GATE / DOOR candidates (title match) ===")
    if gate_hits:
        for r in gate_hits:
            print(f"  [{r['folder']:<14}] {r['title']:<40} uid={r['uid']}\n      {r['url']}")
    else:
        print("  (NO title match for gate/door/actuator — inspect Maintenance folder manually)")

    print("\n=== Related error/alert dashboards to re-verify (mapping's claimed secondary) ===")
    for r in extra_hits:
        print(f"  [{r['folder']:<14}] {r['title']:<40} uid={r['uid']}\n      {r['url']}")

    print("\n=== Maintenance folder (the mapping puts Quadron-gate-status here) ===")
    for r in sorted([r for r in rows if r["folder"] == "Maintenance"], key=lambda x: x["title"]):
        print(f"  {r['title']:<44} uid={r['uid']}")

    candidates = gate_hits + extra_hits
    CAND_PATH.write_text(json.dumps({"candidates": candidates, "all": rows}, indent=2, default=str))
    print(f"\nwrote {CAND_PATH}  ({len(candidates)} candidates)")
    return candidates


def _candidate_urls(session, urls) -> list:
    if urls:
        return [(urlparse(u).path.rstrip("/").split("/")[-1] or u, u) for u in urls]
    if CAND_PATH.exists():
        cands = json.loads(CAND_PATH.read_text()).get("candidates", [])
    else:
        cands = do_discover(session)
    return [(c["title"], c["url"]) for c in cands]


def do_meta(session, urls) -> None:
    report = {}
    for name, url in _candidate_urls(session, urls):
        try:
            info = inspect_dashboard(session, url)
        except Exception as exc:  # noqa: BLE001
            print(f"!! {name}: enumeration failed: {exc}")
            continue
        panels = info["panels"]
        report[info["meta"].get("uid") or name] = {
            "name": name, "url": url, "meta": info["meta"],
            "panels": [{"panel_id": p.panel_id, "title": p.title, "type": p.type,
                        "is_action": p.is_action_panel, "sql_text": p.sql_text} for p in panels],
        }
        print(f"\n### {info['meta'].get('title', name)}  "
              f"(uid={info['meta'].get('uid')}, folder={info['meta'].get('folder')}, "
              f"vars={info['meta'].get('templating')})")
        for p in panels:
            flag = " [ACTION]" if p.is_action_panel else ""
            sql = (p.sql_text[:160].replace("\n", " ") + "…") if p.sql_text else ""
            print(f"  #{p.panel_id:<3} {p.type:<12} {p.title[:40]:<40}{flag}  {sql}")
    (OUT / "gate_panels_meta.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nwrote {OUT / 'gate_panels_meta.json'}")


def do_sample(session, urls, window) -> None:
    meta_path = OUT / "gate_panels_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    targets = _candidate_urls(session, urls)
    for name, url in targets:
        panels = None
        for entry in meta.values():
            if entry.get("url") == url:
                panels = entry.get("panels")
                break
        if panels is None:
            panels = [{"panel_id": p.panel_id, "title": p.title, "is_action": p.is_action_panel}
                      for p in inspect_dashboard(session, url)["panels"]]
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
                    print(f"        e.g. {json.dumps(s['sample_rows'][0], default=str)[:240]}")
            except Exception as exc:  # noqa: BLE001
                samples[pid] = {"error": str(exc)}
                print(f"  #{pid:<3} {p['title'][:34]:<34} -> {str(exc)[:70]}")
        key = urlparse(url).path.rstrip("/").split("/")[-1] or name
        (OUT / f"gate_{key}_samples.json").write_text(json.dumps(samples, indent=2, default=str))


def main() -> None:
    cfg = get_config()
    args = sys.argv[1:]
    mode = args[0] if args else "discover"
    window = cfg.fetch_default_window
    if "--window" in args:
        i = args.index("--window")
        window = args[i + 1]
        args = args[:i] + args[i + 2:]
    urls = [a for a in args[1:] if a.startswith("http")]
    with GrafanaSession() as gs:
        if mode == "discover":
            do_discover(gs)
        elif mode == "meta":
            do_meta(gs, urls)
        elif mode == "sample":
            do_sample(gs, urls, window)
        else:
            print(f"unknown mode '{mode}' (use: discover | meta | sample)")


if __name__ == "__main__":
    main()
