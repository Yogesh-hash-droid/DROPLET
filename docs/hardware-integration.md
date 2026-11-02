# Hardware Integration Guide

> **⚠️ Educational Prototype Disclaimer**: This system is an educational prototype and does not replace certified laboratory water testing. TDS readings are NOT temperature-compensated.

## 1. Primary Hardware: Arduino Uno (ATmega328P)

The current hardware platform uses a plain Arduino Uno with an analog TDS sensor and an analog turbidity sensor. It has no Wi-Fi, so it transmits readings over USB Serial (9600 baud) to a Python gateway (`arduino/gateway.py`), which pushes JSON payloads to the cloud API.

### Authoritative Wiring Table

| From | To | Notes |
|------|----|-------|
| TDS red (+) | Uno D7 (digital pin 7) | Powered only while reading; 5V is an acceptable fallback |
| TDS black (-) | Uno GND | Common ground |
| TDS yellow (A) | Uno A0 | Analog input |
| Turbidity V | Uno 5V | Continuous 5V power |
| Turbidity G | Uno GND | Common ground |
| Turbidity signal | Uno A1 | Analog input |

*No I2C wires are used (no SDA, SCL, ADDR). The Uno ADC is 10-bit at ~5V. The firmware measures the real 5V rail itself, averages samples, and stores EEPROM calibration.*

### Target Payload (`source: "ARDUINO_UNO"`)
```json
{
  "device_id": "UNO-001",
  "tds": 250.0,
  "turbidity": 3.5,
  "source": "ARDUINO_UNO"
}
```
*Note: `ph` and `temperature` are omitted / stored as null. The system performs two-parameter safety checks and reports ML potability as UNAVAILABLE (`PH_NOT_MEASURED`) without fabricating numbers.*

### Serial Commands for Calibration (9600 baud, Newline)
- `tds <ppm>`: Calibrate TDS with a known standard (e.g. `tds 500`)
- `turb <ntu>`: Calibrate turbidity with a known NTU standard (e.g. `turb 4.5`)
- `show`: Display current calibration values in EEPROM
- `reset`: Reset calibration to default values
- `clear`: Clear stored calibration

### USB-to-Cloud Gateway
The Python gateway script (`arduino/gateway.py`) bridges USB Serial to HTTP POST:
```bash
cd arduino
pip install -r ../backend/requirements.txt  # Or: pip install pyserial requests python-dotenv
python gateway.py
```

---

## 2. Legacy Hardware (ESP32 / ESP8266)

The system maintains 100% backward compatibility with 4-sensor hardware payloads containing `ph` and `temperature`:

```json
{
  "device_id": "ESP32-WATER-001",
  "ph": 7.20,
  "tds": 250.0,
  "turbidity": 2.10,
  "temperature": 27.50,
  "source": "ESP32"
}
```

Legacy firmware is archived under `esp32/archive/` for historical reference.
