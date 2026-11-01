-- =====================================================================================
-- PHASE 9 DRAFT MIGRATION SCRIPT (REVIEW ONLY - NOT FOR EXECUTION)
-- =====================================================================================
-- File    : database/migrations/phase9_scope_reconciliation.sql
-- Status  : DRAFT / UNAPPLIED. This script has NOT been executed against any database.
-- Purpose : Backward-compatible schema adjustments for the final two-sensor hardware
--           scope (ESP8266 NodeMCU + ADS1115 + TDS + Turbidity).
-- Author  : Phase 9 planning (documentation only)
-- Date    : 2026-10-30
-- Updated : 2026-10-31 - Phase 10 Step 4 amendment (documentation only, NOT executed):
--           Section 4B added (B1 screening-band columns, decision R-2 = B1) and
--           Section 4C added (idx_score_method index, model parity). Sections 4/5/6
--           extended accordingly. The script remains DRAFT / UNAPPLIED.
--
-- WHAT THIS SCRIPT DOES
--   1. Makes legacy `ph` and `temperature` columns on `water_readings` NULLable.
--      -> Existing rows KEEP their historical values. Nothing is deleted or updated.
--   2. Makes legacy pH/temperature threshold columns on `system_config` NULLable.
--      -> Existing threshold values are preserved as-is.
--   3. Widens `source` ENUMs to accept the new 'ESP8266' value while keeping
--      'SIMULATION' and the legacy 'ESP32' value so historical rows remain valid.
--   4. Adds `predictions.score_method` so that legacy four-parameter scores can be
--      distinguished from new two-parameter scores (Phase 10 decision R-3: REQUIRED).
--      -> Added as a NULLable column with DEFAULT NULL. No rows are modified;
--         NULL means "legacy four-parameter score" (documented, not backfilled).
--   5. (Phase 10 Step 4 amendment, decision R-2 = B1) Adds the database-backed
--      screening bands `system_config.status_good_min` (NOT NULL DEFAULT 70.0) and
--      `system_config.status_poor_max` (NOT NULL DEFAULT 40.0).
--      -> The existing configuration row id=1 receives 70.0 / 40.0 through the
--         column DEFAULTs; every existing threshold value is preserved unchanged.
--         No UPDATE is issued against any row.
--   6. (Phase 10 Step 4 amendment) Adds index `idx_score_method` on
--      `predictions.score_method`, matching the SQLAlchemy model
--      (backend/app/models/prediction.py: index=True). An index carries no row
--      data; no values are touched.
--
-- WHAT THIS SCRIPT DOES NOT DO
--   * It does not DELETE, UPDATE or otherwise alter any existing row values.
--   * It does not drop any column, index, constraint or table.
--   * It does not touch `predictions.prediction` (already NULLable) or any ML field.
--   * It does not retrain or modify any ML artifact.
--
-- MYSQL NOTES / RISKS (read before any future application)
--   * MySQL DDL causes an IMPLICIT COMMIT - there is no transactional "undo".
--     Take a full backup (mysqldump) before applying anything.
--   * NEVER narrow an ENUM: e.g. MODIFY source ENUM('SIMULATION','ESP8266') would
--     destroy/zero every existing 'ESP32' row. ENUM must only ever be WIDENED here.
--   * Apply to a restored staging copy first and run the verification queries below.
--   * Expected affected rows for a pure widening/nullable change: data unchanged,
--     only column metadata changes.
--   * REVIEW CORRECTION (Phase 9 correction round): `water_readings` is now altered by
--     ONE combined statement (Section 1) instead of two separate ALTERs - this halves
--     the table-rebuild/lock exposure. See the note in Section 3.
--   * REVIEW CORRECTION: added an idempotency guard for the ADD COLUMN in
--     Section 4 (MySQL has no `ADD COLUMN IF NOT EXISTS` before 8.0.29, and re-running
--     the statement blindly would error). Sections 4B and 4C carry equivalent guards.
--   * ALTER TABLE ... MODIFY may rebuild the table and take a metadata/write lock on
--     large tables. Measure runtime on the staging copy and schedule a maintenance
--     window. Where supported, adding `ALGORITHM=INPLACE, LOCK=NONE` to a MODIFY lets
--     MySQL refuse the change instead of silently locking - remove the clause if the
--     server rejects it. Do NOT assume any particular algorithm without testing.
-- =====================================================================================


