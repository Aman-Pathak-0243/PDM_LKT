"""CONTROLLER / COMPUTE data-source discovery + inspection (SOP steps 2-4).

The mapping (§10) lists a single Controller / Compute candidate — *CPU Stats* (CPU Utilization
folder) — described as "CPU / memory utilization trend". But the mapping has been wrong in EVERY
prior session (Session 9: Quadron Network status was per-shuttle uptime%, not latency/packet-loss;
Session 8: the decant "Discrepancy Marked" dashboards were frozen-2022 drill-downs), so this helper
**re-verifies by live inspection** rather than trusting it:

  discover : /api/search for cpu / memory / compute / host / node / controller / utilization candidates
             -> uid / folder / title / URL, plus the whole CPU Utilization folder listed.
  meta     : enumerate every panel (id/title/type/SQL) + template vars. ids from the model.
  sample   : pull a small slice of each non-action panel to reveal real columns + rows, so the
             COMPUTE component identity (per-host? per-node? per-controller/PLC?) + the CPU/memory
             saturation signal (the mapped leading indicator) can be judged before any module.

Key questions to answer by sampling:
  * Does a LIVE CPU/memory utilization feed actually exist, or is this operational/other?
  * What is the component key — a host/node id? a controller/PLC? an IP? one aggregate server?
  * Is it a timeseries (like Conveyor's zone counts) or a current-state snapshot? retention/window?
  * Which metrics are present — CPU%, memory%, load, disk, temperature?

Usage:
    .venv/bin/python scripts/inspect_controller.py discover
    .venv/bin/python scripts/inspect_controller.py meta   [--window now-2d] [url ...]
    .venv/bin/python scripts/inspect_controller.py sample [--window now-2d] [url ...]
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
CAND_PATH = OUT / "controller_candidates.json"

# Title substrings that plausibly carry a CPU / memory / compute / host signal.
CPU_KEYS = ["cpu", "memory", "ram", "utilization", "utilisation", "compute", "processor", "load average"]
# Cross-cutting infra signals worth re-verifying regardless of folder.
EXTRA_KEYS = ["host", "node", "server", "controller", "system stat", "resource", "disk", "kepware", "opc"]


def _full_url(base_url: str, dash_url: str) -> str:
    if dash_url.startswith("http"):
        return dash_url
    p = urlparse(base_url)
    return f"{p.scheme}://{p.netloc}{dash_url}"


def do_discover(session) -> list:
    base = get_config().grafana.base_url
    rows = [
        {"uid": d.get("uid", ""), "folder": d.get("folderTitle", "General"),
         "title": d.get("title", ""), "url": _full_url(base, d.get("url", ""))}
        for d in session.search_dashboards()
    ]
    print(f"\n=== {len(rows)} dashboards total ===")

    def _match(keys):
        return [r for r in rows if any(k in r["title"].lower() for k in keys)]

    cpu_hits = _match(CPU_KEYS)
    extra_hits = [r for r in _match(EXTRA_KEYS) if r not in cpu_hits]

    print("\n=== CPU / MEMORY / COMPUTE / UTILIZATION candidates (title match) ===")
    for r in cpu_hits:
        print(f"  [{r['folder']:<16}] {r['title']:<46} uid={r['uid']}\n      {r['url']}")
    print("\n=== Related infra dashboards to re-verify (host/node/server/controller/…) ===")
    for r in extra_hits:
        print(f"  [{r['folder']:<16}] {r['title']:<46} uid={r['uid']}\n      {r['url']}")
    print("\n=== CPU Utilization folder (the mapping puts CPU Stats here) ===")
    for r in sorted([r for r in rows if r["folder"] == "CPU Utilization"], key=lambda x: x["title"]):
        print(f"  {r['title']:<46} uid={r['uid']}\n      {r['url']}")
    print("\n=== All folders present (for orientation) ===")
    folders = sorted({r["folder"] for r in rows})
    print("  " + " | ".join(folders))

    candidates = cpu_hits + extra_hits
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
                        "is_action": p.is_action_panel, "sql_text": p.sql_text} for p in panels]}
        print(f"\n### {info['meta'].get('title', name)}  "
              f"(uid={info['meta'].get('uid')}, folder={info['meta'].get('folder')}, "
              f"vars={info['meta'].get('templating')})")
        for p in panels:
            flag = " [ACTION]" if p.is_action_panel else ""
            sql = (p.sql_text[:220].replace("\n", " ") + "…") if p.sql_text else ""
            print(f"  #{p.panel_id:<3} {p.type:<12} {p.title[:40]:<40}{flag}  {sql}")
    (OUT / "controller_panels_meta.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nwrote {OUT / 'controller_panels_meta.json'}")


def do_sample(session, urls, window) -> None:
    meta_path = OUT / "controller_panels_meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    for name, url in _candidate_urls(session, urls):
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
                    print(f"        e.g. {json.dumps(s['sample_rows'][0], default=str)[:260]}")
            except Exception as exc:  # noqa: BLE001
                samples[pid] = {"error": str(exc)}
                print(f"  #{pid:<3} {p['title'][:34]:<34} -> {str(exc)[:70]}")
        key = urlparse(url).path.rstrip("/").split("/")[-1] or name
        (OUT / f"controller_{key}_samples.json").write_text(json.dumps(samples, indent=2, default=str))


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
