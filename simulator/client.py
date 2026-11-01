"""
HTTP client for the simulator: every reading goes through the real backend
via `POST /api/readings` - never around it, so safety rules, the Water
Quality Score and the ML inference all run exactly as they do for ESP32.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 10.0
SOURCE = "SIMULATION"  # always software-generated data (never ESP32)


def _urlopen(request: urllib.request.Request, timeout: float):
    """Indirection so tests can stub the transport without a live server."""
    return urllib.request.urlopen(request, timeout=timeout)


def build_payload(device_id: str, reading) -> Dict[str, Any]:
    """
    Build the exact JSON contract shared with the future ESP32 firmware.

    `source` is always "SIMULATION": software-generated sensor data.
    """
    if not device_id or not str(device_id).strip():
        raise ValueError("device_id must be a non-empty string")
    return {
        "device_id": str(device_id),
        "ph": float(reading.ph),
        "tds": float(reading.tds),
        "turbidity": float(reading.turbidity),
        "temperature": float(reading.temperature),
        "source": SOURCE,
    }


@dataclass(frozen=True)
class ApiResponse:
    """Result of one POST: never raises - errors are data, not exceptions."""

    status: Optional[int]
    ok: bool
    body: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def prediction(self) -> Optional[str]:
        return (self.body or {}).get("prediction")

    @property
    def confidence(self) -> Optional[float]:
        return (self.body or {}).get("confidence")

    @property
    def safety_status(self) -> Optional[str]:
        return (self.body or {}).get("safety_status")

    @property
    def detail(self) -> Optional[str]:
        if self.error:
            return self.error
        body = self.body or {}
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return json.dumps(detail)
        return None


def post_reading(
    base_url: str,
    payload: Dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT,
) -> ApiResponse:
    """
    POST one reading to `<base_url>/api/readings`.

    Returns an ApiResponse for every outcome: 2xx with the parsed body, an
    HTTP error status with the API's error detail, or a transport failure
    (server down, timeout). Nothing is swallowed silently - the caller prints
    the reason.
    """
    url = f"{base_url.rstrip('/')}/api/readings"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlopen(request, timeout) as response:
            raw = response.read().decode("utf-8")
            status = getattr(response, "status", None) or response.getcode()
            body = json.loads(raw) if raw else {}
            return ApiResponse(status=int(status), ok=True, body=body)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8")
            body = json.loads(raw) if raw else {}
        except Exception:  # noqa: BLE001 - keep the original failure visible
            body = {}
        return ApiResponse(
            status=int(exc.code),
            ok=False,
            body=body,
            error=f"HTTP {exc.code}: {json.dumps(body)[:300] if body else exc.reason}",
        )
    except Exception as exc:  # noqa: BLE001 - connection refused/timeout/DNS
        return ApiResponse(status=None, ok=False, error=f"{type(exc).__name__}: {exc}")
