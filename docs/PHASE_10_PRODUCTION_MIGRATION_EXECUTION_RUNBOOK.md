# Phase 10 — Production Migration Execution Runbook

> **Status:** PREPARATION DOCUMENT ONLY — **production migration is NOT APPROVED and has NOT been executed.**
> **Authoritative readiness basis:** `docs/PHASE_10_FINAL_MIGRATION_READINESS_REVIEW.md` (Phase F: **READY — conditional**).
> **Migration source of truth:** `database/migrations/phase9_scope_reconciliation.sql`
> — 337 lines, 19,627 bytes, **SHA-256 `994B945D6E8621161F33148D362B255100953C95364C2EE7B90C1EEB47435650`**.
> **This runbook does not authorize execution.** The READY recommendation is not migration approval; every statement execution additionally requires the separate per-statement approvals defined in §3 and §7.
> **Created:** 2026-10-31 (documentation-only task; no database contact, no SQL executed while authoring).

---

## 1. Executive summary and current authorization status

**What will happen (when approved):** six guarded `ALTER TABLE` statements from the hash-verified migration file will be applied to the production database `water_quality_db`, one at a time, each preceded by its guard/pre-flight check and followed by mandatory verification, inside an agreed maintenance window, with all database writes quiesced before the fresh verified backup and kept paused until acceptance. Historical rows are never updated, deleted, or backfilled; only column/index metadata changes.

**Current status:**

| Item | Status |
|---|---|
| Phase 10 backend implementation | COMPLETED (Workstream A, Steps 1–10) |
| DB-free regression verification | 171 passed / 0 failed (previous recorded run) |
| Live MySQL schema verification | COMPLETED (`VERIFY_OK`) |
| Backup + staging restore | COMPLETED (Phase B / Phase C) |
| Six-statement staging rehearsal | PASSED (Phase D, per-statement, row-level proof) |
| Seven-statement isolated rollback rehearsal | PASSED (Phase E, `STEP5_VERIFY_OK` 30/30) |
| Phase F final readiness review | **READY — conditional** (13 conditions, §13 of that report) |
| **Production migration** | **NOT APPROVED — BLOCKED** |
| Phase 11 | NOT STARTED — BLOCKED |

**Authorization boundaries:** this document prepares the procedure only. No SQL may be run against production, staging, or the rollback-test copy on the strength of this document. Execution begins only after the approvals in §3 are recorded in §14.

---

## 2. Migration scope and the exact six ALTER statements

**In scope (file order — statements MUST be executed in this order):**

| # | File lines | Section | Purpose |
|---|---|---|---|
| 1 | 105–109 | §1 | `water_readings`: `ph`/`temperature` → NULL + widen `source` enum (one combined statement) |
| 2 | 120–124 | §2 | `system_config`: four pH/temperature thresholds → NULL (values preserved) |
| 3 | 134–136 | §3 | `devices`: widen `source` enum |
| 4 | 169–172 | §4 | `predictions`: add `score_method` (guarded; R-3 REQUIRED) |
| 5 | 205–209 | §4B | `system_config`: add `status_good_min`/`status_poor_max` (guarded; R-2 = B1) |
| 6 | 228–229 | §4C | `predictions`: add `idx_score_method` (guarded; model parity) |

**Verbatim statements (exactly as they appear in the file — do not paraphrase, reformat, reorder, or substitute):**

```sql
-- Statement 1 (lines 105-109)
ALTER TABLE water_readings
    MODIFY COLUMN ph FLOAT NULL COMMENT 'Legacy sensor. NULL = not measured (no pH sensor in final hardware scope).',
    MODIFY COLUMN temperature FLOAT NULL COMMENT 'Legacy sensor. NULL = not measured (no temperature sensor in final hardware scope).',
    MODIFY COLUMN source ENUM('SIMULATION', 'ESP32', 'ESP8266') NOT NULL DEFAULT 'SIMULATION'
        COMMENT 'Telemetry source. ESP32 retained for historical rows only; ESP8266 is the final hardware.';

-- Statement 2 (lines 120-124)
ALTER TABLE system_config
    MODIFY COLUMN ph_min FLOAT NULL COMMENT 'Legacy threshold. NULL = inactive (no pH sensor).',
    MODIFY COLUMN ph_max FLOAT NULL COMMENT 'Legacy threshold. NULL = inactive (no pH sensor).',
    MODIFY COLUMN temperature_min FLOAT NULL COMMENT 'Legacy threshold. NULL = inactive (no temperature sensor).',
    MODIFY COLUMN temperature_max FLOAT NULL COMMENT 'Legacy threshold. NULL = inactive (no temperature sensor).';

-- Statement 3 (lines 134-136)
ALTER TABLE devices
    MODIFY COLUMN source ENUM('SIMULATION', 'ESP32', 'ESP8266') NOT NULL DEFAULT 'SIMULATION'
    COMMENT 'Telemetry source. ESP32 retained for historical rows only; ESP8266 is the final hardware.';

-- Statement 4 (lines 169-172)
ALTER TABLE predictions
    ADD COLUMN score_method ENUM('FOUR_PARAM_LEGACY', 'TWO_PARAM_SCREENING') NULL DEFAULT NULL
    COMMENT 'NULL = legacy four-parameter score (pre-Phase-10). Two-parameter rows are tagged TWO_PARAM_SCREENING.'
    AFTER quality_score;

-- Statement 5 (lines 205-209)
ALTER TABLE system_config
    ADD COLUMN status_good_min FLOAT NOT NULL DEFAULT 70.0
        COMMENT 'Screening band: GOOD when score >= status_good_min (Phase 10 decision R-2 = B1).',
    ADD COLUMN status_poor_max FLOAT NOT NULL DEFAULT 40.0
        COMMENT 'Screening band: POOR when score < status_poor_max (Phase 10 decision R-2 = B1).';

-- Statement 6 (lines 228-229)
ALTER TABLE predictions
    ADD INDEX idx_score_method (score_method);
```

