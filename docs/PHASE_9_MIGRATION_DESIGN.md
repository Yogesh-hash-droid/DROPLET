# Phase 9 — Database Migration Design

> **Status:** PLANNING / DRAFT — **no migration has been executed.**
> **Draft script:** `database/migrations/phase9_scope_reconciliation.sql` (created for review only)
> **Companion documents:** `docs/PHASE_9_QUALITY_ASSESSMENT_DESIGN.md`, `docs/api.md`, `docs/PHASE_9_IMPLEMENTATION_ROADMAP.md`

---

## 1. Goals

1. Make legacy **pH** and **temperature** reading columns nullable.
2. Preserve **all** existing historical records and their values (no UPDATE, no DELETE, no DROP).
3. Make legacy pH/temperature **configuration** fields optional and backward-compatible.
4. Add support for the **`ESP8266`** device source value.
5. Preserve **`SIMULATION`** as a separate source (and keep the legacy `ESP32` value so old rows stay valid).
6. Keep every existing database record unchanged.
7. Distinguish legacy four-parameter scores from the new two-parameter scores (§6).

---

## 2. Current Schema (as-is, `database/schema.sql`)

| Table | Column | Current definition | Problem for final scope |
|---|---|---|---|
| `water_readings` | `ph` | `FLOAT NOT NULL` | Hardware has no pH sensor → cannot store an honest reading |
| `water_readings` | `temperature` | `FLOAT NOT NULL` | Hardware has no temperature sensor |
| `water_readings` | `source` | `ENUM('SIMULATION','ESP32') NOT NULL DEFAULT 'SIMULATION'` | No `ESP8266` value; ESP32 out of scope |
| `devices` | `source` | `ENUM('SIMULATION','ESP32') NOT NULL DEFAULT 'SIMULATION'` | Same |
| `system_config` | `ph_min`, `ph_max` | `FLOAT NOT NULL DEFAULT 6.5 / 8.5` | Thresholds for a sensor that does not exist |
| `system_config` | `temperature_min`, `temperature_max` | `FLOAT NOT NULL DEFAULT 10.0 / 35.0` | Same |
| `predictions` | `prediction`, `confidence` | already `NULL` | **No change needed** — NULL already = "no ML verdict" |
| `predictions` | `quality_score` | `FLOAT NOT NULL` | Keeps NOT NULL; the *method* behind it must become distinguishable (§6) |

---

## 3. Proposed Schema Changes

All changes are **metadata-only** (nullable flags, enum widening, one new nullable column).

```sql
-- 1) legacy reading sensors become nullable AND source is widened, in ONE statement
--    (Phase 9 correction: combined so `water_readings` is only rebuilt once)
ALTER TABLE water_readings
    MODIFY COLUMN ph FLOAT NULL,
    MODIFY COLUMN temperature FLOAT NULL,
    MODIFY COLUMN source ENUM('SIMULATION','ESP32','ESP8266') NOT NULL DEFAULT 'SIMULATION';

-- 2) legacy config thresholds become nullable (values preserved)
ALTER TABLE system_config
    MODIFY COLUMN ph_min FLOAT NULL,
    MODIFY COLUMN ph_max FLOAT NULL,
    MODIFY COLUMN temperature_min FLOAT NULL,
    MODIFY COLUMN temperature_max FLOAT NULL;

-- 3) widen (never narrow) the devices source enum
ALTER TABLE devices
    MODIFY COLUMN source ENUM('SIMULATION','ESP32','ESP8266') NOT NULL DEFAULT 'SIMULATION';

-- 4) score-method marker so old vs new scores are never confused
--    (REQUIRED as of the Phase 10 plan, decision R-3; guard first:
--     SELECT COUNT(*) FROM information_schema.COLUMNS WHERE ... COLUMN_NAME='score_method';)
ALTER TABLE predictions
    ADD COLUMN score_method ENUM('FOUR_PARAM_LEGACY','TWO_PARAM_SCREENING') NULL DEFAULT NULL
    AFTER quality_score;

-- 5) (Phase 10 Step 4 amendment, 2026-10-31 - added to the same draft file, still
--    NOT executed) B1 screening-band columns (decision R-2 = B1), with an
--    information_schema.COLUMNS re-run guard:
ALTER TABLE system_config
    ADD COLUMN status_good_min FLOAT NOT NULL DEFAULT 70.0,
    ADD COLUMN status_poor_max FLOAT NOT NULL DEFAULT 40.0;

-- 6) (Phase 10 Step 4 amendment) score_method index for SQLAlchemy model parity
--    (Prediction.score_method declares index=True), with an
--    information_schema.STATISTICS re-run guard:
ALTER TABLE predictions
    ADD INDEX idx_score_method (score_method);
```

