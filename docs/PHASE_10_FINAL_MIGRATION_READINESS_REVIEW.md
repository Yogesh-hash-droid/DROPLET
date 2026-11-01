# Phase 10 — Final Migration Readiness Review (Phase F)

> **Status:** READ-ONLY REVIEW — **no migration executed, no SQL executed, no database connection opened during this review.**
> **Scope of this document:** evidence-based readiness assessment of the Phase 10 six-statement migration against `database/migrations/phase9_scope_reconciliation.sql`.
> **Authorization boundary:** Phase F (final migration readiness review) ONLY. **This document is NOT production migration approval.**
> **Date:** 2026-10-31

---

## 1. Executive summary

Every rehearsal gate defined by the Phase 10 plan (§7.4–§7.6, §12 Gate 3 preparation) has been executed and its results recorded: a verified pre-migration backup, a staging restore with zero differences, a six-for-six forward migration rehearsal with per-statement verification, and a seven-for-seven guarded rollback rehearsal that returned an isolated copy to a **byte-identical pre-migration baseline** (`STEP5_VERIFY_OK`, 30/30 verdicts). Backend code is green on DB-free tests (171 passed / 0 failed, session-recorded at Step 2 regression), the non-finite input fix is present and tested, and the ML artifact hash is unchanged.

**Recommendation: READY — conditional.** No technical blocker was found in the backup, schema, data-preservation, or rollback evidence. The remaining items are (a) the expected approval gate (production migration requires separate explicit approval), (b) process safeguards to perform at execution time (fresh backup, maintenance window, post-migration checks, deployment ordering), and (c) warnings that are real but out of scope of this migration (least-privilege/root usage, `reading_id` model↔schema unique mismatch, P2 admin auth, documentation gaps). Conditions are listed in §13.

---

## 2. Scope and authorization boundary

| Item | Status |
|---|---|
| Phase F — final migration readiness review | **APPROVED and performed (read-only)** |
| Production migration execution | **NOT APPROVED — BLOCKED pending separate explicit approval** |
| Phase 11 start | **NOT APPROVED — BLOCKED** |
| SQL execution / DB connection during this review | **NONE** (file reads, SHA-256 hashing, and offline parsing of the backup file only) |
| Files modified in `D:\EVS` during this review | **This report only** |

---

## 3. Evidence reviewed

**Documents (project files):**

| # | Evidence | Location / detail |
|---|---|---|
| 1 | Phase 10 backend implementation plan | `docs/PHASE_10_BACKEND_IMPLEMENTATION_PLAN.md` (75,115 B; §7 DB-compat 466–551, §9 test matrix 634–670, §10 file inventory 674–700, §11 risks 704–720, §12 gates 724–731) |
| 2 | Phase 9 migration design | `docs/PHASE_9_MIGRATION_DESIGN.md` (12,622 B; §4 sequence, §7 rollback 155–163, §8 risks 167–176) |
| 3 | Migration script (6 forward + commented 7-statement rollback) | `database/migrations/phase9_scope_reconciliation.sql` — 19,627 B, 337 lines, SHA-256 `994B945D6E8621161F33148D362B255100953C95364C2EE7B90C1EEB47435650`; forward ALTERs at lines 105, 120, 134, 169, 205, 228; Section 6 rollback at lines 282–337 |
| 4 | Baseline schema reference | `database/schema.sql` (2,970 B, last written 2026-10-06) |
| 5 | Phase 10 backend implementation artifacts | `backend/app/**` (newest source `app/main.py` 2026-10-31 00:02), `backend/tests/test_phase10_contract.py` (45,559 B, 79 tests), `test_readings_unit.py` |
| 6 | Test cache artifacts | `backend/.pytest_cache/v/cache/nodeids` (215 collected test IDs, written 2026-10-31 07:27) and `lastfailed` = `{}` (empty → no recorded failures, written 2026-10-31 00:02) |
| 7 | Verified backup | `database/backups/water_quality_db_pre_phase10_20261031_083234.sql` — 113,699 B, 2026-10-31 08:32:34, SHA-256 `188379095AAA28D76FC25D6D84D94165B38E152A7393DE5D3E8FCB014615C355` (hash re-verified during this review) |
| 8 | Step 5 live schema verification tooling | `Temp\opencode\evs_live_schema_verify.py` (read-only SELECT/SHOW whitelist, credentials never printed) |
| 9 | Phase 6 rehearsal tooling + extracts | `Temp\opencode\evs_staging_verify.py`, `evs_staging_postverify.py`, `evs_rowlevel_proof.py`, `evs_phase_e_step5_verify.py`, forward-statement extracts `evs_e_fwd_stmt_1..6.sql`, rollback extracts `evs_rb_*.sql` + `evs_rb_guard_*.txt` |
| 10 | Account inventory tooling | `Temp\opencode\evs_accounts_check.py` (Phase 6 Phase A, read-only) |
| 11 | ML artifact | `ml/models/water_potability_model.joblib` — SHA-256 `F446308C985584261D44A51428CC4AD68930DEAF9F5044A599555CC9B1DAACC6` (re-verified during this review) |

