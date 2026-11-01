# Decision — `Prediction.reading_id` Uniqueness (One-to-One Prediction-to-Reading)

> **Type:** Architecture/design decision record (ADR).
> **Status:** DECIDED (Option A) — **IMPLEMENTATION NOT AUTHORIZED.** This document is a design decision, **not migration authorization**. Production migration remains separately approval-gated (Gate 3), and any `UNIQUE` constraint implementation requires its own **new, separately approved migration executed only after the Phase 10 production migration**.
> **Scope of this file:** documentation only. No UNIQUE constraint was added, no migration SQL was created, no application code, tests, `schema.sql`, backups, or existing migration files were changed.
> **Date:** 2026-10-31 · **Source investigation:** read-only code/schema/test review of `D:\EVS`.
> **Related records:** `docs/PHASE_10_FINAL_MIGRATION_READINESS_REVIEW.md` (finding F-6, condition 9), `docs/PHASE_10_PRODUCTION_MIGRATION_EXECUTION_RUNBOOK.md` (§10 deployment concern (a), §14 follow-up item).

---

## 1. Problem — current model/schema mismatch

| Layer | Definition | Enforces uniqueness? |
|---|---|---|
| SQLAlchemy model `backend/app/models/prediction.py` line 47 | `reading_id = Column(Integer, ForeignKey("water_readings.id", ondelete="CASCADE"), nullable=False, unique=True)` | Model metadata: **yes** |
| ORM relationship `backend/app/models/water_reading.py` line 24 | `assessment = relationship("Prediction", back_populates="reading", uselist=False, cascade="all, delete-orphan")` | ORM: models **one-to-one** (`uselist=False`) |
| `database/schema.sql` lines 39–53 | `reading_id INT NOT NULL` + `CONSTRAINT fk_prediction_reading FOREIGN KEY (reading_id) REFERENCES water_readings(id) ON DELETE CASCADE` — **no UNIQUE** | Database: **no** |
| Live MySQL baseline (Phase C/E inventories: 8 constraints, none on `reading_id`) | FK only | Database: **no** |
| DB-free test databases (in-memory SQLite via `Base.metadata.create_all`) | `unique=True` produces a real UNIQUE column constraint | Tests: **yes** |

**The mismatch:** the model, ORM, and test schema all assume and enforce one prediction per reading; **production MySQL does not.** The database is the inconsistent layer — it allows duplicate `reading_id` values that the rest of the system is not designed to handle. Documentation compounds the drift: `docs/PHASE_10_BACKEND_IMPLEMENTATION_PLAN.md` line 22 and `PROJECT_AUDIT_REPORT.md` lines 88/115 describe `reading_id` as "unique"/"1:1", which is false of the DB today.

**Duplicate handling if a duplicate ever appeared** (manual SQL, restore/merge, future re-scoring): `uselist=False` emits a SAWarning and returns an arbitrary row; the six scalar accessors on `WaterReading` (`prediction`, `confidence`, `quality_score`, `score_method`, `safety_status`, `warning_message`) and `Prediction.query.filter(reading_id == X).first()` become nondeterministic; `GET /predictions/latest` could surface either row; count/orphan preservation audits would break.

## 2. Evidence that one-to-one is the intended invariant

1. **Single creation path:** `app/services/reading_service.py` lines 132–143 (`create_reading_with_assessment`) creates **exactly one** `Prediction` per newly created `WaterReading`, committed atomically; called only by `POST /api/readings` (`app/routers/readings.py` line 109).
2. **No competing path:** no PUT/PATCH/DELETE endpoint exists for readings or predictions; no `.update(` / `.delete(` on predictions anywhere in `app/`; no manual `.assessment = …` assignment (grep: 0 matches); service docstring: "No existing row is ever UPDATEd or DELETEd."
3. **ORM models it as one-to-one:** `uselist=False` + `cascade="all, delete-orphan"`, with scalar property accessors throughout `water_reading.py`.
4. **Data conforms:** Phase F offline parse of the verified backup — **500 predictions, 500 distinct `reading_id`, 0 duplicates, 0 orphans**.
5. **Docs state it:** plan line 22 ("FK, **unique**, CASCADE"), audit report lines 88/115 ("1:1 … via `reading_id` unique").
6. **Tests rely on it:** `test_readings_unit` 286–290, `test_phase3_api` 196–204, `test_phase5_ml_api` 140/283, `test_readings_integration` 168, `test_phase10_contract` 170–179/503/886–891 all dereference `row.assessment` as a single object, and SQLite `create_all` enforces `unique=True`.
7. **Column is `NOT NULL`** → UNIQUE semantics are clean (no multi-NULL ambiguity).

