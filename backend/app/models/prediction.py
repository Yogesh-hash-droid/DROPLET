import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, Enum, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.database import Base


class PotabilityResult(str, enum.Enum):
    POTABLE = "POTABLE"
    NOT_POTABLE = "NOT POTABLE"


class SafetyStatus(str, enum.Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    UNSAFE = "UNSAFE"


class ScoreMethod(str, enum.Enum):
    """Assessment method discriminator (Phase 10, decision R-3: REQUIRED column).

    FOUR_PARAM_LEGACY  - historical four-parameter assessment. Stored only as the
                         column default NULL for historical rows; historical rows
                         are never backfilled or updated.
    TWO_PARAM_SCREENING - every row written by the new two-sensor pipeline.
    """
    FOUR_PARAM_LEGACY = "FOUR_PARAM_LEGACY"
    TWO_PARAM_SCREENING = "TWO_PARAM_SCREENING"


def _enum_db_values(enum_cls) -> list:
    """
    Persist Python enum *values* (not member names).

    database/schema.sql defines the MySQL columns as
    ENUM('POTABLE', 'NOT POTABLE') and ENUM('SAFE','WARNING','UNSAFE'), so the
    member names (e.g. NOT_POTABLE) must never be written to them.
    """
    return [member.value for member in enum_cls]


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    reading_id = Column(Integer, ForeignKey("water_readings.id", ondelete="CASCADE"), nullable=False, unique=True)
    prediction = Column(
        Enum(PotabilityResult, values_callable=_enum_db_values),
        nullable=True,
        index=True,
    )
    confidence = Column(Float, nullable=True)
    quality_score = Column(Float, nullable=True)
    # Phase 10 decision R-3 (REQUIRED): discriminator between historical
    # four-parameter records (NULL, never backfilled) and new two-parameter
    # screening records (TWO_PARAM_SCREENING). Must exist in MySQL before
    # this code is deployed (database migration is separately gated).
    score_method = Column(
        Enum(ScoreMethod, values_callable=_enum_db_values),
        nullable=True,
        index=True,
    )
    safety_status = Column(
        Enum(SafetyStatus, values_callable=_enum_db_values),
        nullable=False,
        index=True,
    )
    warning_message = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    reading = relationship("WaterReading", back_populates="assessment")
