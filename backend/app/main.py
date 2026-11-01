from contextlib import asynccontextmanager
import math

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from datetime import datetime, timezone

from app.config import get_settings
from app.database import engine, Base, check_db_connection
from app.ml.service import get_ml_service, ML_DISCLAIMER
from app.routers import readings, config, predictions, devices
from app.sse import event_generator

# Ensure database tables exist
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    # Log warning if initial DB check fails (e.g. during offline test run)
    pass

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm up the ML artifact once at startup (never blocks/fails the API)."""
    get_ml_service().warm_up()
    yield


app = FastAPI(
    title="Smart Water Quality Monitoring API",
    description="IoT-based Water Quality Monitoring and ML-based Potability Prediction System",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(readings.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(predictions.router, prefix="/api")
# Phase 10 (D6): device endpoints expose connectivity only - no sensor-health claim.
app.include_router(devices.router, prefix="/api")


def _json_safe_non_finite(value):
    """Recursively render non-finite floats as strings so 422 payloads stay
    JSON-serializable (starlette's JSONResponse uses allow_nan=False). Without
    this, FastAPI's default validation handler crashes while echoing a rejected
    Infinity/NaN input back to the client and the request surfaces as an
    unhandled HTTP 500 instead of the intended 422."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)  # 'inf' | '-inf' | 'nan'
    if isinstance(value, dict):
        return {key: _json_safe_non_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_non_finite(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def json_safe_request_validation_handler(request: Request, exc: RequestValidationError):
    """Same 422 contract as FastAPI's default handler ({'detail': [errors...]});
    only non-finite input echoes are sanitized (Phase 10 non-finite input fix).
    For all other inputs the payload is identical to the default handler's."""
    return JSONResponse(
        status_code=422,
        content={"detail": _json_safe_non_finite(jsonable_encoder(exc.errors()))},
    )


@app.get("/health", tags=["System"])
def health_check():
    """System health check endpoint verifying FastAPI process and database connectivity."""
    db_ok = check_db_connection()
    ml_svc = get_ml_service()
    return {
        "status": "healthy" if db_ok else "degraded",
        "service": "Smart Water Quality Monitoring API",
        "database": "connected" if db_ok else "disconnected",
        "ml_model": "loaded" if ml_svc.is_loaded else "unavailable",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0"
    }


@app.get("/ml/status", tags=["ML"])
def ml_status():
    """ML model availability, training metadata, and performance metrics.

    Returns real measured metrics from training — never hardcoded values.
    """
    import json, pathlib
    svc = get_ml_service()
    metrics_path = pathlib.Path(settings.METRICS_PATH)
    metrics = None
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:
            metrics = None

    return {
        "available": svc.is_loaded,
        "model_path": str(svc.model_path),
        "last_error": svc.last_error,
        "disclaimer": ML_DISCLAIMER,
        "metrics": metrics,
    }


@app.get("/api/stream", tags=["Real-time"])
async def sse_stream(request: Request):
    """
    Server-Sent Events stream for real-time reading push.

    Every new reading POSTed to /api/readings is broadcast here immediately.
    Heartbeat comment lines are sent every 15 s to keep the connection alive
    through Render / Vercel / nginx proxies.

    Connect with:
        const es = new EventSource('https://<render-url>/api/stream')
        es.onmessage = (e) => { const reading = JSON.parse(e.data); ... }
    """
    return StreamingResponse(
        event_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
            "Connection": "keep-alive",
        },
    )


@app.get("/", tags=["System"])
def root():
    return {
        "message": "Smart Water Quality Monitoring & ML Potability Prediction API is running.",
        "health_check": "/health",
        "ml_status": "/ml/status",
        "realtime_stream": "/api/stream (SSE)",
        "docs": "/docs"
    }
