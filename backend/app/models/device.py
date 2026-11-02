import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Enum, DateTime
from sqlalchemy.orm import relationship

from app.database import Base


class DeviceSource(str, enum.Enum):
    SIMULATION = "SIMULATION"
    ESP32 = "ESP32"
    ESP8266 = "ESP8266"
    ARDUINO_UNO = "ARDUINO_UNO"


class DeviceStatus(str, enum.Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String(64), unique=True, nullable=False, index=True)
    device_name = Column(String(128), nullable=False)
    source = Column(Enum(DeviceSource), nullable=False, default=DeviceSource.SIMULATION)
    status = Column(Enum(DeviceStatus), nullable=False, default=DeviceStatus.OFFLINE)
    sensor_status = Column(String(32), nullable=False, default="ok")
    wifi_rssi = Column(Integer, nullable=True)
    firmware_version = Column(String(32), nullable=True)
    last_seen = Column(DateTime, nullable=True, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    readings = relationship("WaterReading", back_populates="device", cascade="all, delete-orphan")