**File integrity rule:** before the window opens, recompute the file hash and compare to the header value of this runbook. Any mismatch = **STOP** (§13). The migration file must never be edited to "fix" a failure mid-window; if the file changes, Phase F readiness no longer applies and the review must be repeated.

**Explicitly out of scope:** no `UPDATE`, `DELETE`, `INSERT`, `DROP`, or column/index/constraint removal; no change to `predictions.prediction`/`confidence`/`quality_score` values; no ML artifact touched; no schema.sql edit during the window (sync happens after, §14); no enum narrowing (widening only — narrowing would destroy `ESP32` rows).

---

## 3. Pre-migration approval requirements

All of the following must be recorded in §14 **before** the first statement runs:

1. **Gate 3 production-migration approval** — separate, explicit, written. Neither prior phase approvals nor this runbook's existence constitute approval.
2. **Fresh-backup approval** — the operator confirms that **all application, simulator, and other database writes were stopped before the dump was taken** (§4 step 0 / §6 W5), that the new dump passed every integrity check in §4, and that its SHA-256 is recorded.
3. **Drift-check approval** — the §5 checklist completed with zero unexpected differences.
4. **Window approval** — maintenance window agreed with all stakeholders; participants and comms confirmed (`[OPERATOR CONFIRMATION REQUIRED]`).
5. **Per-statement approval** — **each of the six statements is executed individually only after a separate, explicit approval for that statement**, granted only after the previous statement's verification (§8) passed and was recorded. Approval for statement *N* never implies approval for statement *N+1*.
6. **Stop-condition acknowledgement** — every participant acknowledges the stop conditions in §13 and agrees any one of them halts the window immediately.
7. **Deployment-sequence acknowledgement** — migration completes and passes §8/§9 verification *before* any backend deploy/restart (§10); the backend stays write-paused through deployment, and §11 Part A sign-off (which includes the read-only smoke) follows the restart.

---

## 4. Production backup procedure and integrity verification

**Rule: a FRESH verified backup — taken only AFTER write quiescence — is mandatory immediately before execution.** The existing Phase B dump (`database/backups/water_quality_db_pre_phase10_20261031_083234.sql`, 113,699 B, SHA-256 `188379095AAA28D76FC25D6D84D94165B38E152A7393DE5D3E8FCB014615C355`) is pre-rehearsal evidence only; it must not be reused as the execution-day backup, and it must never be overwritten or deleted.

**Procedure:**

