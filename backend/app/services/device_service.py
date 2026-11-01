"""
Device service - Phase 10 (decision D6).

Scope: DEVICE CONNECTIVITY ONLY. ONLINE/OFFLINE is derived purely from telemetry
recency (`last_seen` vs `Settings.DEVICE_OFFLINE_THRESHOLD_SECONDS`).

Sensor health is NOT part of this service: without actual sensor diagnostics,
TDS/turbidity sensor health remains UNKNOWN. A sensor is never reported as
WORKING merely because telemetry arrived, and health is never inferred from a
plausible numeric reading. No diagnostics or firmware requirements are
introduced here (plan sections 3.4 / Step 8, risk R-13).
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.device import Device, DeviceStatus

settings = get_settings()


def compute_connectivity(device: Device, now: Optional[datetime] = None) -> DeviceStatus:
    """
    ONLINE = telemetry received within DEVICE_OFFLINE_THRESHOLD_SECONDS.
    OFFLINE = no telemetry within the threshold (or never seen).

    `last_seen` may come back timezone-naive from the DateTime column; naive
    values are treated as UTC, mirroring how timestamps are written (UTC).
    """
    if device.last_seen is None:
        return DeviceStatus.OFFLINE

    last_seen = device.last_seen
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    reference = now or datetime.now(timezone.utc)
    age_seconds = (reference - last_seen).total_seconds()
    return DeviceStatus.ONLINE if age_seconds <= settings.DEVICE_OFFLINE_THRESHOLD_SECONDS else DeviceStatus.OFFLINE


def _with_live_status(device: Device) -> Device:
    """Attach the computed connectivity status to the returned object.

    The value is computed at read time (risk R-10) and is not persisted by the
    read path; the stored `status` column is refreshed opportunistically by the
    device upsert on the next telemetry POST.
    """
    device.status = compute_connectivity(device)
    return device


def list_devices(db: Session) -> List[Device]:
    """All registered devices, newest registration first (stable id order)."""
    devices = db.query(Device).order_by(Device.id.asc()).all()
    return [_with_live_status(device) for device in devices]


def get_device(db: Session, device_id: str) -> Optional[Device]:
    """Single device by its device_id, or None when unknown."""
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if device is None:
        return None
    return _with_live_status(device)
