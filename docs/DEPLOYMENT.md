# DROPLET deployment runbook

This runbook prepares the first deployment without executing database
operations. It targets a FastAPI service on Render, a React/Vite site on
Vercel, and a new Aiven MySQL service.

## 1. Aiven MySQL

Create a new, separate Aiven MySQL service. Do not select or reuse
`water_quality_db_test` or any existing production database.

After the service is running, create an empty application database if the
Aiven service did not provision one automatically. Record these settings in a
password manager, not GitHub or chat:

| Application setting | Aiven value |
|---|---|
| `MYSQL_HOST` | Aiven service host |
| `MYSQL_PORT` | Aiven MySQL port, normally `3306` |
| `MYSQL_USER` | Dedicated application user |
| `MYSQL_PASSWORD` | Dedicated application password |
| `MYSQL_DATABASE` | New empty database name |

Use the Aiven TLS/SSL requirement for the client connection. If Aiven
requires an explicit SQLAlchemy URL, use:

```text
mysql+pymysql://<user>:<password>@<host>:<port>/<database>
```

Do not commit the URL. The application currently accepts the individual
`MYSQL_*` settings and constructs this URL safely.

Before any migration:

1. Confirm the service and database are the new Aiven resources.
2. Confirm the target database is empty or contains only an explicitly
   approved baseline.
3. Confirm a fresh backup/export is available and restorable.
4. Review the migration statements below and obtain explicit database-operation
   approval.

## 2. Render FastAPI

The repository includes [`render.yaml`](../render.yaml). In Render:

1. Create a new Blueprint from the GitHub repository
   `Yogesh-hash-droid/DROPLET`.
2. Select branch `main`.
3. Review the `droplet-api` service before applying it.
4. Set the secret/environment values:
   - `CORS_ORIGINS`: the final Vercel URL, for example
     `https://droplet.example.vercel.app`
   - `MYSQL_HOST`
   - `MYSQL_PORT=3306`
   - `MYSQL_USER`
   - `MYSQL_PASSWORD`
   - `MYSQL_DATABASE`
   - `ADMIN_API_KEY`: generate a strong random value, or leave configuration
     updates disabled until it is provisioned.
5. Do not set `MODEL_PATH` to an unavailable public URL. The configured path
   is intentionally allowed to be absent; the API remains available with ML
   unavailable until private artifact delivery is arranged.
6. Deploy the service and verify:
   - `GET https://<render-service>.onrender.com/health`
   - response status is `healthy` and database is `connected`.

The Render start command is:

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## 3. Vercel React frontend

The repository includes [`vercel.json`](../frontend/vercel.json).

1. Import the same GitHub repository into Vercel.
2. Set the project root to `frontend`.
3. Keep the framework as Vite.
4. Set the production environment variable:
   - `VITE_API_BASE_URL=https://<render-service>.onrender.com/api`
5. Deploy and record the actual Vercel production URL.
6. Update Render's `CORS_ORIGINS` with that exact HTTPS origin, without a
   trailing path.
7. Redeploy/restart the Render service after changing CORS.

The frontend defaults to `/api` for local Vite proxy development. Production
uses `VITE_API_BASE_URL` so Vercel can call the Render API directly.

## 4. Phase 10 migration review before execution

Do not run the migration during deployment preparation. Review
[`phase9_scope_reconciliation.sql`](../database/migrations/phase9_scope_reconciliation.sql)
against the actual empty Aiven schema and verify the file hash recorded in the
production runbook.

The six forward statements are:

1. Make `water_readings.ph` and `temperature` nullable and add `ESP8266` to
   the reading source enum.
2. Make legacy pH/temperature configuration thresholds nullable.
3. Add `ESP8266` to the device source enum.
4. Add `predictions.score_method`.
5. Add `system_config.status_good_min` and `status_poor_max`.
6. Add `predictions.idx_score_method`.

The migration must preserve the two-sensor contract:

- TDS and turbidity remain required.
- Missing pH and temperature remain SQL `NULL`.
- Safety screening and quality score continue.
- Missing pH skips ML inference.
- Prediction and confidence remain `NULL`.
- `ml_status_reason` is `PH_NOT_MEASURED`.

On a completely empty new database, first establish the approved baseline
schema/provisioning path. Do not blindly apply a migration designed to alter
an existing pre-Phase-10 schema. Capture the target schema inspection and
approval before executing any DDL.

## 5. ML artifact delivery

ML is intentionally non-blocking for the first deployment. Without the
private `.joblib` artifact, startup logs a warning and the API remains
available. Readings continue with deterministic safety screening and quality
score; ML prediction and confidence remain unavailable.

When private artifact delivery is approved, place the artifact at the
configured `MODEL_PATH` through a private deployment mechanism. Never commit
the artifact or put it in a public GitHub release.

## 6. End-to-end acceptance

Deployment is not complete until all of these are verified with live URLs:

1. Render `/health` is healthy and connected to the new Aiven database.
2. Vercel loads the dashboard.
3. A two-sensor `ESP8266` POST stores TDS/turbidity with pH and temperature
   null.
4. Latest/history endpoints return the new reading.
5. Dashboard shows TDS, turbidity, score, screening status, and timestamp.
6. Dashboard shows ML `UNAVAILABLE` with `PH_NOT_MEASURED`, without a
   potability prediction or confidence.
7. No production migration is claimed until the separately approved operation
   is executed and verified.