**Session-recorded results (executed earlier in this Phase 10 session; tooling persisted as above, but console outputs were not persisted as project documents):** Phase 5 live verification (`VERIFY_OK`), Phase 6 Phase B (backup), Phase C (staging restore), Phase D (forward rehearsal), Phase E (rollback rehearsal, `STEP5_VERIFY_OK` 30/30).

> **Evidence-class note used throughout:** items marked PASS below rest on *persisted artifacts* (files/hashes re-checked in this review) and/or *session records of executed verification runs*. Where only a session record exists and no persisted report, that is stated explicitly.

---

## 4. Backup and recovery assessment

| # | Finding | Verdict |
|---|---|---|
| A1 | Backup exists at `D:\EVS\database\backups\water_quality_db_pre_phase10_20261031_083234.sql`; 113,699 bytes; timestamp 2026-10-31 08:32:34; SHA-256 `188379095AAA28D76FC25D6D84D94165B38E152A7393DE5D3E8FCB014615C355` — re-hashed in this review, matches the Phase B record | **PASS** |
| A2 | File structure (parsed offline in this review): mysqldump 8.0.46 header, `Database: water_quality_db`, **4 `CREATE TABLE`** (devices, predictions, system_config, water_readings) + **4 `INSERT`** (all four tables), **0 `CREATE DATABASE`, 0 `USE`** | **PASS** |
| A3 | Backup represents the **pre-migration** database: the restored copies carried `enum('SIMULATION','ESP32')`, `ph/temperature NOT NULL`, no `score_method`, no band columns, no `idx_score_method`, thresholds `NOT NULL` (Phase C pre-check and Phase E Step 2 verification, both session-recorded with tooling persisted) | **PASS** |
| A4 | Backup is **restorable** — proven twice: Phase C restore into `water_quality_db_staging_phase10` (exit 0, verification with 0 differences vs baseline) and Phase E restore into `water_quality_db_phase10_rollback_test` (exit 0, counts 77/503/500/1) | **PASS** |
| A5 | Backup integrity re-validated after all rehearsals: hash + size unchanged at review time; backup never overwritten or deleted | **PASS** |
| A6 | Recovery procedure documented: full dump (plan §7.4), restore-then-verify (§7.4 item 2), "preferred rollback = restore pre-migration mysqldump" (migration script line 332, Phase 9 design §7) | **PASS** |
| A7 | The dump contains `DROP TABLE IF EXISTS` for its 4 tables (standard mysqldump) and **no self-selecting `USE`/`CREATE DATABASE`**: restore replaces tables in whichever schema is passed to the client — this is a safeguard (the file cannot silently target a database by itself) **and** a risk (the operator must pass the correct schema explicitly) | **WARNING** (procedure must state the exact restore command with target schema) |
| A8 | Single backup copy on the same host/disk as the source server; no offsite/second copy documented; no binlog/PITR recovery procedure documented (Phase A printed `gtid_mode`/`log_bin`, but values were not persisted to a project file) | **WARNING** |
| A9 | Backup recency: taken 2026-10-31 08:32. No writes to production have occurred since (production verified untouched in Phase E). At execution time a **fresh backup (or hash + counts re-confirmation)** is still required | **WARNING** (condition, §13) |

