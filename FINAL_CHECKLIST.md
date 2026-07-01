# Final Checklist — CEO tasks (`ceo_thoughts.md`)

> Tracking file for the tasks in `ceo_thoughts.md`. Task 1 runs in **this** session;
> Tasks 2–8 run in a **follow-up** session (see the kickoff prompt printed at the end
> of Session 1). Checks are updated as each task completes.

## Working rules (from the CEO note)
- [x] (a) Maintain this checklist and tick tasks as they are completed.
- [x] (b) Task 1 = one session; Tasks 2–8 = a second session, started via a kickoff prompt printed at the end of Session 1.
- [x] (c) For every requested markdown: update the existing relevant file if one exists, else create it.

---

## Task 1 — Codebase & module audit + fixes  *(this session — COMPLETE)*
- [x] Analyze the entire codebase and every module in detail (methodologies, health logic, panel relevance). — full fan-out audit + adversarial verification; see `docs/AUDIT_REPORT.md`.
- [x] Verify each module's health-scoring logic is correct; fix any logical errors found. — 28 confirmed + 9 plausible findings fixed across all 11 modules + core + webapp.
- [x] Verify the panels each module consumes are relevant health signals; fix/flag if not. — no irrelevant panels; the mapping's prior source reassignments all hold; conveyor gained a stall signal, controller now requires the real idle column.
- [x] Assess RCA quality per module; make RCA more insightful where it is weak. — gate (aisle common-cause leads), network (bounded downtime), tracker (pick-error surfaced), lift (fault timing), shuttle/meta labels, meta escalation consumed.
- [x] Confirm CSV storage folder exists and an env toggle switches CSV ⇄ MySQL. — `STORAGE_BACKEND=csv`, `data/store/*.csv`, gated dormant MySQL backend; storage layer additionally hardened (atomic seq, lock safety, bool round-trip, deterministic ordering).
- [x] Run the regression tests and confirm green after fixes. — **31/31 pass** (19 pre-existing + 12 new).
- [x] Print `done master`.
- [x] Print the kickoff prompt for Session 2 (Tasks 2–8).

## Task 2 — Operator SOP  *(session 2 — COMPLETE)*
- [x] Markdown: how an operator runs the system, what to monitor regularly, where each thing lives (navigation), regular vs interval tasks. → [`docs/OPERATOR_SOP.md`](docs/OPERATOR_SOP.md).

## Task 3 — Hosting resources  *(session 2 — COMPLETE)*
- [x] Markdown: resources required to host (MySQL DB size projection from the measured ~1.6 KB/row, CPU/RAM/disk, LAN/firewall, backup). → [`docs/HOSTING_RESOURCES.md`](docs/HOSTING_RESOURCES.md).

## Task 4 — Developer guide + DB migration/export  *(session 2 — COMPLETE)*
- [x] Markdown: everything a developer needs to develop/maintain/update the code. → [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md).
- [x] Document the "database full → back up & export to another DB" workflow. → Developer Guide §6.
- [x] Write the backup/export script and reference it. → [`scripts/db_migrate_export.py`](scripts/db_migrate_export.py) (stats/backup/copy/load/verify; MySQL-gated; smoke-tested: 2,715 rows copied+verified). Referenced in the Developer Guide + Hosting Resources.

## Task 5 — System overview  *(session 2 — COMPLETE)*
- [x] Markdown: how the system is built, what it tracks, the value it adds. → [`docs/SYSTEM_OVERVIEW.md`](docs/SYSTEM_OVERVIEW.md).

## Task 6 — URL / route map  *(session 2 — COMPLETE)*
- [x] Markdown: every system URL, where it goes, and its features (HTML pages + JSON API, enumerated from `webapp/main.py` + `webapp/api.py`). → [`docs/URL_MAP.md`](docs/URL_MAP.md).

## Task 7 — Module health methodology reference  *(session 2 — COMPLETE)*
- [x] Markdown: per-module — which dashboards/panels, which fields matter and why, and how the fields become the health algorithm. → [`docs/MODULE_METHODOLOGY.md`](docs/MODULE_METHODOLOGY.md).

## Task 8 — Word notebook  *(session 2 — COMPLETE)*
- [x] Compile all markdown files into a single Word notebook with references and contents. → [`docs/ASRS_PdM_Notebook.docx`](docs/ASRS_PdM_Notebook.docx) (6 parts, 24 sections incl. all 11 module chapters, 129 tables, auto-TOC field + explicit contents list). Rebuild: [`scripts/build_notebook.py`](scripts/build_notebook.py).
