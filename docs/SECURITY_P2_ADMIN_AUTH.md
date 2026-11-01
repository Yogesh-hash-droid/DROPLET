# Security Note — P2 Admin Authentication (implemented) & Device Authentication (pending)

> **Status:** P2 admin authentication for `PUT /api/config` is **implemented in code** (backend + frontend + DB-free tests). **Device authentication is NOT implemented — that gap is a deliberate, temporary risk recorded here.**
> This note records security posture only. It does not authorize deployment, migration, or Phase 11.

## 1. What was implemented (P2 — admin authentication)

| Item | Detail |
|---|---|
| Enforcement | `backend/app/security.py` — FastAPI `APIKeyHeader(name="X-Admin-Key", auto_error=False)` + `secrets.compare_digest` |
| Config | `ADMIN_API_KEY` in `backend/app/config.py` (read from environment / `backend/.env`); placeholder in `backend/.env.example` is **empty** |
| Protected route | **Only** `PUT /api/config` (`backend/app/routers/config.py`) |
| Behavior | Server **without** `ADMIN_API_KEY` → **HTTP 503** (fail closed, checked first); missing/wrong key → **HTTP 401**; correct key → update proceeds |
| Unchanged | `GET /api/config` (no key needed), all other read endpoints, all other behavior |
| Key hygiene | Key is never printed, logged, echoed, or returned in any response body/error detail; kept out of the frontend JS bundle and out of source control (real value goes only in the untracked `backend/.env`) |
| Frontend | Admin-key input on the Settings page (`ThresholdSettingsForm.jsx`) — **React component memory only** (no `localStorage`/`sessionStorage`/cookies); sent as the `X-Admin-Key` header by `saveConfig` (`services/api.js`); distinct 401 and 503 messages, never containing the key |
| Tests | `backend/tests/test_admin_auth.py` (DB-free: 401 missing, 401 wrong, 200 correct, 503 unconfigured, unauthorized-writes-change-nothing, GET open) |

**Deployment prerequisite:** set a strong `ADMIN_API_KEY` in the deployment environment before relying on configuration updates — with it unset, `PUT /api/config` is **disabled (503)** by design. Rotate by changing the environment value.

## 2. TEMPORARY, SEPARATE RISK — `POST /api/readings` is unauthenticated (device authentication pending)

**`POST /api/readings` remains deliberately UNAUTHENTICATED** so the software simulator (`simulator/client.py` — sends only `Content-Type`) and the ESP8266 hardware (`esp32/` — no credential support) keep ingesting telemetry without interruption.

This is a **device-security risk, not an admin-authentication gap**, and the two must not be conflated:

- **Admin auth (P2)** answers: *"who may change safety thresholds?"* → **implemented**.
- **Device auth** answers: *"which devices may submit readings?"* → **not implemented**. Until it exists, any reachable client can submit telemetry (history poisoning/spam risk; no rate limiting either).

**Why kept open in this change:** adding a credential requirement to `POST /api/readings` would break the simulator and ESP8266 firmware in the same release; it needs its own design (e.g., `X-Device-Key` per device, provisioning story for hardware), its own tests, and **separate approval**. It was explicitly scoped OUT of the P2 implementation.

**Temporary until device authentication is implemented:**
1. Do not expose the readings API beyond trusted networks.
2. Treat `PUT /api/config` auth as unrelated to this exposure — closing P2 does **not** mitigate it.
3. Track this item as an open security debt alongside the Phase 10 deployment concerns (runbook §10) and Phase F findings (least-privilege account, P2 now resolved).

## 3. Explicit non-claims

- No security fix for **device** ingestion, rate limiting, TLS, or least-privilege DB access is claimed here.
- No database migration was created or run; the hash-locked Phase 10 migration is untouched; the ML artifact is untouched.
- Production migration remains **NOT APPROVED**; Phase 11 is **NOT STARTED**.