Counter-note: no explicit requirement statement ("exactly one assessment per reading") exists — the invariant is implicit/conventional. This decision elevates it to an enforced invariant.

## 3. Options compared

| Dimension | **Option A — add UNIQUE on `predictions.reading_id`** (DB + `schema.sql`) | **Option B — remove `unique=True` from the model** |
|---|---|---|
| Aligns DB with model/ORM/docs/data | **Yes** — all five layers consistent | No — aligns only model metadata with DB; flips the mismatch onto the docs |
| SQL / approval cost | New migration DDL + separate approval | None (no SQL) |
| Duplicate prevention | **Enforced at DB** | None anywhere (SQLite tests also lose UNIQUE → duplicates become silently nondeterministic) |
| Test↔production parity | Restored (tests already enforce it) | Preserves divergence-free parity only by weakening tests |
| Data readiness | Verified: 500/500 distinct, 0 dups, 0 orphans | N/A |
| Future re-scoring / prediction history | **Blocks** 1:N — would require dropping the constraint later | Permits 1:N |
| Doc corrections required | Audit line 88 becomes accurate as-is | Plan line 22, audit 88/115 must be rewritten |
| Baseline/verification updates | Constraint count **8 → 9**, +1 unique index row → runbook §5/§14, Phase F B2/F-6 restated | None |

## 4. Selected decision — Option A

**ADOPT OPTION A: enforce one-to-one prediction-to-reading association with a `UNIQUE` constraint on `predictions.reading_id`.**

**Rationale:**
1. The data already satisfies the constraint (0 duplicates/0 orphans), so enforcement costs nothing today and prevents an undetectable-by-code hazard tomorrow.
2. Option A makes **five layers consistent** (model, ORM, tests, plan, audit report); Option B would require rewriting four of them and would silently weaken the test schema's guard.
3. The single, atomic creation path produces exactly one prediction per reading — the constraint codifies existing behavior rather than changing it.
4. `NOT NULL` + FK already exist; UNIQUE is the missing half of an association the codebase already treats as one-to-one.
5. Test/production parity: SQLite tests enforce uniqueness now; Option A brings MySQL in line instead of lowering tests to MySQL's level.

**Implementation routing (mandated):** through a **NEW, separately approved migration** executed **only after the Phase 10 production migration**. The existing hash-locked Phase 10 migration (`database/migrations/phase9_scope_reconciliation.sql`, SHA-256 `994B945D6E8621161F33148D362B255100953C95364C2EE7B90C1EEB47435650`) must **not** be modified — editing it would invalidate its Phase D/E rehearsal evidence and the Phase F READY verdict.

## 5. Risks and future implications

- **Re-scoring / prediction history:** UNIQUE **prevents** storing multiple assessments per reading (historical re-evaluations, ML re-runs, model-version comparisons). If that capability is ever required, it needs a separate design (e.g., separate `assessment_history` table, or dropping the UNIQUE) — not a silent constraint drop.
- **Migration-time failure risk:** `ALTER TABLE … ADD UNIQUE` fails if any duplicate exists at execution time → preflight (§6) is mandatory.
- **DDL implicit commit:** like all Phase 10 statements, the ALTER is non-transactional → fresh verified backup required (§6).
- **Baseline drift:** structure verification expectations change (§7) — plans/runbooks that assert "8 constraints / 15 index rows" must be restated **after** this change, not before.
- **Timing risk:** running it before/with Phase 10 would invalidate rehearsed verification sets; it is therefore sequenced strictly after.
- **Interim exposure:** until implemented, the model↔schema mismatch persists (Phase F F-6 stays WARNING) and MySQL remains free to accept duplicates via out-of-band writes.