-- -------------------------------------------------------------------------------------
-- SECTION 0 - PRE-FLIGHT (read-only checks - safe to run at any time)
-- -------------------------------------------------------------------------------------
-- Record the baseline so "no data changed" can be proven after application.

SELECT COUNT(*) AS devices_total FROM devices;
SELECT COUNT(*) AS readings_total FROM water_readings;
SELECT COUNT(*) AS predictions_total FROM predictions;
SELECT COUNT(*) AS config_rows FROM system_config;

-- Current column nullability (expect 'NO' for ph/temperature today; status_good_min /
-- status_poor_max expected ABSENT today - they are the required Phase 10 additions):
SELECT TABLE_NAME, COLUMN_NAME, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'water_quality_db'
  AND (
        (TABLE_NAME = 'water_readings'  AND COLUMN_NAME IN ('ph','temperature','source'))
     OR (TABLE_NAME = 'system_config'   AND COLUMN_NAME IN ('ph_min','ph_max','temperature_min','temperature_max','status_good_min','status_poor_max'))
     OR (TABLE_NAME = 'devices'         AND COLUMN_NAME = 'source')
     OR (TABLE_NAME = 'predictions'     AND COLUMN_NAME IN ('prediction','quality_score','score_method'))
  )
ORDER BY TABLE_NAME, COLUMN_NAME;

-- Count of rows that currently use each source value (ESP8266 must be 0 today):
SELECT source, COUNT(*) FROM devices   GROUP BY source;
SELECT source, COUNT(*) FROM water_readings GROUP BY source;


-- -------------------------------------------------------------------------------------
-- SECTION 1 - MAKE LEGACY READING SENSORS NULLABLE + WIDEN SOURCE  (required)
-- -------------------------------------------------------------------------------------
-- `ph` and `temperature` become NULLable so that hardware readings created WITHOUT a
-- pH sensor or a temperature sensor can be stored honestly (NULL = "not measured").
-- Existing rows keep their stored values; no UPDATE is issued.
--
-- This statement ALSO widens `source` to include 'ESP8266' (requirement 3), keeping
-- 'SIMULATION' and the legacy 'ESP32' member. Combining both changes in one ALTER
-- avoids a second rebuild of the same table (Phase 9 correction).

-- >>> Migration step 1 (combined with step 3b)
ALTER TABLE water_readings
    MODIFY COLUMN ph FLOAT NULL COMMENT 'Legacy sensor. NULL = not measured (no pH sensor in final hardware scope).',
    MODIFY COLUMN temperature FLOAT NULL COMMENT 'Legacy sensor. NULL = not measured (no temperature sensor in final hardware scope).',
    MODIFY COLUMN source ENUM('SIMULATION', 'ESP32', 'ESP8266') NOT NULL DEFAULT 'SIMULATION'
        COMMENT 'Telemetry source. ESP32 retained for historical rows only; ESP8266 is the final hardware.';


-- -------------------------------------------------------------------------------------
-- SECTION 2 - MAKE LEGACY THRESHOLDS OPTIONAL / BACKWARD-COMPATIBLE  (required)
-- -------------------------------------------------------------------------------------
-- `ph_min/ph_max/temperature_min/temperature_max` become NULLable so the configuration
-- can be managed without pH/temperature. Existing values are intentionally left
-- untouched (they remain valid for evaluating legacy rows if desired).

-- >>> Migration step 2
ALTER TABLE system_config
    MODIFY COLUMN ph_min FLOAT NULL COMMENT 'Legacy threshold. NULL = inactive (no pH sensor).',
    MODIFY COLUMN ph_max FLOAT NULL COMMENT 'Legacy threshold. NULL = inactive (no pH sensor).',
    MODIFY COLUMN temperature_min FLOAT NULL COMMENT 'Legacy threshold. NULL = inactive (no temperature sensor).',
    MODIFY COLUMN temperature_max FLOAT NULL COMMENT 'Legacy threshold. NULL = inactive (no temperature sensor).';


