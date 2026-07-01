# Codebase Audit & Hardening Report — Session 12 (2026-07-01)

> **Scope:** a full correctness / methodology / RCA-quality audit of the entire ASRS
> Predictive-Maintenance codebase — all **11 modules** (Lift, Shuttle, Conveyor, Tracker,
> Gate, Bin, GTP Station, Decant Station, Network, Controller, Meta), the shared
> **core** (runner, registry, scheduler, config, CSV/MySQL storage) and the **webapp**
> (export/delete/archive/restore). Requested by the CEO note (`ceo_thoughts.md`, Task 1):
> *“check that all the logics etc are correct … fix any logical error … make the RCA
> insightful … store to CSV with an env toggle to MySQL.”*

## How the audit was run

A fan-out of independent senior-reviewer passes (one per module + core + webapp), each
reading the real code **and** the sampled panel data in `data/inspection/`, then an
**adversarial verification** pass that re-read the code for every raised finding and
either **CONFIRMED**, marked **PLAUSIBLE**, or **REJECTED** it with a concrete failure
trace. Only confirmed/plausible findings were acted on. 41 findings were raised, 4 were
rejected as misreads, and the rest were fixed. Two modules (Gate, Bin) were re-audited
directly. A regression-test suite was added; the full suite is **31/31 green**.

## Headline conclusion

