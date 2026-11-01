from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, DateTime, text

from app.database import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, default=1)
    # Legacy four-parameter thresholds (values preserved; nullable so historical
    # configuration rows remain valid under the two-sensor scope).
    ph_min = Column(Float, nullable=True, default=6.5, comment="legacy column; NULL = not configured")
    ph_max = Column(Float, nullable=True, default=8.5, comment="legacy column; NULL = not configured")
    tds_max = Column(Float, nullable=False, default=500.0)
    turbidity_max = Column(Float, nullable=False, default=5.0)
    temperature_min = Column(Float, nullable=True, default=10.0, comment="legacy column; NULL = not configured")
    temperature_max = Column(Float, nullable=True, default=35.0, comment="legacy column; NULL = not configured")
    # Phase 10 decision R-2 = B1 (FINAL): database-backed screening score bands.
    # Column defaults match the migration defaults; existing rows receive these
    # values without losing any existing configuration values.
    # GOOD: score >= status_good_min; POOR: score < status_poor_max; else MODERATE.
    status_good_min = Column(Float, nullable=False, default=70.0, server_default=text("70.0"))
    status_poor_max = Column(Float, nullable=False, default=40.0, server_default=text("40.0"))
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