> **Phase 10 Step 4 update (2026-10-31):** statements 5 and 6 were appended to the draft as Sections 4B/4C, and statement 4 was promoted from OPTIONAL to REQUIRED (decision R-3). The draft now issues **6** executable DDL statements (see §4 step 5). The script remains DRAFT / UNAPPLIED.

**Explicitly unchanged:** every row's data, `predictions.prediction`, `predictions.confidence`, all indexes, all foreign keys, `devices.device_id` uniqueness, the `single_row CHECK` on `system_config`, and the `SIMULATOR-001` seed.

### Why nullable instead of dropping columns (scope decision 4)

- Historical pH/temperature values (already captured by earlier phases) remain queryable and auditable.
- No data is destroyed → the "do not delete historical values" requirement holds.
- Legacy `SIMULATION` clients that still send 4 fields keep working unchanged (§5).
- Reversibility: rollback simply restores `NOT NULL` (guarded — it only succeeds while no NULL exists).

### SQL draft review corrections (Phase 9 correction round)

The draft `database/migrations/phase9_scope_reconciliation.sql` was reviewed line by line. Two issues were found and corrected **in the draft only** (nothing executed):

1. **Double alteration of `water_readings`** — the first draft issued two separate `ALTER TABLE water_readings` statements (nullable sensors, then enum widening), risking two table rebuilds/lock windows. **Correction:** combined into a single statement (draft §1; §3b now points to it instead of repeating the ALTER).
2. **Missing idempotency guard on `ADD COLUMN score_method`** — MySQL has no `ADD COLUMN IF NOT EXISTS` before 8.0.29, so a re-run would fail. **Correction:** a read-only `information_schema` guard query was added to draft §4 (run it first; skip step 4 when the column already exists).

Additionally documented (not a defect, but a missing caution): `ALTER TABLE … MODIFY` may rebuild tables and take locks on large data sets — the draft header now requires a staging runtime measurement and a maintenance window, and notes the optional `ALGORITHM=INPLACE, LOCK=NONE` clause to make MySQL refuse a locking change instead of applying it silently.

Verified as still correct in the draft: header marks it DRAFT/NOT FOR EXECUTION; no `UPDATE`/`DELETE`/`DROP` anywhere; historical rows untouched; `ESP32` and `SIMULATION` enum members preserved with `ESP8266` added (widening only); pH/temperature made nullable; config thresholds made nullable with values intact; optional `score_method` retained with `NULL = legacy` semantics; rollback guards preserved.

---

## 4. Migration Steps (proposed sequence for a future phase)

1. **Backup:** `mysqldump water_quality_db > backup_before_phase9.sql` (mandatory — MySQL DDL auto-commits, there is no transactional undo).
2. **Baseline capture (read-only):** run the Section 0 counts in the draft script; store the output as evidence.
3. **Restore-test the draft on a copy:** restore the dump into a scratch database and apply `phase9_scope_reconciliation.sql` there first.
4. **Verify on the copy:** re-run Section 5 verification queries — all counts must match the baseline exactly; `ph_values_preserved` must equal the pre-migration non-NULL count.
5. **Apply to the real database** (single maintenance window; after the Phase 10 Step 4 amendment the corrected draft issues **6** statements in order: §1 combined `water_readings` ALTER → §2 `system_config` → §3 `devices` → §4 `predictions` guard + ADD COLUMN `score_method` → §4B `system_config` band-columns guard + ADD COLUMN → §4C `predictions` index guard + ADD INDEX).
6. **Post-apply verification:** same queries again, plus `SHOW COLUMNS` to confirm `IS_NULLABLE = YES` and the widened enum.
7. **Record** the application date/version in `PROJECT_STATUS.md`.
8. **Only then** may Phase 10 runtime code start writing NULL/ESP8266 values.

> Execution is **explicitly out of scope for Phase 9** and requires your approval in a later phase.

---

## 5. Backward-Compatibility Considerations