The system is **architecturally sound**: a clean self-registering plugin model, a
consistent penalty-based scoring methodology, correct normalisation (rates/ratios/robust
z-scores rather than raw counts), and a genuinely useful longitudinal store. The defects
found were **calibration, edge-case, and RCA-insight** issues plus a small number of real
correctness bugs — now fixed. No module was fundamentally mis-designed and no panel was
found to be irrelevant (the mapping's prior corrections all hold up).

## CSV / MySQL storage requirement (Task 1) — already satisfied, verified

- `STORAGE_BACKEND=csv` (in `.env`); `DATA_DIR=data` → all datasets persist under
  `data/store/*.csv`, mirroring `db/schema.sql` 1:1.
- `core/storage/__init__.py::get_storage()` switches on `STORAGE_BACKEND`; the MySQL
  backend stays **dormant behind a second gate** (`MYSQL_CONFIRM=ENABLE`) so it can never
  connect by accident. No calling code changes when the backend is switched.
- Hardened this session (see Core below): atomic id-sequence writes, self-healing id
  counter, lock-leak safety, string-boolean round-trip, deterministic ordering.

---

## Fixes by area

Severity is post-verification. **H** = high, **M** = medium, **L** = low.

### Core — storage & webapp
| Sev | File | Defect → Fix |
|-----|------|--------------|
| H | `webapp/exporting.py` | `restore()` re-serialised the string `"false"` through `bool()` → every stored `false` flipped to `true`. **Fix:** `CsvBackend._serialise` now interprets string boolean literals symmetrically (protects all callers). |
| H | `webapp/exporting.py` | A bare-date `date_to` used a raw string `<=` compare, silently dropping every row timestamped later on the end date. **Fix:** inclusive date-prefix compare for bare dates. |
| H | `webapp/exporting.py` | `delete()` looped one id at a time, rewriting the whole CSV per row (O(N·filesize), lock held the whole batch). **Fix:** single set-membership `{"id": ("in", …)}` delete → one rewrite. |
| M | `core/storage/csv_backend.py` | `_FileLock.__enter__` could leak the in-process lock if `open()` failed after `acquire()`. **Fix:** exception-safe acquire/release; `__exit__` guards a `None` handle. |
| L | `core/storage/csv_backend.py` | `.seq` id counter written non-atomically → a crash mid-write could duplicate PKs. **Fix:** temp-file + `os.replace`; missing/corrupt counter self-heals from `max(existing id)`. |
| L | `core/storage/csv_backend.py` | Descending `order_by` had no tiebreak and sorted NULLs to the top. **Fix:** deterministic secondary sort on `id`; NULLs always last. |
| L | `core/storage/mysql_backend.py` | `upsert` used `row[k]` for key cols (KeyError on a missing key) vs CSV's `row.get(k)`. **Fix:** `row.get(k)` for backend parity. |
| L | `webapp/exporting.py` | Dead, broken `build_filters()` (its `date_to` branch re-applied the lower bound). **Fix:** deleted; `_select()` is the single source of truth. |
| L | `webapp/exporting.py` | `archive()` on a keyless table (e.g. `automation_config`) wrote the archive but deleted 0 rows → duplicates on restore. **Fix:** keyless branch deletes by primary key. |

### Modules — correctness, methodology, RCA
| Sev | Module | Defect → Fix |
|-----|--------|--------------|
| H | conveyor | A **stalled/dead zone** (zero throughput) scored a perfect 100 because only congestion *above* 1.0 was penalised — the exact belt/motor stall PdM must catch was invisible. **Fix:** new `stall_idle` signal = peer-anomalous idleness (fires when a zone is idle while peers flow; a plant-wide quiet period yields no false flag). Also wired the documented-but-unused `congestion_p90` as a `sustained_congestion` signal. |
| H | bin_mech | **Block-age anchored to `max(blockedTime)`** → the freshest slot always read age 0 and a systemic backlog (many old blocks, nothing new) escaped the block-age signal entirely. **Fix:** anchor to the actual run time (falls back to newest block on clock skew). |
| H | bin_mech | Block-age **peer-z over-fired on trivially-fresh blocks** and was silent on uniformly-stuck sets. **Fix:** gate peer-z by an absolute stuck-age floor. |
| M | lift | `severity` + `mechanical` (two intensity ratios off the SAME code) were un-volume-gated → a single stale mechanical error drove a lift to WARN. **Fix:** volume-gate both ratios by fault count. |
| M | lift/shuttle/tracker/gate/bin_mech | Trend-regime `np.polyfit` was **unguarded** against identical timestamps (LinAlgError → whole run fails). **Fix:** zero-spread guard + `try/except` in every module's `_trend` (matches meta/controller which already guarded). |
| M | shuttle | `current_daily` double-counted today's errors already scored by the windowed `epc`/severity. **Fix:** penalise only the **excess** of daily over the window count. |
| M | shuttle | epc fallback fabricated `n·1000` for a cycle-less shuttle, polluting the fleet median/z. **Fix:** epc = `None` when cycles unknown; excluded from peers. Raw-count `current_badtracker` → binary pick-error state. Cycles-trend now **falls back to a time-based slope** when cumulative cycles are static (frozen data), so the trend regime can still activate. |
| M | tracker | `cluster` + `recent_cluster` + `peer_z` triple-counted one cluster. **Fix:** `cluster` scores **stale** totes only (disjoint from recent); `peer_z` cap reduced (a deviation signal, not a third count). |
| M | tracker | `dominant_shuttle_share` divided by all rows incl. NaN-shuttle rows → weakened the ≥0.6 shuttle cross-flag. **Fix:** divide by shuttle-attributed rows. |
| M | decant_station | Missing/`Unknown` station status set `is_active=False` → false offline-persistence. **Fix:** tri-state (`None` for Unknown). |
| M | network | `today_downtime%` could exceed 100% (panel #2 divides by seconds-since-midnight) and was unclamped → absurd RCA (“150% downtime today”). **Fix:** clamp both downtime figures to `[0,100]`. |
| M | controller | If `cpu_idle` was renamed but `cpu_sql` matched, idle defaulted to 0 → false 100% utilisation → false system-wide critical/meta alarm. **Fix:** require the `cpu_idle` column. |
| M | meta | `has_meta_flag` (the first-class `→ meta` escalation from controller/network) was computed but **never consumed**. **Fix:** a bounded `meta_flag` penalty surfaces a coordinated cross-unit pattern as ≥ watch. |
| M | meta | The `breadth` penalty (16·(b−1), cap 48) **saturated at 4 modules**, so 4/5/6-module aisles were indistinguishable and all floored to 0/critical. **Fix:** rebalanced to 9·(b−1) cap 45 — discrimination preserved through breadth 6. |
| L | gate | Cold-start confidence rose with **signal magnitude**, not data sufficiency. **Fix:** confidence tracks prior-run depth (same fix applied to controller & meta cold-start). |
| L | gate | `stuck_recurrence` was a raw count (held a recovered gate down forever). **Fix:** converted to a decaying **rate**. RCA now distinguishes peer-deviation from own-history rate and **leads with an aisle-wide common cause** when ≥3 gates on an aisle are non-closed. |
| L | tracker | Window parser mapped Grafana `m` to *months* (should be *minutes*); `M` never matched. **Fix:** correct Grafana unit table (`m`=min, `M`=months). |
| L | controller | `sql_share` could exceed 1 when reported `cpu_sql > utilisation`. **Fix:** clamp `sql` to utilisation before the ratio. |
| L | decant_station | Scanner recurrence wasn't volume-gated (noisy low-scan device could compound). **Fix:** recurrence counts only prior runs with adequate volume. |
| L | bin_mech | Chronic-slot `historical` penalty was a raw frozen count with a large (24-pt) cap. **Fix:** cap reduced to 12 (enrichment prior, not a tier driver). Aisle-06 history-SQL gap and a missing-tracker-column degradation are now logged. |
| L | lift/meta/gtp_station | RCA/doc polish: lift RCA now surfaces fault-timing context; meta & gtp READMEs corrected (dynamic aisle roster; 263-scanner universe after the decant exclusion). |

### Cross-cutting invariants now enforced (see `docs/notebook/methodology.md §12`)
1. **Confidence reflects evidence, not severity** — every cold-start branch ties confidence to store depth, capped at 0.85 (a loud single snapshot is *low* confidence).
2. **No raw counts drive penalties** — remaining count-based penalties were converted to rates, binary states, or volume-gated.
3. **Trend fits are crash-safe** — every `np.polyfit` is guarded against zero time-spread.
4. **Percentages are physically bounded** — downtime/utilisation/shares clamped to their real ranges.
5. **Peer-deviation signals don't double-count the absolute signal** and are gated by an absolute floor.

## Verification
- `python -m pytest tests/ -q` → **31 passed** (19 pre-existing + 12 new regression tests covering the fixes above).
- Every module scores cleanly on empty input (no crashes); conveyor stall, lift volume-gate, bin_mech block-age, network clamp, controller idle-guard, and meta escalation were each verified with a targeted scenario.

## Not changed (verified correct / by design)
- No panel was found irrelevant; the mapping's earlier source reassignments hold.
- Meta's “a lone flagged module leaves its aisle `ok`” no-double-count invariant is preserved (the `meta_flag` penalty fires only on an explicit `→ meta` escalation).
- Bin_mech's recurrence-driven health decline (M2) is intentional (persistence = degradation); only its `polyfit` was hardened.