**Recovery-procedure sufficiency:** SUFFICIENT for this migration — restore path exercised twice end-to-end, all four tables included, integrity hashes recorded. **Limitations:** single-copy storage, no PITR documented, restore command/schema targeting must be explicit, no documented retention/expiry policy for the dump.

---

## 5. Schema and migration assessment

### 5.1 Baseline vs intended statements

The six forward statements in the migration file (re-read in this review, verbatim anchors confirmed at lines 105/120/134/169/205/228):

| # | Section | Statement | Effect |
|---|---|---|---|
| 1 | §1 (line 105) | `ALTER TABLE water_readings` — `ph`/`temperature` → NULL (+comments), `source` → `ENUM('SIMULATION','ESP32','ESP8266')` | nullable sensors + enum widening (combined, one table rebuild) |
| 2 | §2 (line 120) | `ALTER TABLE system_config` — `ph_min/ph_max/temperature_min/temperature_max` → NULL | optional legacy thresholds, values preserved |
| 3 | §3 (line 134) | `ALTER TABLE devices` — `source` → 3-member enum | enum widening |
| 4 | §4 (line 169) | `ADD COLUMN score_method ENUM(...) NULL DEFAULT NULL AFTER quality_score` (guarded) | R-3 discriminator |
| 5 | §4B (line 205) | `ADD COLUMN status_good_min FLOAT NOT NULL DEFAULT 70.0, status_poor_max FLOAT NOT NULL DEFAULT 40.0` (guarded) | R-2 = B1 bands |
| 6 | §4C (line 228) | `ADD INDEX idx_score_method (score_method)` (guarded) | model parity |

| # | Finding | Verdict |
|---|---|---|
| B1 | Plan, design doc, and script agree on **6** executable DDL statements (plan §7.2/§10/§11 R-2/R-3; design §4 note; script lines above) | **PASS** |
| B2 | Verified production baseline (31 columns / 15 index rows / 8 constraints / 2 FKs, session-recorded in Phase C/E) matches `database/schema.sql` structure (7+8+8+8 columns, 8 named indexes + 4 PKs + `device_id` UNIQUE + composite `idx_device_reading`×2 = 15 index rows, 8 constraints) — **no drift found** | **PASS** |
| B3 | Pre-migration live state confirmed before rehearsal: `score_method` absent, band columns absent, `idx_score_method` absent, enums 2-member, `ph/temp`/thresholds `NOT NULL` (Phase 5 `VERIFY_OK` + Phase C pre-check; session-recorded, tooling persisted) | **PASS** |
| B4 | Statement 1–3 effects rehearsed on **staging** (Phase D) and on the **rollback copy** (Phase E): enums widened to 3 members, `ph/temperature` nullable, thresholds nullable | **PASS** |
| B5 | Statement 4 (`score_method`) rehearsed on both copies; column present, `DEFAULT NULL`, enum of 2 members | **PASS** |
| B6 | Statement 5 (bands) rehearsed on both copies; 2 columns present with defaults **70.0 / 40.0**, all pre-existing config values unchanged (`6.5/8.5/500/5/10/35`) | **PASS** |
| B7 | Statement 6 (`idx_score_method`) rehearsed on both copies; index present, non-unique, on `score_method` | **PASS** |
| B8 | All six statements applied **one at a time with per-statement verification** on both copies (Phase D: 6/6 exit 0 + individually verified; Phase E: 6/6 exit 0 + guards + verification), file guards (information_schema) all returned the expected pre-state | **PASS** |
| B9 | Idempotency/re-run guards for statements 4–6 encoded in the script (lines 161–167, 195–204, 221–227) and exercised during rehearsal | **PASS** |
| B10 | `database/schema.sql` intentionally **not yet synced** with the six changes (plan §10: sync after migration approval) — expected, must be done post-migration | **WARNING** (pending action, §13) |
| B11 | Plan text still says "the live database schema has not been verified" (§7 opening, line 468; §7.3 line 514) although Phase 5 live verification completed (`VERIFY_OK`) — documentation staleness only | **WARNING** |
| B12 | Staging ALTER **timings/lock measurements** required by §7.4 item 3 were not found in any persisted artifact | **NOT VERIFIED** (condition: measure or accept documented maintenance window, §13) |

