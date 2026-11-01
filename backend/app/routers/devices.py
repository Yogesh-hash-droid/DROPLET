"""
Device endpoints - Phase 10 (decision D6): DEVICE CONNECTIVITY ONLY.

The responses expose connection recency (ONLINE/OFFLINE) and nothing about
sensor condition. Sensor health stays UNKNOWN without actual diagnostics and
is deliberately NOT exposed here: telemetry arrival or a plausible reading is
not evidence that a sensor works (plan sections 3.4 / Step 8, risk R-13).
GET /api/statistics is deferred (D6).
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.device import Device
from app.schemas.device import DeviceResponse
from app.services import device_service

router = APIRouter(prefix="/devices", tags=["Devices"])


def _to_response(device: Device) -> DeviceResponse:
    return DeviceResponse(
        id=device.id,
        device_id=device.device_id,
        device_name=device.device_name,
        source=device.source.value,
        status=device.status.value,
        last_seen=device.last_seen,
        created_at=device.created_at,
    )


@router.get(
    "",
    response_model=List[DeviceResponse],
    summary="List registered devices (connectivity status only)",
)
def list_devices_endpoint(db: Session = Depends(get_db)):
    """
    Return every device with its live **connectivity** status:
    ONLINE = telemetry received within `DEVICE_OFFLINE_THRESHOLD_SECONDS`,
    OFFLINE otherwise.

    This status measures connectivity ONLY and makes no sensor-health claim.
    """
    return [_to_response(device) for device in device_service.list_devices(db)]


@router.get(
    "/{device_id}",
    response_model=DeviceResponse,
    summary="Retrieve a single device (connectivity status only)",
)
def get_device_endpoint(device_id: str, db: Session = Depends(get_db)):
    """Return one device by `device_id`, or 404 when unknown.

    Same scope: connectivity only, no sensor-health claim.
    """
    device = device_service.get_device(db, device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found.",
        )
    return _to_response(device)