## 6. Required preflight duplicate check (at future execution time)

Before any statement runs, read-only duplicate detection must return **zero rows**:

- Query shape: duplicates grouped on `predictions.reading_id` with `COUNT(*) > 1` (e.g., `SELECT reading_id, COUNT(*) FROM predictions GROUP BY reading_id HAVING COUNT(*) > 1;`) — **expected result: 0 rows**. *[OPERATOR CONFIRMATION REQUIRED] for exact query text and tooling at execution time.*
- Also confirm count parity: total predictions = distinct `reading_id`, and **0 orphans** (every `reading_id` resolves in `water_readings`).
- **Any nonzero result = STOP.** Duplicates must be reconciled manually (documented decision required) — never auto-deleted, never auto-reassigned; the runbook's no-deletion preservation rule applies.

## 7. Fresh backup and separate approval requirements

- **Fresh verified backup immediately before execution** — same discipline as `docs/PHASE_10_PRODUCTION_MIGRATION_EXECUTION_RUNBOOK.md` §4: write quiescence first, audited mysqldump flag set, 4 `CREATE TABLE` + 4 `INSERT`, no `CREATE DATABASE`/`USE`, SHA-256 recorded. No reuse of the existing `water_quality_db_pre_phase10_20261031_083234.sql` dump as the execution-day backup.
- **Separate explicit approval:** this decision record **is not authorization**. Execution requires its own Gate-style approval, granted only **after** the Phase 10 production migration completes and passes its §11 acceptance (including write re-enable sequencing from the runbook).
- **Schema-drift/preflight check** before the window (runbook §5 discipline): constraint/index counts, duplicate check (§6), row counts 77/503/500/1 baseline re-confirmed as applicable at that time.
- The ALTER must be executed as a single, individually approved statement with post-statement verification (SHOW INDEX/`information_schema.STATISTICS` expecting the new unique index on `reading_id`).

## 8. Expected structural baseline change

| Metric | Before | After (expected) |
|---|---|---|
| `predictions` constraints (Phase C/E/F baseline) | **8** | **9** |
| Index rows (pre-Phase-10 baseline 15; recompute post-Phase-10 at execution time) | current post-Phase-10 value | **+1** unique index on `predictions.reading_id` |
| FK `fk_prediction_reading` | unchanged | unchanged |
| Row data | 500 predictions, 500 distinct `reading_id` | unchanged (DDL only; no data mutation) |

Verification documents requiring update **when this decision is later implemented** (not now):
- `database/schema.sql` — add the UNIQUE declaration to the `predictions` table (post-Phase-10 bookkeeping sync, separately approved).
- `docs/PHASE_10_FINAL_MIGRATION_READINESS_REVIEW.md` — resolve F-6 / condition 9.
- `docs/PHASE_10_PRODUCTION_MIGRATION_EXECUTION_RUNBOOK.md` §10/§14 — close deployment concern (a); update §5/§14 structure totals (8 → 9 constraints).
- `PROJECT_AUDIT_REPORT.md` lines 88/115 — accurate under Option A once implemented; `PROJECT_STATUS.md` — record application.
- Phase F B2-style structure inventories restated with the new totals.

## 9. Authorization boundary

**This is a design decision, not migration authorization.** Specifically: no UNIQUE constraint exists or was added; no migration SQL file was created; the hash-locked Phase 10 migration is untouched; no schema, model, test, backup, or application file was changed; no database was contacted and no SQL was executed. Production migration remains **NOT APPROVED** pending separate Gate 3 approval; this decision's implementation is additionally gated behind completed Phase 10 production migration + its acceptance; **Phase 11 remains NOT STARTED.**

---

*Documentation-only artifact. Files modified by this task: `docs/DECISION_PREDICTION_READING_ID_UNIQUENESS.md` (created) — nothing else.*