| Scenario | Behaviour after migration | Needs code change? |
|---|---|---|
| Existing rows with pH/temperature values | Values untouched; remain readable; scored with the old formula | No |
| Pre-Phase-5 rows with `prediction = NULL` | Unchanged (`GET /api/predictions/latest` already skips them) | No |
| Legacy `SIMULATION` client sending all 6 fields | Columns accept them; NULLs not required | Optional (Phase 12 simulator decision) |
| **New ESP8266 client sending only `device_id/tds/turbidity/source`** | Stored with `ph = NULL`, `temperature = NULL` | **Yes — Phase 10 schema/service change (422 today)** |
| Rows with `source = 'ESP32'` | Still a valid enum member → never invalidated | No |
| Frontend reading `ph`/`temperature` of new rows | Would receive `null` | **Yes — Phase 13 (dashboard shows only TDS/turbidity)** |
| MySQL enum narrowing hazard | Avoided: only widening is used | — |

**API-side compatibility (must accompany the migration, Phase 10):** the migration alone does **not** change API behaviour. `POST /api/readings` still returns **422** for a payload without `ph`/`temperature` until the Pydantic schemas are relaxed — see `docs/api.md` §"Proposed Phase 9 contract (NOT YET IMPLEMENTED)".

---

## 6. Distinguishing Legacy vs New Scores

Two scores with different formulas will coexist. They must never be compared silently.

| | Legacy score | New score |
|---|---|---|
| Formula | 4 parameters (pH 0.35, TDS 0.30, Turbidity 0.25, Temperature 0.10) | 2 parameters (TDS, Turbidity only) |
| Rows | every row written up to the Phase 10 cutover | rows written after the cutover |
| Storage marker | `score_method IS NULL` (or `'FOUR_PARAM_LEGACY'`) | `score_method = 'TWO_PARAM_SCREENING'` |
| API field (proposed) | `quality_score` + `score_method: "FOUR_PARAM_LEGACY"` | `quality_score` + `score_method: "TWO_PARAM_SCREENING"` |

**Design choices:**
- `score_method` is added as a **NULLable column with DEFAULT NULL**; legacy rows are **not backfilled**, because backfilling would mean `UPDATE`-ing existing records (prohibited). `NULL` is therefore *defined* as legacy four-parameter.
- If the optional column is rejected in review, the fallback is to derive the method at read time: `reading.ph IS NULL → TWO_PARAM_SCREENING`, otherwise `FOUR_PARAM_LEGACY`. This is stored-data-free but must then be applied consistently by API *and* frontend.
- Charts, statistics and exports must group or label by `score_method` rather than averaging the two together.

Full scoring design: `docs/PHASE_9_QUALITY_ASSESSMENT_DESIGN.md`.

---

## 7. Rollback Strategy

- **Preferred:** restore the pre-migration `mysqldump` (DDL is non-transactional; a point-in-time restore is the only complete undo).
- **Secondary:** reverse ALTERs are provided as commented statements in §6 of the draft script, each preceded by a **guard query that must return 0** before it may run:
  - Drop `score_method` only if no row uses it.
  - Narrow the `source` enum back only if **no row** uses `'ESP8266'` — otherwise narrowing would invalidate records (violating the preservation rule).
  - Restore `NOT NULL` on `system_config` thresholds only if no NULL exists.
  - Restore `NOT NULL` on `water_readings.ph/temperature` only if no NULL exists (i.e. only before real hardware data arrives).
- **Rollback of the API contract (Phase 10 code)** is independent of the DB rollback: reverting the code re-imposes 422 without breaking stored data, because nullable columns accept non-NULL values.

---

## 8. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| MySQL implicit commit — partial application if a statement fails | High | Backup + staging dry-run first; run statements one at a time and verify |
| Accidentally narrowing an enum (destroys `ESP32` rows) | High | Script only widens; guard queries before any rollback |
| Migration applied before Phase 10 code is ready | Low | Nullable columns are backwards compatible — old code keeps sending non-NULL values |
| Code ready before migration applied | Medium | New ESP8266 payloads would fail with a MySQL **1048 "column cannot be null"** → apply migration first (ordering enforced in the roadmap) |
| Two incompatible scores mixed in charts/statistics | Medium | `score_method` marker + grouped reporting (§6) |
| Someone executes the draft script during Phase 9 | High | Script header states DRAFT/NOT FOR EXECUTION; execution is prohibited this phase |

---

## 9. Confirmation

- ✅ No migration SQL was executed.
- ✅ No historical records were changed.
- ✅ No columns, indexes or constraints were dropped.
- ✅ Only a new draft file was created: `database/migrations/phase9_scope_reconciliation.sql`.
