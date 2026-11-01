from app.models.device import Device, DeviceSource, DeviceStatus
from app.models.water_reading import WaterReading
from app.models.prediction import Prediction, PotabilityResult, SafetyStatus
from app.models.system_config import SystemConfig

__all__ = [
    "Device",
    "DeviceSource",
    "DeviceStatus",
    "WaterReading",
    "Prediction",
    "PotabilityResult",
    "SafetyStatus",
    "SystemConfig",
]