**Schema drift / unresolved mismatch:** none found between verified baseline and `schema.sql` for this migration's scope. One **pre-existing** model↔schema mismatch exists (`Prediction.reading_id unique=True` vs no UNIQUE in DB/schema) — see §9, risk F-6; it is **not touched by this migration**.

---

## 6. Historical data preservation assessment

| # | Finding | Verdict |
|---|---|---|
| C1 | Row counts preserved at every stage: **devices 77 / water_readings 503 / predictions 500 / system_config 1** — baseline (backup), post-restore, post-forward-migration (Phase D), post-rollback (Phase E) | **PASS** |
| C2 | Historical `score_method` **all NULL (500/500)** after forward migration — no backfill, no UPDATE (Phase D post-verify + Phase E) | **PASS** |
| C3 | Row-level byte-comparison vs the verified backup: Phase D **all 4 tables IDENTICAL / 0 mismatches** (predictions compared after excluding the added column, config after excluding bands — additions were new columns, no row rewriting) | **PASS** |
| C4 | Row-level byte-comparison after rollback (Phase E): **all 4 tables byte-identical with no exclusions needed** (77/503/500/1 rows) | **PASS** |
| C5 | Aggregates exact against recorded baseline: readings sums `ph 3154.919995240867 / temp 15813.800010681152 / tds 260475.10009765625 / turb 23233.42999905348`, min/max ranges exact; predictions sums `quality_score 43282.39989089966 / confidence 218.2168864607811`, distributions `POTABLE 334 / NOT 45 / SAFE 290 / WARNING 50 / UNSAFE 160`; devices `75 SIM / 2 ESP32`; readings `483 SIM / 20 ESP32` | **PASS** |
| C6 | Checksum evidence explained and consistent: after forward migration `devices` checksum unchanged; `water_readings` changed **layout-only** (null-flag) and `predictions`/`system_config` changed (new columns) — proven value-identical by row-level comparison; after rollback **all four checksums returned exactly to the pre-migration values** (`3343005134 / 1944214664 / 3285054345 / 2228304261`) | **PASS** |
| C7 | No historical record excluded or rewritten: migration contains no `UPDATE`/`DELETE`/`DROP` of data (design §3 "explicitly unchanged"; script contains only the 6 ALTERs + read-only guards + Section 6 comments); verified by row-level identity | **PASS** |
| C8 | Config row `id=1` values preserved through all phases (`6.5/8.5/500/5/10/35`), bands land at defaults 70/40 without touching other values | **PASS** |

---

## 7. Rollback assessment

### 7.1 The seven guarded rollback statements and rehearsal results (Phase E, session-recorded; extracts + guard files persisted)