-- -------------------------------------------------------------------------------------
-- SECTION 3 - ADD ESP8266 SOURCE VALUE  (required)
-- -------------------------------------------------------------------------------------
-- WIDEN only: keeps 'SIMULATION', the legacy 'ESP32' value (historical rows stay valid),
-- and adds 'ESP8266'. Never remove an ENUM member in this migration.

-- >>> Migration step 3a
ALTER TABLE devices
    MODIFY COLUMN source ENUM('SIMULATION', 'ESP32', 'ESP8266') NOT NULL DEFAULT 'SIMULATION'
    COMMENT 'Telemetry source. ESP32 retained for historical rows only; ESP8266 is the final hardware.';

-- >>> Migration step 3b - WIDENING OF water_readings.source IS PART OF THE COMBINED
--     STATEMENT IN SECTION 1 (Phase 9 correction: one ALTER instead of two, so the
--     table is only processed once). Do NOT issue a second ALTER for water_readings.


-- -------------------------------------------------------------------------------------
-- SECTION 4 - SCORE METHOD MARKER  (required - Phase 10 decision R-3)
-- -------------------------------------------------------------------------------------
-- Distinguishes legacy four-parameter scores from new two-parameter screening scores so
-- they are never compared as if identical.
--
-- Contract:
--   NULL                 -> legacy row scored with the OLD 4-parameter formula
--                           (all rows that exist before this migration, and any row
--                           written before the Phase 10 code change). NOT backfilled,
--                           because existing records must remain unchanged.
--   'FOUR_PARAM_LEGACY'  -> explicitly scored with the old formula (only if the
--                           application later chooses to write it).
--   'TWO_PARAM_SCREENING'-> scored with the new TDS + Turbidity formula.
--
-- >>> Migration step 4 (REQUIRED per Phase 10 decision R-3 - a stored discriminator,
--                       not read-time inference)
--
-- GUARD - run this read-only query first (required: MySQL has no
-- `ADD COLUMN IF NOT EXISTS` before 8.0.29, so blindly re-running would error):
--     SELECT COUNT(*) FROM information_schema.COLUMNS
--      WHERE TABLE_SCHEMA = 'water_quality_db'
--        AND TABLE_NAME   = 'predictions'
--        AND COLUMN_NAME  = 'score_method';
--     -> 0 means the column does not exist yet: run step 4.
--     -> 1 means step 4 was already applied: SKIP it (idempotent).
ALTER TABLE predictions
    ADD COLUMN score_method ENUM('FOUR_PARAM_LEGACY', 'TWO_PARAM_SCREENING') NULL DEFAULT NULL
    COMMENT 'NULL = legacy four-parameter score (pre-Phase-10). Two-parameter rows are tagged TWO_PARAM_SCREENING.'
    AFTER quality_score;


