"""P2 admin authentication for configuration updates.

Scope (deliberate and narrow): ONLY ``PUT /api/config`` is protected by this
module. ``GET /api/config`` and every other read endpoint stay open.

``POST /api/readings`` is intentionally left UNAUTHENTICATED so the software
simulator and the ESP8266 hardware keep ingesting telemetry. That is a
SEPARATE, TEMPORARY **device**-security risk (documented in
``docs/SECURITY_P2_ADMIN_AUTH.md``) and must not be confused with this admin
authentication. Device authentication is a future, separately approved change.

Security properties:
- Fail closed: ``ADMIN_API_KEY`` not configured on the server -> HTTP 503
  (configuration updates disabled), checked BEFORE the supplied key.
- Missing ``X-Admin-Key`` header -> HTTP 401; incorrect key -> HTTP 401.
- Constant-time comparison via ``secrets.compare_digest``.
- The configured key is never printed, logged, echoed, or included in any
  response body, error detail, or exception text. Error details below are
  static strings that contain no key material.
"""

import secrets
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

#: Exact header name clients must send (also referenced by the frontend).
ADMIN_KEY_HEADER = "X-Admin-Key"

# auto_error=False: FastAPI must never auto-403/echo; this module raises the
# controlled 401/503 responses itself.
admin_api_key_header = APIKeyHeader(name=ADMIN_KEY_HEADER, auto_error=False)


def require_admin_key(
    api_key: Optional[str] = Security(admin_api_key_header),
) -> None:
    """FastAPI dependency guarding admin-only write endpoints (P2).

    Raises:
        HTTPException 503: ``ADMIN_API_KEY`` is not configured (fail closed).
        HTTPException 401: header missing, or key does not match.
    """
    configured = get_settings().ADMIN_API_KEY

    # 1. Fail closed when the server has no key configured - regardless of
    #    what (if anything) the client sent.
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Configuration updates are disabled: admin authentication "
                "is not configured on the server."
            ),
        )

    # 2. Missing/empty header -> 401.
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Admin key required: missing {ADMIN_KEY_HEADER} header.",
        )

    # 3. Constant-time comparison; detail is a static string (never echoes
    #    the supplied value nor the configured value).
    if not secrets.compare_digest(
        api_key.encode("utf-8"), str(configured).encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin key.",
        )
