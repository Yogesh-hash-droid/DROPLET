# Aiven baseline schema review

## Scope and safety boundary

This review prepares a schema for the new, separate Aiven MySQL 8.4 service.
It was completed without connecting to Aiven, executing SQL, running
migrations, or changing any local/test database.

The generated schema is
[`database/schema_aiven_baseline.sql`](../database/schema_aiven_baseline.sql).
It targets the already-created Aiven database `defaultdb` and does not issue
`CREATE DATABASE`, because database creation is managed by Aiven.

## Sources compared

- SQLAlchemy models under `backend/app/models/`
- Connection/session setup in `backend/app/database.py`
- Settings and URL construction in `backend/app/config.py`
- Existing pre-Phase-10 `database/schema.sql`
- Phase 10 migration
  [`phase9_scope_reconciliation.sql`](../database/migrations/phase9_scope_reconciliation.sql)

The existing `database/schema.sql` is not suitable for this deployment. It
requires pH and temperature, omits ESP8266, omits `score_method` and screening
band columns, and does not represent the current ORM model.

## Model-to-baseline mapping

| Model | Baseline result |
|---|---|
| `Device` | `devices` with `device_id` unique, source `SIMULATION`/`ESP32`/`ESP8266`, and `ONLINE`/`OFFLINE` status |
| `WaterReading` | `water_readings` with required TDS/turbidity and nullable pH/temperature |
| `Prediction` | `predictions` with nullable prediction/confidence/score method and one assessment per reading |
| `SystemConfig` | `system_config` with nullable legacy thresholds and non-null screening bands |

### Nullable two-sensor fields

The baseline declares:

```sql
ph FLOAT NULL
temperature FLOAT NULL
```

An ESP8266 payload containing only TDS and turbidity can therefore persist
honestly with SQL `NULL` for both unmeasured sensors. No pH imputation or
synthetic temperature is introduced.

### Relationships and delete behavior

- `water_readings.device_id` references `devices.device_id`.
- Deleting a device cascades to its readings, matching
  `ForeignKey(..., ondelete="CASCADE", onupdate="CASCADE")`.
- `predictions.reading_id` references `water_readings.id` with `ON DELETE
  CASCADE`.
- `reading_id` is unique, matching the one-to-one `Prediction` relationship.

### Indexes

The baseline uses SQLAlchemy's generated `ix_*` names for `index=True`
columns, including `ix_predictions_score_method`. The existing Phase 10
migration adds a differently named `idx_score_method` index for an existing
pre-Phase-10 schema. That migration must not be run blindly against this
fresh baseline; adding both indexes would be redundant.

### Defaults

The ORM uses Python-side defaults for most timestamps, enum values, and
threshold values. The baseline preserves the required server defaults for
`status_good_min = 70.0` and `status_poor_max = 40.0`. The application
provides the other model defaults when it creates rows, and
`config_service.get_system_config()` provisions the initial configuration row.

## Phase 10 migration comparison

The migration is an ALTER script for an existing pre-Phase-10 database. Its
six forward changes are already represented in the baseline:

1. Nullable `water_readings.ph` and `temperature`; ESP8266 reading source.
2. Nullable legacy pH/temperature configuration thresholds.
3. ESP8266 device source.
4. `predictions.score_method`.
5. `system_config.status_good_min` and `status_poor_max`.
6. An index for `score_method`.

Because the Aiven database is new and empty, the correct operation is to use
the baseline schema after explicit review, not to apply the ALTER migration.
The migration remains relevant only for an existing legacy database.

## Safety and quality behavior preserved

The schema does not alter application logic:

- TDS and turbidity remain `NOT NULL`.
- Safety-rule evaluation remains application-owned.
- Quality-score calculation remains application-owned.
- Missing pH causes ML inference to be skipped.
- Missing pH yields null prediction/confidence and
  `PH_NOT_MEASURED` through the existing API contract.
- No ML model or artifact is changed.

## Aiven connection prerequisites

The supplied service details are:

- MySQL 8.4
- Database: `defaultdb`
- Port: `15444`
- TLS: required

Render must receive these values privately through `MYSQL_HOST`,
`MYSQL_PORT=15444`, `MYSQL_USER`, `MYSQL_PASSWORD`, and
`MYSQL_DATABASE=defaultdb`.

The current `config.py` constructs a PyMySQL URL from `MYSQL_*`, but does not
define an explicit CA-file or SSL options setting. Before connecting, confirm
that the Aiven endpoint accepts the driver's default TLS negotiation. If Aiven
requires a CA bundle or explicit SSL parameters, the deployment configuration
must be extended before the first connection; no credentials or certificates
belong in this repository.

## Approval gate

Before any database operation:

1. Confirm the Aiven host privately and verify the target is the new service.
2. Confirm `defaultdb` is empty using a read-only inspection.
3. Confirm the baseline file and model comparison are approved.
4. Decide whether Aiven's backup/export is available before schema creation.
5. Approve execution of the baseline SQL as a separate database operation.

Until those approvals are given, no SQL, migration, or connection should be
executed.