| # | Rollback statement (script lines) | Guard (must return 0) | Guard result | Executed | Effect verified |
|---|---|---|---|---|---|
| 1 | `ALTER TABLE predictions DROP INDEX idx_score_method` (298) | none in file — index carries no row data | n/a | exit 0 | index absent |
| 2 | `ALTER TABLE system_config DROP COLUMN status_good_min, status_poor_max` (307–309) | customized-value check (302–303) | **0** | exit 0 | 2 columns gone; system_config back to 8 columns; thresholds preserved |
| 3 | `ALTER TABLE predictions DROP COLUMN score_method` (294) | `COUNT(score_method IS NOT NULL)` (293) | **0** | exit 0 | column gone; predictions back to 8 columns; 500 rows |
| 4 | `ALTER TABLE devices MODIFY source ENUM('SIMULATION','ESP32')` (314) | ESP8266 rows in devices (312) | **0** | exit 0 | enum narrowed; 75/2/0 rows intact |
| 5 | `ALTER TABLE water_readings MODIFY source ENUM('SIMULATION','ESP32')` (315) | ESP8266 rows in readings (313) | **0** | exit 0 | enum narrowed; 503 rows |
| 6 | `ALTER TABLE water_readings MODIFY ph/temperature NOT NULL` (328–330) | NULL ph/temp rows (327) | **0** | exit 0 | NOT NULL restored; 503 rows |
| 7 | `ALTER TABLE system_config MODIFY thresholds NOT NULL DEFAULT ...` (320–324) | NULL threshold check (318–319) | **0** | exit 0 | NOT NULL restored; **values unchanged** |

Execution discipline: `SELECT DATABASE()` asserted to be `water_quality_db_phase10_rollback_test` before **every** statement; guards never bypassed; order = index → bands → score_method → enums → ph/temp → thresholds.

| # | Finding | Verdict |
|---|---|---|
| D1 | All 7 rollback statements rehearsed successfully with all 6 file guards returning 0 | **PASS** |
| D2 | Isolated copy returned to pre-migration baseline: **`STEP5_VERIFY_OK`, 30/30 verdicts** — 31 columns byte-equal to untouched production, 15 index rows structurally identical, 8 constraints, 2 FKs, ENGINE/collation/AUTO_INCREMENT (`81/501/507`) identical, COMMENTs back to `''`, enums back to 2 members, NOT NULL restored on ph/temp + 4 thresholds, counts/config/aggregates exact, all 4 checksums exact, row-level byte-identical to backup (session-recorded; verifier `evs_phase_e_step5_verify.py` persisted) | **PASS** |
| D3 | MySQL DDL implicit commits correctly treated as the central constraint: every statement verified individually; plan §7.5 and design §8 record "no transactional undo" | **PASS** |
| D4 | **Primary recovery method = restore of the verified pre-migration dump**, explicitly preferred over reverse-ALTERs (script line 332; design §7; plan §7.5). Reverse-ALTERs are secondary and only valid while their guards hold | **PASS** |
| D5 | Rollback-copy `CARDINALITY` statistics differ from production (8 index entries) — InnoDB estimate only, structural fields identical | **PASS** (documented, not a defect) |
| D6 | Operational risk: after production accepts real ESP8266 rows or NULL sensor values, guards 4–7 will (correctly) **fail** — reverse-ALTER rollback then becomes unavailable by design; only dump restore remains | **WARNING** (inherent; documented in script §6 header and design §7) |
| D7 | Operational risk: a mid-sequence statement failure leaves a **partial migration** (implicit commit per statement); recovery = restore dump, not statement rollback | **WARNING** (mitigated by rehearsal + one-at-a-time execution + verification) |
| D8 | Rehearsal DBs `water_quality_db_staging_phase10` and `water_quality_db_phase10_rollback_test` still exist (retained by the no-drop rule); their cleanup is **not** approved | **WARNING** (decide separately; do not drop without approval) |

---

## 8. Backend and testing assessment

