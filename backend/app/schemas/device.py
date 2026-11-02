from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, ConfigDict


class DeviceResponse(BaseModel):
    id: int
    device_id: str
    device_name: str
    source: Literal["SIMULATION", "ESP32", "ESP8266", "ARDUINO_UNO"]
    status: Literal["ONLINE", "OFFLINE"]
    last_seen: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