-- -------------------------------------------------------------------------------------
-- SECTION 4B - SCREENING BAND COLUMNS  (required - Phase 10 decision R-2 = B1, FINAL)
-- -------------------------------------------------------------------------------------
-- Adds the database-backed screening bands consumed by the two-parameter screening
-- pipeline and exposed through GET/PUT /api/config
-- (docs/PHASE_9_QUALITY_ASSESSMENT_DESIGN.md section 8; plan section 7.2):
--   status_good_min FLOAT NOT NULL DEFAULT 70.0   -> GOOD:  score >= status_good_min
--   status_poor_max FLOAT NOT NULL DEFAULT 40.0   -> POOR:  score <  status_poor_max
--   (everything else: MODERATE)
--
-- Backward compatible: the existing configuration row id=1 receives 70.0 / 40.0
-- through the column DEFAULTs; every existing threshold value (ph_min, ph_max,
-- tds_max, turbidity_max, temperature_min, temperature_max) is preserved unchanged.
-- No UPDATE is issued against any row.
--
-- Matches backend/app/models/system_config.py: both columns are Float, nullable=False,
-- default 70.0 / 40.0 with server_default 70.0 / 40.0.
--
-- >>> Migration step 4B
--
-- GUARD - run this read-only query first (MySQL has no `ADD COLUMN IF NOT EXISTS`
-- before 8.0.29, so blindly re-running would error):
--     SELECT COUNT(*) FROM information_schema.COLUMNS
--      WHERE TABLE_SCHEMA = 'water_quality_db'
--        AND TABLE_NAME   = 'system_config'
--        AND COLUMN_NAME IN ('status_good_min', 'status_poor_max');
--     -> 0 means neither band column exists yet: run step 4B.
--     -> 2 means step 4B was already applied: SKIP it (idempotent re-run).
--     -> 1 means a partial state: do NOT run the combined statement; add ONLY the
--        missing column manually, then re-verify.
ALTER TABLE system_config
    ADD COLUMN status_good_min FLOAT NOT NULL DEFAULT 70.0
        COMMENT 'Screening band: GOOD when score >= status_good_min (Phase 10 decision R-2 = B1).',
    ADD COLUMN status_poor_max FLOAT NOT NULL DEFAULT 40.0
        COMMENT 'Screening band: POOR when score < status_poor_max (Phase 10 decision R-2 = B1).';


-- -------------------------------------------------------------------------------------
-- SECTION 4C - score_method INDEX  (required for model parity - Phase 10 amendment)
-- -------------------------------------------------------------------------------------
-- backend/app/models/prediction.py declares Prediction.score_method with index=True;
-- the original draft added the column (Section 4) without its index. This adds the
-- matching index. An index holds no row data - no values are touched.
--
-- >>> Migration step 4C
--
-- GUARD - run this read-only query first (prevents duplicate index creation):
--     SELECT COUNT(*) FROM information_schema.STATISTICS
--      WHERE TABLE_SCHEMA = 'water_quality_db'
--        AND TABLE_NAME   = 'predictions'
--        AND INDEX_NAME   = 'idx_score_method';
--     -> 0 means the index does not exist yet: run step 4C.
--     -> 1 means step 4C was already applied: SKIP it (idempotent re-run).
ALTER TABLE predictions
    ADD INDEX idx_score_method (score_method);


-- -------------------------------------------------------------------------------------
-- SECTION 5 - POST-FLIGHT VERIFICATION  (read-only)
-- -------------------------------------------------------------------------------------
-- Prove that no data changed: counts must match Section 0 exactly.

SELECT COUNT(*) AS devices_total_after FROM devices;
SELECT COUNT(*) AS readings_total_after FROM water_readings;
SELECT COUNT(*) AS predictions_total_after FROM predictions;
SELECT COUNT(*) AS config_rows_after FROM system_config;

-- Prove historical values survived (this must return the same number of non-NULL pH /
-- temperature rows as before the migration - i.e. every legacy row):
SELECT
    COUNT(*) AS readings_total,
    COUNT(ph) AS ph_values_preserved,
    COUNT(temperature) AS temperature_values_preserved,
    SUM(CASE WHEN source = 'ESP8266' THEN 1 ELSE 0 END) AS esp8266_rows
FROM water_readings;

-- Prove the enum now accepts ESP8266 (metadata only):
SHOW COLUMNS FROM devices LIKE 'source';
SHOW COLUMNS FROM water_readings LIKE 'source';
SHOW COLUMNS FROM water_readings WHERE Field IN ('ph','temperature');

-- Prove the Phase 10 Step 4 amendments (Sections 4B / 4C) landed correctly:
SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'water_quality_db'
  AND TABLE_NAME   = 'system_config'
  AND COLUMN_NAME IN ('status_good_min', 'status_poor_max');
-- expect exactly 2 rows: FLOAT / NO / 70.0 and FLOAT / NO / 40.0

SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'water_quality_db'
  AND TABLE_NAME   = 'predictions'
  AND COLUMN_NAME  = 'score_method';
-- expect ENUM('FOUR_PARAM_LEGACY','TWO_PARAM_SCREENING') / YES / NULL

SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = 'water_quality_db'
  AND TABLE_NAME   = 'predictions'
  AND INDEX_NAME   = 'idx_score_method';