0. **Write quiesce BEFORE the backup (mandatory first step):** stop **all** application, simulator, and other database writes to `water_quality_db` and confirm the database is write-idle **before** `mysqldump` starts (§6 W5; `[OPERATOR CONFIRMATION REQUIRED]` for the stop method). Writes stay paused from this point through migration, post-migration verification, backend deployment, and smoke testing; they are re-enabled **only after acceptance** (§6 W11, §11).
1. Target: database `water_quality_db` (production), all four tables — captured while quiesced (step 0), so the dump is a stable point-in-time image.
2. Tool: the MySQL 8.0.46 `mysqldump.exe` at `C:\Program Files\MySQL\MySQL Server 8.0\bin\` (not on PATH). Use the **same audited flag set already used and proven in Phases B/E** (persisted in the Phase E verifier tooling): `--single-transaction --quick --skip-lock-tables --routines --events --triggers --hex-blob --default-character-set=utf8mb4 --set-gtid-purged=OFF`, output to a **new dated file** in `D:\EVS\database\backups\` following the established naming pattern `water_quality_db_pre_phase10_<YYYYMMDD_HHMMSS>.sql`. Exact command line and filename: `[OPERATOR CONFIRMATION REQUIRED]`.
3. Credentials come only from `backend/.env` (`MYSQL_*` keys), passed to the child process via a process-scoped environment variable; **never printed, never embedded in the file name or command history**.
4. Refuse to overwrite an existing file — pick a new timestamp if a collision occurs.

**Integrity verification (all must pass; any failure = no migration):**

| # | Check | Expected |
|---|---|---|
| B1 | Exit code | 0 |
| B2 | File size | > 0; in line with the ~113 KB scale of the known-good dump |
| B3 | `CREATE TABLE` statements | exactly 4 (`devices`, `predictions`, `system_config`, `water_readings`) |
| B4 | `INSERT INTO` statements | 4 (all four tables carry data) |
| B5 | `CREATE DATABASE` / `USE` lines | 0 (dump must not self-select a target) |
| B6 | Header | `MySQL dump 10.13 Distrib 8.0.46`, `Database: water_quality_db` |
| B7 | SHA-256 | computed and **recorded in §14** |
| B8 | Restore proof (optional but recommended) | trial restore into a scratch schema **only if separately approved**; otherwise rely on the twice-proven restore path from Phases C/E — mark `[OPERATOR CONFIRMATION REQUIRED]` |
| B9 | Retention | keep the dump until post-migration acceptance (§11) is signed off (plan §7.4 item 4) |

---

## 5. Live schema-drift verification procedure

Run **immediately before** the window (read-only). Any unexpected result = **STOP** (§13); do not "reconcile" drift in the window.

1. **Baseline counts (file §0, lines 70–73, verbatim):**

```sql
SELECT COUNT(*) AS devices_total FROM devices;
SELECT COUNT(*) AS readings_total FROM water_readings;
SELECT COUNT(*) AS predictions_total FROM predictions;
SELECT COUNT(*) AS config_rows FROM system_config;
```

Expected: **77 / 503 / 500 / 1**. Any other value = STOP.

2. **Pre-migration column state (file §0, lines 77–86, verbatim)** — expected: `water_readings.ph`/`temperature` `IS_NULLABLE = NO`; `system_config` thresholds `NO`; `devices.source` and `water_readings.source` = `enum('SIMULATION','ESP32')`; `status_good_min`/`status_poor_max`/`score_method` **absent**; `predictions.quality_score` `NO`.

3. **Source distributions (file §0, lines 89–90, verbatim):**

```sql
SELECT source, COUNT(*) FROM devices   GROUP BY source;
SELECT source, COUNT(*) FROM water_readings GROUP BY source;
```

Expected: devices `SIMULATION 75 / ESP32 2` (no `ESP8266`); water_readings `SIMULATION 483 / ESP32 20` (no `ESP8266`).

4. **Full §7.3 inventory (plan `docs/PHASE_10_BACKEND_IMPLEMENTATION_PLAN.md` §7.3)** — complete every listed item read-only: column `DATA_TYPE`/nullability/comments, enum members, row counts + `SIMULATOR-001` seed, `score_method`/band absence, indexes/constraints (`fk_readings_device`, `fk_prediction_reading`, `CHECK (id = 1)`), **drift comparison of live schema vs `database/schema.sql`**, MySQL version (expected 8.0.46) and table sizes (lock/rebuild estimate). Where this needs exact query text, reuse the persisted read-only tooling from Phase 5 (`evs_live_schema_verify.py`, SELECT/SHOW whitelist) — `[OPERATOR CONFIRMATION REQUIRED]` for which tool/script runs it.
5. **Expected pre-migration structure totals (from Phase F verified baseline):** 31 columns (7/8/8/8), 15 index rows, 8 constraints, 2 foreign keys. Deviations = STOP.
6. **Environment facts to confirm:** server 8.0.46; the connecting account (see least-privilege concern §13-F-2 — only `root@localhost` currently has full privileges, 3 accounts locked); `gtid_mode`/`log_bin` values (Phase A printed them but did not persist them — `[OPERATOR CONFIRMATION REQUIRED]`).

---

## 6. Maintenance window and operator preparation

**Why a window is required (file header, lines 43–61):** MySQL DDL causes an **implicit commit** — there is no transactional undo; `ALTER TABLE … MODIFY` may rebuild tables and take metadata/write locks. The script header requires a staging runtime measurement and maintenance window; **staging timings were never recorded (Phase F finding F-10 / NOT VERIFIED)** — measure them or explicitly accept the lock exposure before the window opens (`[OPERATOR CONFIRMATION REQUIRED]`).

**Window prerequisites:**

| # | Item | Detail |
|---|---|---|
| W1 | Window schedule | Date/time/duration + rollback decision deadline: `[OPERATOR CONFIRMATION REQUIRED]` |
| W2 | Participants | Operator (DBA role), approver(s) for per-statement approvals, backend owner on standby: `[OPERATOR CONFIRMATION REQUIRED]` |
| W3 | Comms | Channel for pause/stop calls: `[OPERATOR CONFIRMATION REQUIRED]` |
| W4 | Client access | `mysql.exe`/`mysqldump.exe` at `C:\Program Files\MySQL\MySQL Server 8.0\bin\`; credentials via `backend/.env` only, process-scoped, never printed |
| W5 | Write quiesce (**before the backup**) | **All** application, simulator, and other database writes to `water_quality_db` stopped and confirmed write-idle **BEFORE the fresh backup is taken** (§4 step 0) — not merely before statement 1. Writes remain paused through migration, post-migration verification, backend deployment, and smoke testing (`[OPERATOR CONFIRMATION REQUIRED]` — process/service stop method) |
| W6 | Baseline capture | §5 checks complete and recorded; counts 77/503/500/1 (performed while writes are paused) |
| W7 | Fresh backup (after W5) | §4 complete **with quiesce (W5) in place first**, SHA-256 recorded in §14 |
| W8 | File hash | Migration SHA-256 re-verified = header value |
| W9 | Algorithm/lock policy | Decide whether to attempt `ALGORITHM=INPLACE, LOCK=NONE` (script header: MySQL must refuse rather than silently lock; remove the clause if rejected; **do not assume any algorithm without testing**). This changes statement text ⇒ default is **run statements verbatim without the clause** unless the operator explicitly decides otherwise and records it: `[OPERATOR CONFIRMATION REQUIRED]` |
| W10 | Rollback readiness | Restore command + target schema written down (§12); participant authorized to call STOP |
| W11 | Write re-enable (only after acceptance) | Application/simulator/other DB writes are **re-enabled only after** all §11 Part A acceptance criteria pass and sign-off is recorded in §14 (pause scope is defined in W5). The `POST /api/readings` HTTP 201 check runs only **after** this re-enable (§11 Part B) (`[OPERATOR CONFIRMATION REQUIRED]`) |

**MySQL DDL implicit-commit model (mandatory reading for all participants):** each of the six statements commits independently the moment it succeeds; a failure after statement *k* leaves statements *1..k* **permanently applied** with statements *k+1..6* absent. There is no rollback-by-transaction. Recovery options in that state: (a) continue after fixing the cause, or (b) restore the fresh dump (§12). This partial-application state is expected behavior, not corruption — but it must never be attempted without the verified dump present.

---

## 7. Exact statement-by-statement execution sequence

**Global rules for every statement:**

- Execute **one statement at a time**, individually approved (§3 item 5), via a single-statement client invocation (proven method from Phases D/E: raw-bytes stdin to `mysql.exe`, schema passed as the target database argument, `MYSQL_PWD` process-scoped, password redaction on all captured output).
- Before the first statement: `SELECT DATABASE();` must return `water_quality_db` (the Phase E discipline asserted the target before *every* statement; production execution must do the same).
- Run the applicable guard **before** statements 4, 4B, 6 (guards are part of the file and are quoted below verbatim).
- On exit code ≠ 0, unexpected guard result, or failed verification → **STOP immediately** (§13). **Any guard result other than the expected value — including an already-present column, index, or band columns (guard = 1 or 2) — triggers STOP and manual reconciliation. Never automatically skip a statement, never automatically re-run a statement, never skip a guard, never edit the file to work around an error, never run a statement twice blindly.**

**Sequence:**

| Step | Statement (§2) | Pre-check / guard (verbatim from file) | Expected guard result | Post-verification (§8) | Approval |
|---|---|---|---|---|---|
| 1 | #1 `water_readings` (105–109) | §5 checks above (baseline captured) | counts 77/503/500/1; `ph`/`temperature` `NO` | V1 | `[OPERATOR CONFIRMATION REQUIRED]` per statement |
| 2 | #2 `system_config` (120–124) | verify statement 1 verified OK | — | V2 | " |
| 3 | #3 `devices` (134–136) | verify statement 2 verified OK | — | V3 | " |
| 4 | #4 `predictions` ADD `score_method` (169–172) | file guard, lines 163–167: `SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = 'water_quality_db' AND TABLE_NAME = 'predictions' AND COLUMN_NAME = 'score_method';` (**0 = run; 1 = already present → STOP + manual reconciliation — never auto-skip, never auto-re-run; anything else = STOP**) | **0** | V4 | " |
| 5 | #5 `system_config` bands (205–209) | file guard, lines 197–200: `SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = 'water_quality_db' AND TABLE_NAME = 'system_config' AND COLUMN_NAME IN ('status_good_min', 'status_poor_max');` (**0 = run; 2 = both already present → STOP + manual reconciliation; 1 = partial state → do NOT run the combined statement → STOP + manual reconciliation; anything else = STOP — never auto-skip, never auto-re-run**) | **0** | V5 | " |
| 6 | #6 `predictions` index (228–229) | file guard, lines 222–225: `SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = 'water_quality_db' AND TABLE_NAME = 'predictions' AND INDEX_NAME = 'idx_score_method';` (**0 = run; 1 = already present → STOP + manual reconciliation — never auto-skip, never auto-re-run; anything else = STOP**) | **0** | V6 | " |

**Guard rule (applies to every guard in this runbook):** an expected result of 0 authorizes execution of that statement after per-statement approval. **Every other result — including "already applied" / "already present" — is an unexpected guard result: STOP, record the raw output, and perform manual reconciliation (§13 S4) before anything else. A statement is never skipped automatically, and never re-run automatically.**

After step 6: run the full acceptance set (§9, §11).

---

## 8. Verification query requirements after each statement

All queries below already exist in the migration file (Section 0 / Section 5) or plan §7.6 — no new SQL is introduced. Each verification runs read-only and its output is recorded in §14 before the next approval is granted.

**After every statement (file §5, lines 237–240, verbatim):**

```sql
SELECT COUNT(*) AS devices_total_after FROM devices;
SELECT COUNT(*) AS readings_total_after FROM water_readings;
SELECT COUNT(*) AS predictions_total_after FROM predictions;
SELECT COUNT(*) AS config_rows_after FROM system_config;
```

Expected after **each** statement: **77 / 503 / 500 / 1**. Any deviation = STOP.

**V1 (after statement 1):** re-run file §0 column query (lines 77–86) → `water_readings.ph` and `temperature` now `YES`; `water_readings.source` now `enum('SIMULATION','ESP32','ESP8266')`; also file §5 line 254 `SHOW COLUMNS FROM water_readings WHERE Field IN ('ph','temperature');` and line 253 `SHOW COLUMNS FROM water_readings LIKE 'source';` — plus file §5 preservation query (lines 244–249, verbatim):

```sql
SELECT
    COUNT(*) AS readings_total,
    COUNT(ph) AS ph_values_preserved,
    COUNT(temperature) AS temperature_values_preserved,
    SUM(CASE WHEN source = 'ESP8266' THEN 1 ELSE 0 END) AS esp8266_rows
