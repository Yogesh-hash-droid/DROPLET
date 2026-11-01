from datetime import datetime, timezone
import math
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.system_config import SystemConfig
from app.schemas.system_config import SystemConfigUpdate
from app.config import get_settings

settings = get_settings()


def get_system_config(db: Session) -> SystemConfig:
    """
    Retrieve the single system configuration record.
    If it does not exist in the database, automatically provision it with defaults.
    """
    config = db.query(SystemConfig).filter(SystemConfig.id == 1).first()
    if not config:
        config = SystemConfig(
            id=1,
            ph_min=settings.DEFAULT_PH_MIN,
            ph_max=settings.DEFAULT_PH_MAX,
            tds_max=settings.DEFAULT_TDS_MAX,
            turbidity_max=settings.DEFAULT_TURBIDITY_MAX,
            temperature_min=settings.DEFAULT_TEMP_MIN,
            temperature_max=settings.DEFAULT_TEMP_MAX,
            # Phase 10 R-2 = B1: screening bands. Settings values are provisioning
            # fallback only; the DB columns (70.0 / 40.0 defaults) are authoritative.
            status_good_min=settings.DEFAULT_STATUS_GOOD_MIN,
            status_poor_max=settings.DEFAULT_STATUS_POOR_MAX,
            updated_at=datetime.now(timezone.utc)
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def update_system_config(db: Session, update_in: SystemConfigUpdate) -> SystemConfig:
    """
    Update threshold configuration with logical validation.
    """
    config = get_system_config(db)

    # Non-finite values (Infinity / -Infinity / NaN) are never valid
    # configuration values for ANY field: e.g. tds_max=Infinity would silently
    # make every TDS reading PASS, and temperature_min=NaN previously slipped
    # through unconstrained and was stored. HTTP 400 per the config validation
    # design (plan section 3.5 - logical validation in the service, not schema).
    for _field_name, _field_value in update_in.model_dump(exclude_unset=True).items():
        if _field_value is not None and not math.isfinite(float(_field_value)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid configuration: {_field_name} must be a finite number (received {_field_value!r}).",
            )

    # Determine proposed values for cross-field consistency checks
    proposed_ph_min = update_in.ph_min if update_in.ph_min is not None else config.ph_min
    proposed_ph_max = update_in.ph_max if update_in.ph_max is not None else config.ph_max
    proposed_temp_min = update_in.temperature_min if update_in.temperature_min is not None else config.temperature_min
    proposed_temp_max = update_in.temperature_max if update_in.temperature_max is not None else config.temperature_max

    # Cross-field checks skip None comparisons for legacy pairs (legacy pH and
    # temperature thresholds are nullable and remain optional to send).
    if proposed_ph_min is not None and proposed_ph_max is not None and proposed_ph_min >= proposed_ph_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid pH configuration: ph_min ({proposed_ph_min}) must be strictly less than ph_max ({proposed_ph_max})."
        )

    if proposed_temp_min is not None and proposed_temp_max is not None and proposed_temp_min >= proposed_temp_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid temperature configuration: temperature_min ({proposed_temp_min}) must be strictly less than temperature_max ({proposed_temp_max})."
        )

    # Phase 10 R-2 = B1: screening band validation (plan section 3.5).
    # Both range (0-100) and ordering (status_poor_max < status_good_min)
    # violations return HTTP 400 - validated here rather than in the schema so
    # the status code stays 400 instead of a schema-level 422.
    proposed_good_min = (
        update_in.status_good_min if update_in.status_good_min is not None else config.status_good_min
    )
    proposed_poor_max = (
        update_in.status_poor_max if update_in.status_poor_max is not None else config.status_poor_max
    )

    for _band_name, _band_value in (
        ("status_good_min", proposed_good_min),
        ("status_poor_max", proposed_poor_max),
    ):
        if _band_value is None or not (0.0 <= _band_value <= 100.0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid screening band configuration: {_band_name} must be between 0.0 and 100.0."
            )

    if proposed_poor_max >= proposed_good_min:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid screening band configuration: status_poor_max ({proposed_poor_max}) must be strictly less than status_good_min ({proposed_good_min})."
        )

    # Apply valid updates
    for field, value in update_in.model_dump(exclude_unset=True).items():
        setattr(config, field, value)

    config.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(config)
    return config