-- expect exactly one row: idx_score_method / non-unique / column score_method

SELECT status_good_min, status_poor_max FROM system_config WHERE id = 1;
-- expect 70.0 and 40.0 (or the operator's intentionally customized values)


-- -------------------------------------------------------------------------------------
-- SECTION 6 - ROLLBACK (DRAFT - DO NOT EXECUTE)
-- -------------------------------------------------------------------------------------
-- MySQL cannot roll DDL back automatically. Use the statements below only to reverse
-- the migration, and only after checking the guard query immediately preceding each one.
--
-- IMPORTANT: Rolling back the ENUM (Section 3) requires that NO row uses 'ESP8266'.
-- If ESP8266 rows exist they must first be reviewed - narrowing an ENUM silently
-- invalidates those rows, which would violate the "preserve existing records" rule.
--
-- -- >>> Rollback 4 (only if step 4 was applied)
-- -- Guard: SELECT COUNT(*) FROM predictions WHERE score_method IS NOT NULL;  -- must be 0
-- -- ALTER TABLE predictions DROP COLUMN score_method;
--
-- -- >>> Rollback 4C (Phase 10 amendment - index only; may be dropped INDEPENDENTLY of
-- --                   any column rollback - an index carries no row data)
-- -- ALTER TABLE predictions DROP INDEX idx_score_method;
--
-- -- >>> Rollback 4B (Phase 10 amendment - screening-band columns)
-- -- Guard (MUST return 0 before this DROP may even be considered):
-- -- SELECT COUNT(*) FROM system_config
-- --  WHERE id = 1 AND (status_good_min <> 70.0 OR status_poor_max <> 40.0);
-- -- If the guard returns > 0 the configuration has been customized: customized values
-- -- are real data - export/back them up first, or leave the columns in place.
-- -- NEVER silently discard customized configuration values.
-- -- ALTER TABLE system_config
-- --     DROP COLUMN status_good_min,
-- --     DROP COLUMN status_poor_max;
--
-- -- >>> Rollback 3 (only if NO row uses ESP8266)
-- -- Guard: SELECT COUNT(*) FROM devices WHERE source='ESP8266';
-- --        SELECT COUNT(*) FROM water_readings WHERE source='ESP8266';      -- both must be 0
-- -- ALTER TABLE devices       MODIFY COLUMN source ENUM('SIMULATION','ESP32') NOT NULL DEFAULT 'SIMULATION';
-- -- ALTER TABLE water_readings MODIFY COLUMN source ENUM('SIMULATION','ESP32') NOT NULL DEFAULT 'SIMULATION';
--
-- -- >>> Rollback 2 (restores NOT NULL on config thresholds; values are already intact)
-- -- Guard: SELECT COUNT(*) FROM system_config WHERE ph_min IS NULL OR ph_max IS NULL
-- --           OR temperature_min IS NULL OR temperature_max IS NULL;                 -- must be 0
-- -- ALTER TABLE system_config
-- --     MODIFY COLUMN ph_min FLOAT NOT NULL DEFAULT 6.5,
-- --     MODIFY COLUMN ph_max FLOAT NOT NULL DEFAULT 8.5,
-- --     MODIFY COLUMN temperature_min FLOAT NOT NULL DEFAULT 10.0,
-- --     MODIFY COLUMN temperature_max FLOAT NOT NULL DEFAULT 35.0;
--
-- -- >>> Rollback 1 (restores NOT NULL on reading sensors; fails if any row is NULL)
-- -- Guard: SELECT COUNT(*) FROM water_readings WHERE ph IS NULL OR temperature IS NULL;  -- must be 0
-- -- ALTER TABLE water_readings
-- --     MODIFY COLUMN ph FLOAT NOT NULL,
-- --     MODIFY COLUMN temperature FLOAT NOT NULL;
--
-- >>> Preferred rollback: restore the pre-migration mysqldump backup, since DDL is
--     non-transactional and per-statement guards may not cover every edge case.

-- =====================================================================================
-- END OF DRAFT SCRIPT - NOT APPLIED
-- =====================================================================================
