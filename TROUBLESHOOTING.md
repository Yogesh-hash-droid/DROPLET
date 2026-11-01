# DROPLET Troubleshooting & Deployment Guide

This runbook covers common deployment issues, architecture details, and exact configuration variables for Render, Vercel, and the ESP8266 node.

---

## 1. Quick Troubleshooting Reference

### Issue A: CORS Policy Error in Browser Console
**Symptom:**
```text
Access to XMLHttpRequest at 'https://droplet-api-byl8.onrender.com/api/readings/history?limit=200'
from origin 'https://droplet-cyan.vercel.app' has been blocked by CORS policy:
No 'Access-Control-Allow-Origin' header is present on the requested resource.
```
**Root Causes:**
1. **Render Free-Tier Sleep / Cold Start:** When the Render instance is idle for 15+ minutes, it spins down. Requests received during cold start or redeploy hit the Cloudflare/Render edge proxy before FastAPI starts. When the edge proxy returns 502/504 or 404, it lacks CORS headers. Chrome blocks the response and reports a CORS failure.
2. **500 Server Error:** If an unhandled exception occurs in FastAPI (e.g. schema validation), Starlette's default 500 handler bypasses CORSMiddleware.
3. **CORS_ORIGINS Mismatch:** `CORS_ORIGINS` on Render did not list the Vercel domain.

**Fixes Applied:**
- Added regex matching in `backend/app/main.py`: `allow_origin_regex=r"https://.*\.vercel\.app"`.
- Added a global `@app.exception_handler(Exception)` so all 500 responses return clean JSON and pass through `CORSMiddleware`.
- Fixed `LatestPredictionResponse` schema in `backend/app/schemas/prediction.py` to allow `Optional[float]` for readings where `ph` is null.
- Vercel rewrites in `frontend/vercel.json` proxy `/api/*` and `/ml/*` directly, enabling same-origin requests from the browser.

---

### Issue B: Render Free-Tier Sleep & Cold Starts
**Symptom:** First request from ESP8266 or frontend takes 20-45 seconds, or firmware prints `-11 Read timeout`.

**Fixes:**
1. **Firmware:** The ESP8266 sketch uses `COLD_START_EXTRA_MS = 25000` (25-second timeout) on the initial request and `15000` on subsequent requests with exponential backoff and no crash.
2. **Keep-Alive Cron:** Set up an external uptime monitor (e.g., [cron-job.org](https://cron-job.org) or UptimeRobot) pinging `https://droplet-api-byl8.onrender.com/health` every 10 minutes to prevent the container from sleeping.
3. **Paid Plan:** Upgrading to Render Starter ($7/mo) permanently disables spin-down.

---

### Issue C: Wrong URL or HTTP vs. HTTPS (301 / 302 Redirects)
**Symptom:** Firmware logs `301 Moved Permanently` or `302 Found`.
**Cause:** Using `http://` instead of `https://`. Render enforces HTTPS and redirects all plain HTTP traffic. The ESP8266 HTTPClient does not follow redirects automatically and aborts.
**Fix:** Always use the full HTTPS URL:
`https://droplet-api-byl8.onrender.com/api/readings`

---

### Issue D: Database TLS / SSL Connection Failures
**Symptom:** Backend health check reports `"database": "disconnected"`, or startup crashes with `SSLError`.
**Cause:** Cloud MySQL (Aiven, PlanetScale, AWS RDS) enforces TLS.
**Fix:**
- Set `MYSQL_SSL=true`.
- For managed MySQL services requiring CA validation (e.g., Aiven), download the project CA certificate and set `MYSQL_SSL_CA=/path/to/ca.pem` or leave CA verification to system certificates.
- Set connection pool parameters with `pool_recycle=280` and `pool_pre_ping=True` to prune stale cloud connections.

---

### Issue E: Model Lost on Redeploy or Shows "UNAVAILABLE"
**Symptom:** `/health` reports `"ml_model": "unavailable"` or `/ml/status` returns `"available": false`.
**Root Causes:**
1. Render containers use ephemeral filesystems. Anything generated during runtime is erased on restart or redeploy.
2. ESP8266 reading has `ph: null` (no physical pH sensor probe), so the contract correctly flags `ml_status_reason: "PH_NOT_MEASURED"`.
**Fixes Applied:**
- Build command in `render.yaml` executes:
  `pip install -r requirements.txt && python ../ml/train.py --simulated`
  This guarantees the model is trained and baked directly into the build image before `uvicorn` starts.
- Model artifact `ml/models/water_potability_model.joblib` and metrics `ml/models/model_metrics.json` are committed to the git repository as a persistent fallback.
- `MLInferenceService.load()` has multi-path resolution (configured path -> repo root -> backend relative).

---

## 2. Exact Environment Variables

### Render Backend (`droplet-api`)

| Variable | Recommended Value | Purpose |
|---|---|---|
| `ENVIRONMENT` | `production` | Enables production mode |
| `PORT` | `10000` | Port assigned by Render (automatically bound by `$PORT`) |
| `CORS_ORIGINS` | `https://droplet-cyan.vercel.app,http://localhost:5173` | Allowed origins (regex also allows all `*.vercel.app`) |
| `MYSQL_HOST` | `<your-mysql-host>` | External MySQL hostname (e.g. Aiven) |
| `MYSQL_PORT` | `15444` | External MySQL port |
| `MYSQL_USER` | `avnadmin` | MySQL username |
| `MYSQL_PASSWORD` | `<your-db-password>` | MySQL password |
| `MYSQL_DATABASE` | `defaultdb` | MySQL database name |
| `MYSQL_SSL` | `true` | Enforces TLS for external DB connections |
| `MODEL_PATH` | `/opt/render/project/src/ml/models/water_potability_model.joblib` | Model artifact path |
| `METRICS_PATH` | `/opt/render/project/src/ml/models/model_metrics.json` | Model metrics metadata path |
| `ADMIN_API_KEY` | `<your-secure-secret-key>` | Protects `PUT /api/config` |
| `PYTHONIOENCODING` | `utf-8` | Ensures UTF-8 terminal encoding |

---

### Vercel Frontend (`droplet-cyan`)

| Variable | Recommended Value | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `/api` *(or empty)* | Uses Vercel's built-in proxy rewrite to eliminate CORS |
| `VITE_API_TARGET` | `https://droplet-api-byl8.onrender.com` | Target Render backend URL |

> **Note:** Leaving `VITE_API_BASE_URL=/api` routes all API requests through `vercel.json` rewrites on the server side. This eliminates browser CORS preflights and prevents cold-start CORS errors.

---

## 3. How to Run the Simulator

To stream realistic sensor readings to the cloud backend at 1-second intervals without physical hardware:

```bash
# 1. Normal clean water scenario (Safe, 1-second intervals)
python simulator/simulator.py --scenario normal --interval 1 --base-url "https://droplet-api-byl8.onrender.com"

# 2. Contaminated scenario (High TDS, Unsafe)
python simulator/simulator.py --scenario high_tds --interval 1 --base-url "https://droplet-api-byl8.onrender.com"

# 3. Turbidity spike
python simulator/simulator.py --scenario turbid --interval 1 --base-url "https://droplet-api-byl8.onrender.com"
```

The simulator prints the HTTP status code, ML potability prediction, confidence score, and safety status for every reading in real time.