| # | Finding | Verdict |
|---|---|---|
| E1 | DB-free regression run recorded at Phase 10 Step 2: **171 passed / 0 failed** (session record). Corroborating persisted artifacts: `lastfailed` = `{}` (no recorded failures) and 215 collected test IDs in the nodeids cache | **PASS** (session record; see E2) |
| E2 | No persisted console log exists for the 171-test run; the suite has since grown (`test_phase10_contract.py` now contributes 79 tests; 215 collected total). A fresh DB-free run on the **final current tree** is recommended as an execution-day condition | **WARNING** / exact current-suite pass count **NOT VERIFIED** (Phase F may not execute tests) |
| E3 | Non-finite input validation fix present in code: `app/main.py` `_json_safe_non_finite` (well-formed 422 bodies instead of HTTP 500 on raw Infinity/NaN), `app/schemas/water_reading.py` `allow_inf_nan=False`, `app/services/config_service.py` `math.isfinite` guards, `quality_service.py`/`safety_service.py` finite checks | **PASS** |
| E4 | Non-finite fix covered by tests: `test_phase10_contract.py` T10/T11 infinity params, `test_non_finite_rejection_returns_valid_json_422`, `test_t21b_config_rejects_non_finite_values`; `test_readings_unit.py` `test_non_finite_required/optional_values_rejected_unit`, `test_rejected_non_finite_creates_no_record_unit` | **PASS** |
| E5 | ML artifact unchanged: SHA-256 `F446308C985584261D44A51428CC4AD68930DEAF9F5044A599555CC9B1DAACC6` re-computed in this review — matches the Step 2 record | **PASS** |
| E6 | Compilation/import health (session record: compile checks during Workstream A; `__pycache__` bytecode regenerated, newest `main.cpython-313.pyc` 2026-10-31 07:27) — corroborating but weak evidence | **PASS** (session-recorded) |
| E7 | MySQL-dependent suites remain **BLOCKED** until production migration + Gate 4: `test_readings_integration.py` (4 tests), `test_simulator_integration.py` (4), `test_phase5_ml_api.py` (15), `test_phase3_api.py` (12) | **BLOCKED** — **these are NOT claimed to have passed** |
| E8 | Gate 4 (full regression + MySQL integration) not yet executed — by design it runs after Gate 3 (plan §12) | **BLOCKED** (expected) |

---

## 9. Risks and unresolved issues

| ID | Risk / issue | Evidence-based assessment | Verdict |
|---|---|---|---|
| F-1 | **Production backup readiness** | Backup verified + restorable (§4); single-copy storage; refresh at execution time | **WARNING** |
| F-2 | **Root account write privileges / least privilege** | Phase 6 Phase A inventory (session record): only `root@localhost` holds full privileges (+3 locked accounts); rehearsal tooling and the backend `.env` (`MYSQL_USER`, value not printed here) both operate as root. No dedicated migration/app DDL-limited account exists | **WARNING** (pre-existing; not introduced by this migration; address before production deployment) |
| F-3 | **Migration execution order & per-statement verification** | Order fixed (script order §1→§2→§3→§4→§4B→§4C); rehearsed one-at-a-time with per-statement verification twice; guards encoded | **PASS** |
| F-4 | **DDL implicit-commit risk** | Acknowledged everywhere (plan §7.5, design §8, script §6); mitigations: verified backup, rehearsal, one-at-a-time + verify, restore-as-recovery | **PASS** (mitigated; residual risk inherent to MySQL DDL) |
| F-5 | **Monitoring / post-migration validation** | Read-only acceptance checklist exists (plan §7.6; script Section 5) and its queries were exercised in rehearsal. No documented *live* monitoring plan for the maintenance window (connection errors, error-log watch, app health check after restart) | **WARNING** (document in execution runbook) |
| F-6 | **`Prediction.reading_id` model↔schema unique mismatch** | Model declares `unique=True` (`app/models/prediction.py` line 47) while `database/schema.sql` (line 41) and the verified live baseline have **no UNIQUE on `reading_id`** (only the FK; Phase E constraint inventory = 8, none on `reading_id`). Offline parse of the backup in this review: 500 predictions, **500 distinct `reading_id`, 0 duplicates, 0 orphans** → data would support adding UNIQUE later, but **this migration does not add it**, so the mismatch **persists after migration**. Project audit (`PROJECT_AUDIT_REPORT.md` line 88) describes it as "1:1 … unique", which does not match the DB | **WARNING** (pre-existing, unresolved; separate decision required; not a migration blocker) |
| F-7 | **Pending decisions P2 (admin auth) / P3 (simulator flag naming)** | Plan §11 R-11 / §12: `PUT /api/config` remains unauthenticated; explicitly out of Phase 10 scope, "P2 required before deployment" | **WARNING** (deployment condition, not migration condition) |
| F-8 | **Documentation gaps** | Phase 5 Step 5 and Phase 6 B–E results exist only as session records + tooling (no project report files before this review); `PROJECT_STATUS.md` not yet updated for Phase 10; optional `docs/PHASE_10_MIGRATION_VERIFICATION.md` (plan §10) not created; plan text stale (§7 "live schema never verified") | **WARNING** |
| F-9 | **MySQL-dependent tests blocked** | See E7/E8 — legitimate, by design | **BLOCKED** (expected until Gate 4) |
| F-10 | **Staging/lock timings not recorded** (plan §7.4 item 3) | No persisted timing evidence | **NOT VERIFIED** |
| F-11 | **Backup-relevant server flags** (gtid/binlog) | Phase A printed them but values were never persisted to a project file | **NOT VERIFIED** (informational; not required for a plain dump/restore recovery) |
| F-12 | Production write-target discipline | Production verified untouched through all phases (Phase E final status: no score_method/bands/index, 2-member enums, `ph NOT NULL`, counts 503/500); staging and rollback copy isolated | **PASS** |

