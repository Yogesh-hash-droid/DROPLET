from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, String, Enum, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.device import DeviceSource


class WaterReading(Base):
    __tablename__ = "water_readings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(64), ForeignKey("devices.device_id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False, index=True)
    ph = Column(Float, nullable=True, comment="NULL = not measured")
    tds = Column(Float, nullable=True, comment="NULL = sensor fault / not measured")
    turbidity = Column(Float, nullable=True, comment="NULL = sensor fault / not measured")
    temperature = Column(Float, nullable=True, comment="NULL = not measured")
    sensor_status = Column(String(32), nullable=False, default="ok")
    wifi_rssi = Column(Integer, nullable=True)
    uptime = Column(Integer, nullable=True)
    firmware_version = Column(String(32), nullable=True)
    source = Column(Enum(DeviceSource), nullable=False, default=DeviceSource.SIMULATION, index=True)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    device = relationship("Device", back_populates="readings")
    assessment = relationship("Prediction", back_populates="reading", uselist=False, cascade="all, delete-orphan")

    @property
    def prediction(self) -> str | None:
        if self.assessment and self.assessment.prediction:
            return self.assessment.prediction.value
        return None

    @property
    def confidence(self) -> float | None:
        return self.assessment.confidence if self.assessment else None

    @property
    def quality_score(self) -> float | None:
        return self.assessment.quality_score if self.assessment else None

    @property
    def score_method(self) -> str | None:
        if self.assessment and self.assessment.score_method:
            return self.assessment.score_method.value
        return None

    @property
    def safety_status(self) -> str | None:
        if self.assessment and self.assessment.safety_status:
            return self.assessment.safety_status.value
        return None

    @property
    def warning_message(self) -> str | None:
        return self.assessment.warning_message if self.assessment else None