FROM water_readings;
```

Expected: `503 / 503 / 503 / 0` (every historical value preserved; **no NULL rows yet** — important: production has no NULL ph/temperature, which keeps rollback guards alive).

**V2 (after statement 2):** file §0 column query → four `system_config` thresholds now `YES`, `COLUMN_DEFAULT` unchanged (6.5/8.5/10/35); config row values still `6.5/8.5/500/5/10/35` (plan §7.6: existing config values unchanged).

**V3 (after statement 3):** file §5 line 252 `SHOW COLUMNS FROM devices LIKE 'source';` → 3-member enum; devices distribution still 75/2/0 (file §0 lines 89–90).

**V4 (after statement 4):** file §5 lines 264–269 (verbatim) → exactly 1 row: `ENUM('FOUR_PARAM_LEGACY','TWO_PARAM_SCREENING') / YES / NULL`; plus the file's own rollback-side guard query, reused here as a read-only preservation check (line 293): `SELECT COUNT(*) FROM predictions WHERE score_method IS NOT NULL;` → **0** (proves no backfill; historical rows untouched — plan §7.6 "historical predictions.score_method all NULL").

**V5 (after statement 5):** file §5 lines 257–261 (verbatim) → exactly 2 rows: `FLOAT / NO / 70.0` and `FLOAT / NO / 40.0`; plus file §5 line 278 `SELECT status_good_min, status_poor_max FROM system_config WHERE id = 1;` → `70.0 / 40.0`; plus config row thresholds still `6.5/8.5/500/5/10/35`.

**V6 (after statement 6):** file §5 lines 271–276 (verbatim) → exactly one row: `idx_score_method / non-unique / column score_method`.

**Full-set re-checks after step 6:** file §0 queries again (columns, distributions) and the plan §7.6 acceptance list (§11 below).

---

## 9. Historical data preservation checks

Run after step 6 and compare against the §5 baseline; **all must match exactly**:

1. **Counts:** 77 / 503 / 500 / 1 (file §5, lines 237–240).
2. **Sensor values:** `503 / 503 / 503` non-NULL ph/temperature, `esp8266_rows = 0` (file §5, lines 244–249).
3. **No backfill:** `SELECT COUNT(*) FROM predictions WHERE score_method IS NOT NULL;` → **0** (file line 293).
4. **Distributions unchanged:** devices 75 SIMULATION / 2 ESP32 / 0 ESP8266; water_readings 483 / 20 / 0 (file §0, lines 89–90).
5. **Config row `id=1`:** `6.5 / 8.5 / 500 / 5 / 10 / 35` with bands at `70.0 / 40.0` (file §5, lines 278–279).
6. **Deep preservation proof (recommended, requires separately approved read-only tooling):** row-level comparison of all four tables' `INSERT` data against the **fresh §4 dump** using the persisted Phase D/E method (`evs_rowlevel_proof.py` pattern: both sides serialized by the same mysqldump binary, in-memory, no files written beyond the dump). Expectation set proven in rehearsal: devices and water_readings byte-identical; predictions identical excluding the `score_method` column (all NULL); system_config identical excluding the two band values (70/40). Whether this runs inside the window: `[OPERATOR CONFIRMATION REQUIRED]`.
7. **Checksum expectations:** after migration, `devices` checksum unchanged; `water_readings`/`predictions`/`system_config` checksums **change by layout only** (null-flag / new columns) — proven value-identical in Phase D. Do not treat those three changes as data drift (Phase F, C6).
8. **What must never appear in any verification output:** row-count changes, non-zero `esp8266_rows`, non-NULL `score_method`, changed threshold values, new NULLs in ph/temperature.

---

## 10. Backend deployment and restart sequence

**Ordering rule (plan R-1):** migration first, then backend deploy/restart (or same window with migration strictly before restart). Backend code that selects `score_method` or the band columns fails with MySQL 1054 against the pre-migration schema; conversely the migrated schema is backward compatible with the current code (nullable columns accept non-NULL values).

1. Step 6 of §7 completes + §8/§9 verification passes — **then** the backend deploy/restart is permitted. (§11 Part A acceptance, which includes the read-only smoke, necessarily follows this restart; its sign-off then gates write re-enable per §6 W11.)
2. Confirm the deployed tree is the Phase 10 implementation (Workstream A complete; `backend/.env` unchanged; `MODEL_PATH`/`METRICS_PATH` unchanged).
3. Restart mechanism (service manager / process command): `[OPERATOR CONFIRMATION REQUIRED]`. **All application, simulator, and other database writes remain PAUSED** (§6 W5) through deployment and smoke testing — write traffic is not re-enabled here; it is re-enabled only after acceptance (§6 W11, §11).
4. Post-start **read-only smoke** (§11 Part A) **with writes still paused**: health endpoint, `GET /api/config`, and `GET /history` only. **`POST /api/readings` MUST NOT be called while writes are paused** — its HTTP 201 check is a post-write-enable verification step (§11 Part B), executed only after acceptance sign-off and explicit write re-enable.
5. **ML artifact protection:** before and after deploy, verify `ml/models/water_potability_model.joblib` SHA-256 = `F446308C985584261D44A51428CC4AD68930DEAF9F5044A599555CC9B1DAACC6`. Any change = STOP and escalate (no retraining/ML change is part of this migration; `MODEL_PATH`/`METRICS_PATH` must not be rewritten).
6. Deployment concerns to track alongside the restart (they do **not** block migration but must be recorded for deployment sign-off, Phase F §9): **(a)** outstanding `Prediction.reading_id` model↔schema uniqueness mismatch (`unique=True` in the model, no UNIQUE in DB — decide add-UNIQUE vs drop-`unique=True` in a separately approved change); **(b)** P2 admin authentication — `PUT /api/config` remains unauthenticated; **(c)** least-privilege database account — app/migration currently rely on `root@localhost`.

---

## 11. Post-migration testing and acceptance criteria

### Part A — Pre-write-enable acceptance criteria (all required for sign-off; all performed while writes are PAUSED)

1. All 6 statements exit 0, each with its guard result and verification recorded (§7, §8).
2. §9 preservation checks all exact-match.
3. Structure matches the rehearsed post-state: 33 columns (31 + `score_method` + 2 bands), `idx_score_method` present, 8 constraints, 2 FKs intact, enums 3-member, thresholds/things nullable as specified, bands `FLOAT NOT NULL` defaults 70/40.
4. **Read-only backend smoke after restart (§10 step 4), with writes still paused — READ-ONLY endpoints only:** health endpoint; `GET /api/config` returns `status_good_min=70.0`/`status_poor_max=40.0` with legacy values intact; `GET /history` returns historical rows with `score_method: null` and unchanged `safety_status`/`warning_message` (P1 separation). `POST /api/readings` is **not** part of Part A (§10 step 4 governs its prohibition while paused); it is verified only in Part B below.
5. **Test results reported SEPARATELY, never merged:**
   - **DB-free suite** — previous recorded run: **171 passed / 0 failed**. Re-run on the final tree during the window and report as its own result line: `[OPERATOR CONFIRMATION REQUIRED]` (this runbook does not claim a fresh result).
   - **MySQL-dependent suites** — `test_readings_integration`, `test_simulator_integration`, `test_phase5_ml_api`, `test_phase3_api` (Gate 4): **NOT YET RUN**; must be reported as a separate block with honest results, including any failures. They are currently BLOCKED (pre-migration), so no pass may be claimed for them beforehand.
6. ML artifact hash unchanged (§10 step 5).
7. **Write quiesce held throughout:** application/simulator/other DB writes were paused before the backup (§4 step 0) and stayed paused through migration, post-migration verification, backend deployment, and smoke testing (§6 W5).
8. **Write re-enable:** application/simulator/other DB writes are re-enabled **only after** all Part A acceptance criteria above pass and sign-off is recorded (§6 W11, §14). Re-enable marks the boundary between Part A and Part B.
9. Bookkeeping: record application date/versions in `PROJECT_STATUS.md`; sync `database/schema.sql`; persist the migration verification report (plan §10 / Phase F condition 12) — after acceptance, in follow-up, not during the window.

**Historical row-count acceptance criteria are UNCHANGED:** the 77 / 503 / 500 / 1 counts (§5, §8, §9, §13 S6) are asserted against the pre-write-enable Part A state, where no writes occurred. These criteria are not relaxed, re-baselined, or waived anywhere in this runbook.

### Part B — Post-write-enable verification (AFTER Part A sign-off and explicit write re-enable)

Executed only after criterion 8 above re-enables writes (§6 W11; recorded in §14):

1. Confirm writes are explicitly re-enabled — record time + owner (`[OPERATOR CONFIRMATION REQUIRED]`).
2. **`POST /api/readings` with a legacy 6-field payload → HTTP 201.**
3. Re-check `GET /api/config` and `GET /history` still behave as in Part A after the write.
4. **Row counts:** the acceptance counts (77 / 503 / 500 / 1) were already signed off in Part A against the write-paused state. Post-enable counts will reflect the newly created record(s) and are recorded as **post-acceptance observations**, not as a new acceptance baseline. **Do not delete test records to restore counts** — deletion would mutate production data and violate the preservation rule (§9); no cleanup of these records is authorized by this runbook.
5. If the POST fails (non-201): STOP, record the response, and investigate as a deployment defect (§13). A Part B failure does not alter the already-signed-off Part A results, but it must be recorded in §14 before overall sign-off.

---

## 12. Recovery and restoration procedure

**Primary recovery method = restore of the fresh §4 dump** (script line 332, design §7, plan §7.5, Phase F D4). DDL is non-transactional; a verified dump restore is the only complete undo.

**Restore procedure (as proven twice in Phases C and E):**

1. Stop further migration attempts; assess state (which statements applied — check via §5-style read-only queries).
2. Restore into `water_quality_db` **only after explicit operator approval** (`[OPERATOR CONFIRMATION REQUIRED]` for who approves, and for the exact command line). Proven mechanics: MySQL 8.0.46 `mysql.exe` at `C:\Program Files\MySQL\MySQL Server 8.0\bin\`, dump fed as **raw bytes to stdin**, **target schema passed as the database argument** (the dump contains no `USE`/`CREATE DATABASE` and contains `DROP TABLE IF EXISTS` for the four tables — it will replace those tables in whichever schema is named; naming the wrong schema is a destructive operator error), credentials process-scoped via `MYSQL_PWD`, never printed.
3. Verify the restore: exit 0, then §5 baseline queries → 77/503/500/1, pre-migration schema, checksums/row-level as in §9.
4. Record everything in §14; re-plan before any new attempt (the Phase F READY verdict applies to the original file/state and must be re-confirmed after any restore).

**Secondary method — guarded reverse ALTERs (Section 6 of the migration file, commented, 7 statements):** rehearsed successfully in Phase E (all guards 0, `STEP5_VERIFY_OK` 30/30). Constraints that still apply:

- Each reverse statement requires its preceding guard to return 0; guards are never bypassed.
- **Reverse ALTER rollback statements may become UNAVAILABLE after ESP8266 records or NULL sensor readings are introduced:** once any row uses `source='ESP8266'`, enum-narrowing guards (file lines 312–313) correctly refuse; once any `ph`/`temperature` is NULL (real ESP8266 telemetry), the NOT NULL restoration guard (line 327) correctly refuses; a non-NULL `score_method` (line 293) or customized bands (lines 302–303) likewise block their reversals. **In those states, dump restore is the only recovery** — narrowing an enum or forcing NOT NULL over NULLs would destroy data and violate the preservation rule.
- Therefore: **if the migrated system has already accepted ESP8266/NULL-sensor traffic, do not attempt reverse ALTERs — restore the dump.**

---

## 13. Failure handling and stop conditions

**IMMEDIATE STOP conditions (halt the window; do not proceed to the next statement):**

| ID | Trigger | Response |
|---|---|---|
| S1 | Migration file SHA-256 ≠ header value, or file missing/truncated | STOP; re-run Phase F prerequisites |
| S2 | Fresh §4 backup failed any integrity check (exit ≠ 0, wrong tables, no INSERTs, hash not recorded) | STOP before statement 1 |
| S3 | Any §5 drift-check expectation mismatch (schema, enums, counts ≠ 77/503/500/1, missing seed, unexpected index/constraint) | STOP before statement 1 |
| S4 | **Any** guard result other than the expected 0 (§7 table) — including guard = 1 or 2 "already applied / already present" (column, index, or band columns already exist) and guard = 1 "partial state" on §4B | STOP; record raw output; **manual reconciliation only — never automatically skip a statement, never automatically re-run a statement** |
| S5 | Any statement exit code ≠ 0 (e.g., lock timeout, algorithm rejection) | STOP; assess applied set (implicit commits); choose continue-vs-restore (§12) |
| S6 | Any §8 verification mismatch: row counts ≠ 77/503/500/1; `esp8266_rows ≠ 0`; `score_method IS NOT NULL` count ≠ 0; config thresholds ≠ 6.5/8.5/500/5/10/35; bands ≠ 70/40; unexpected NULL in ph/temperature; missing/extra columns or index rows | STOP; investigate; consider §12 restore |
| S7 | Row-count or value differences found by §9 deep comparison (if run) | STOP; treat as data-mutation incident; restore dump |
| S8 | Connection lost / client crash mid-window | STOP; reconnect read-only only; determine which statements committed (implicit-commit model §6); never blind-retry |
| S9 | Unexpected schema object present/absent vs baseline totals (31 cols / 15 index rows / 8 constraints / 2 FKs pre-migration) | STOP before statement 1 |
| S10 | ML artifact hash differs from `F446308C…DAACC6` at any verification point | STOP and escalate (out-of-band change) |
| S11 | Any request to execute statements not in the file, in different order, or with edited text | STOP; only the hash-verified file, in order |
| S12 | Approval for the next statement not obtained (§3 item 5) | HOLD — do not execute |

**After a STOP:** record exact time, statement reached, outputs, and applied-set assessment in §14; convene approver(s); decide continue vs. dump restore (§12); readiness verdict must be re-confirmed before resuming.

---

## 14. Final sign-off checklist

**Pre-window (must all be complete before statement 1):**

- [ ] Gate 3 separate, explicit production-migration approval recorded — approver, date/time: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] Migration file SHA-256 re-verified = `994B945D6E8621161F33148D362B255100953C95364C2EE7B90C1EEB47435650`
- [ ] **Write quiesce confirmed BEFORE backup** — all application, simulator, and other DB writes stopped and write-idle (§4 step 0, §6 W5); method: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] Fresh backup created **while writes are quiesced** — filename, size, exit code, 4 CREATE/4 INSERT/no USE, SHA-256: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] Schema-drift check (§5) completed — 0 unexpected differences; counts 77/503/500/1 recorded
- [ ] Maintenance window agreed; participants/comms recorded (§6 W1–W3)
- [ ] Algorithm/lock policy decided (§6 W9); restore command + target schema written down (§12)
- [ ] Stop conditions briefed to all participants (§13), including: unexpected guard result (incl. already-present column/index) = STOP + manual reconciliation, never auto-skip/auto-re-run (§7, §13 S4)
- [ ] Old backup (`water_quality_db_pre_phase10_20261031_083234.sql`) confirmed intact and NOT overwritten

**Per-statement (repeat 6×, in order):**

- [ ] Statement 1 — approval recorded; exit 0; V1 verification recorded — approver: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] Statement 2 — approval recorded; exit 0; V2 recorded — approver: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] Statement 3 — approval recorded; exit 0; V3 recorded — approver: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] Statement 4 — guard = 0 recorded; approval; exit 0; V4 (incl. `score_method` all-NULL = 0) recorded — approver: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] Statement 5 — guard = 0 recorded; approval; exit 0; V5 recorded — approver: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] Statement 6 — guard = 0 recorded; approval; exit 0; V6 recorded — approver: `[OPERATOR CONFIRMATION REQUIRED]`

*(If any guard ≠ 0: STOP + manual reconciliation — never auto-skip, never auto-re-run (§7, §13 S4).)*

**Post-migration / pre-deploy:**

- [ ] §9 historical preservation checks all exact-match (recorded)
- [ ] Structure = rehearsed post-state (33 cols, index, constraints, FKs)
- [ ] ML artifact SHA-256 = `F446308C985584261D44A51428CC4AD68930DEAF9F5044A599555CC9B1DAACC6` before and after
- [ ] Backend deployed/restarted **after** migration completion (§10), **with all DB writes still paused**; restart method: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] **Read-only smoke passed (§11 Part A: health endpoint, `GET /api/config`, `GET /history`) with writes still paused** — **no `POST /api/readings` at this stage**
- [ ] DB-free test result reported separately — previous: 171/0; window run: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] MySQL-dependent (Gate 4) test result reported separately: `[OPERATOR CONFIRMATION REQUIRED]` — **no pre-claimed passes**
- [ ] **All Part A acceptance criteria (§11) signed off — only then: application/simulator/other DB writes re-enabled** (§6 W11); re-enable time + owner: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] **Post-write-enable verification (§11 Part B) completed AFTER re-enable:** `POST /api/readings` legacy 6-field payload → 201 recorded; `GET /api/config` + `GET /history` re-checked; post counts recorded as observations — **test record(s) retained, NOT deleted to restore counts**: `[OPERATOR CONFIRMATION REQUIRED]`
- [ ] Post-migration bookkeeping scheduled: `schema.sql` sync, `PROJECT_STATUS.md` entry, persisted verification report
- [ ] Deployment concerns logged for follow-up: `reading_id` uniqueness mismatch decision; P2 admin authentication; least-privilege DB account
- [ ] Cleanup decision for `water_quality_db_staging_phase10` / `water_quality_db_phase10_rollback_test` deferred (separate approval; no drops authorized)

**Sign-off block:**

| Role | Name | Decision | Date/time |
|---|---|---|---|
| Approver (Gate 3) | `[OPERATOR CONFIRMATION REQUIRED]` | APPROVED / NOT APPROVED | `[OPERATOR CONFIRMATION REQUIRED]` |
| Operator (DBA) | `[OPERATOR CONFIRMATION REQUIRED]` | READY / NOT READY | `[OPERATOR CONFIRMATION REQUIRED]` |
| Backend owner | `[OPERATOR CONFIRMATION REQUIRED]` | ACK (deploy order) | `[OPERATOR CONFIRMATION REQUIRED]` |

---

*End of runbook. Documentation-only artifact: no SQL was executed and no database (production, staging, or rollback-test) was contacted during its creation; the migration file, backup, application code, and ML artifact were not modified; production migration remains NOT APPROVED and Phase 11 remains NOT STARTED.*