---

## 10. Pre-migration checklist

To be completed at execution time (all read-only checks first; stop on any failure):

1. [ ] **Separate explicit production migration approval received** (Gate 3) — must not be assumed from this report.
2. [ ] Re-verify file integrity: migration SHA-256 = `994B945D6E8621161F33148D362B255100953C95364C2EE7B90C1EEB47435650`, 337 lines, 6 statements at lines 105/120/134/169/205/228.
3. [ ] **Take a fresh pre-migration backup** (or re-verify hash `18837909…615C355` + size 113,699 + counts 77/503/500/1 and confirm no writes since 2026-10-31 08:32) with a new dated filename; verify exit code, size, 4 tables, INSERTs.
4. [ ] Run plan §7.3 read-only drift check against live `water_quality_db` (columns/enums/nullability/indexes/constraints/row counts/MySQL version); **stop on any drift**.
5. [ ] Run the script's Section 0 baseline counts; store as evidence.
6. [ ] Confirm script guards pre-state: `score_method` count = 0, band count = 0, `idx_score_method` count = 0.
7. [ ] Confirm maintenance window; record ALTER timings/lock behaviour (F-10); optionally `ALGORITHM=INPLACE, LOCK=NONE` policy decision per design §3.
8. [ ] Confirm restoration command and target schema are written down (A7), and that the operator knows the primary recovery = dump restore.
9. [ ] Re-run the DB-free test suite on the final tree and record results (E2).
10. [ ] Confirm deployment order plan: **migration first, then backend restart/deploy** (plan R-1).

## 11. Post-migration verification checklist

1. [ ] All 6 statements exit 0; per-statement verification after each (re-run guards show post-state).
2. [ ] Row counts unchanged: 77 / 503 / 500 / 1.
3. [ ] `ph`/`temperature` and 4 thresholds `IS_NULLABLE = YES`; values intact (`6.5/8.5/500/5/10/35`).
4. [ ] Both `source` enums = `ENUM('SIMULATION','ESP32','ESP8266')`; distributions unchanged (devices 75/2, readings 483/20) and **0 ESP8266 rows** yet.
5. [ ] `score_method` present, `DEFAULT NULL`, **all 500 historical rows NULL** (no backfill).
6. [ ] `status_good_min = 70.0`, `status_poor_max = 40.0` on row `id=1`; other config values unchanged.
7. [ ] `idx_score_method` present (non-unique, on `score_method`); all 14 pre-existing index entries + composite intact; 8 constraints + 2 FKs intact.
8. [ ] Row-level comparison of all 4 tables vs the fresh backup: **identical** (predictions compared excluding `score_method`, config excluding the 2 band values — as proven in Phase D).
9. [ ] Checksum expectations: `devices` unchanged; `water_readings`/`predictions`/`system_config` **expected to change** (layout) — value equality proven by row-level comparison (do not treat as data drift).
10. [ ] Plan §7.6 acceptance queries all pass; record date/version in `PROJECT_STATUS.md`; sync `database/schema.sql`.
11. [ ] Start backend, confirm health endpoint, smoke-test `POST /api/readings` (legacy 6-field payload), `GET /api/config`, `/history` (P1 separation: historical rows with `score_method: null`).
12. [ ] Run Gate 4: MySQL-dependent suites (`test_readings_integration`, `test_simulator_integration`, `test_phase5_ml_api`, `test_phase3_api`) + full DB-free suite; report results honestly.
13. [ ] Confirm ML artifact hash still `F446308C…DAACC6`.

