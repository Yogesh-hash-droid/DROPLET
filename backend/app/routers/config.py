from fastapi import APIRouter, Depends, Security
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.system_config import SystemConfigResponse, SystemConfigUpdate
from app.security import require_admin_key
from app.services import config_service

router = APIRouter(prefix="/config", tags=["Configuration"])


@router.get(
    "",
    response_model=SystemConfigResponse,
    summary="Get current water quality threshold configuration"
)
def get_config_endpoint(db: Session = Depends(get_db)):
    """Retrieve the active threshold configuration.

    Returns the six legacy thresholds (values preserved) plus the two
    screening score bands introduced by Phase 10 (B1):
    `status_good_min` (default 70.0 - GOOD if score >= this) and
    `status_poor_max` (default 40.0 - POOR if score < this).
    """
    return config_service.get_system_config(db)


@router.put(
    "",
    response_model=SystemConfigResponse,
    summary="Update water quality threshold configuration"
)
def update_config_endpoint(
    config_in: SystemConfigUpdate,
    db: Session = Depends(get_db),
    _admin_key: str | None = Security(require_admin_key),
):
    """
    Update threshold configuration values dynamically.

    P2 admin authentication (app/security.py): requires the ``X-Admin-Key``
    header. Missing/incorrect key -> HTTP 401; server without ``ADMIN_API_KEY``
    configured -> HTTP 503 (fail closed). GET /api/config is unaffected.

    Performs boundary and cross-field consistency checks:
    legacy pairs skip None comparisons, and the screening bands must satisfy
    `0 <= value <= 100` with `status_poor_max < status_good_min`
    (otherwise HTTP 400). All fields are optional - partial updates only
    change the keys that are sent.
    """
    return config_service.update_system_config(db, config_in)