---

## 12. Final recommendation

# **READY** (conditional)

**Basis (verified):** backup verified and twice-restorable; staging forward rehearsal 6/6 with per-statement verification and row-level proof of data preservation; isolated rollback rehearsal 7/7 with all guards returning 0 and a byte-identical return to baseline (`STEP5_VERIFY_OK` 30/30); no schema drift in scope; no historical data rewritten or excluded; backend DB-free tests green with non-finite fix tested; ML artifact unchanged; production untouched throughout.

**Meaning of READY:** the migration is technically ready to be executed **after** the conditions in §13 are satisfied. It does **not** authorize execution — production migration remains **BLOCKED** on separate explicit approval.

## 13. Conditions that must be satisfied before production migration

**Blocking (must be satisfied — otherwise NOT READY to execute):**
1. **Separate explicit written approval for production migration** (Gate 3). This Phase F approval is not it.
2. **Fresh pre-migration backup at execution time** (or hash/size/counts re-confirmation of the existing one plus proof of no writes since 2026-10-31 08:32), with exit-code/size/4-table/INSERT verification and the exact restore command (target schema) written into the runbook.
3. **Live drift check (plan §7.3) immediately before execution**; any divergence stops the migration.
4. **Execute exactly the 6 statements from the hash-verified file, one at a time, running the file's guard queries first** (0 for the `ADD` guards) and verifying after each statement — the rehearsed procedure, no improvising.
5. **Maintenance window agreed**, with lock/`ALGORITHM` policy decided (F-10 timing evidence missing → measure or explicitly accept).
6. **Post-migration checklist (§11) executed and recorded**, including row-level preservation proof and `score_method` all-NULL.
7. **Deployment order enforced: migration before backend code restart/deploy** (plan R-1).

**Required before deployment of the migrated system (not migration blockers):**
8. Run and record a fresh DB-free suite on the final tree (E2), then Gate 4 MySQL-dependent suites (E7) — blocked suites must not be reported as passing before they run.
9. Decide and document the `reading_id` unique-constraint mismatch (F-6): add UNIQUE to DB + `schema.sql`, or drop `unique=True` from the model — and correct `PROJECT_AUDIT_REPORT.md` line 88 either way.
10. P2 admin authentication for `PUT /api/config` (F-7, plan §11 R-11).
11. Least-privilege database account for app/migration (F-2).
12. Post-migration bookkeeping: sync `database/schema.sql`, record application date in `PROJECT_STATUS.md`, persist the migration verification report (plan §10), refresh stale plan text (§7/§7.3).

**Advisory (tracked, non-blocking):**
13. Second/offsite copy of the backup; document retention (A8).
14. Decide cleanup of `water_quality_db_staging_phase10` and `water_quality_db_phase10_rollback_test` **with separate approval** — no drops performed or authorized by this review (D8).
15. Live monitoring steps for the window (connection/error-log watch, health endpoint) added to the runbook (F-5).

---

*Prepared as Phase 10 Step 6 Phase F. No SQL was executed, no database was contacted, and no project file other than this report was created or modified. Production, staging, the rollback-test copy, the backup, application code, and the ML artifact were not modified.*
