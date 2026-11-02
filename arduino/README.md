# DROPLET — Arduino Uno Firmware

> **⚠️ Educational Prototype Disclaimer**
> This system is for learning and demonstration purposes only. TDS readings
> are NOT temperature-compensated. This device does NOT certify water as safe
> or potable. Always use accredited laboratory testing for water safety decisions.

## Hardware

### Wiring Table (authoritative — match this exactly)

| From | To | Notes |
|------|----|-------|
| TDS red (+) | Uno **D7** (digital pin 7) | Powers TDS module only while reading |
| TDS black (−) | Uno **GND** | |
| TDS yellow (A) | Uno **A0** | Analog signal input |
| Turbidity V | Uno **5V** | Always-on power |
| Turbidity G | Uno **GND** | |
| Turbidity signal | Uno **A1** | Analog signal input |

**No I2C wires are used. No SDA, SCL, or ADDR pins are connected.**

The Uno's ADC is 10-bit at ~5V (4.88 mV/step). The firmware measures the
actual 5V rail voltage for accurate conversion.

---

## Arduino IDE Setup

1. Board: **Arduino Uno**
2. Port: whichever COM port appears when you plug in the Uno
3. Baud rate: **9600** in Serial Monitor (line ending: **Newline**)

---

## Firmware: `water_quality_uno_final.ino`

Place `water_quality_uno_final.ino` in this directory.
The firmware prints one JSON line per valid reading over USB Serial at 9600 baud:

```json
{"device_id":"UNO-001","tds":250.0,"turbidity":3.5,"source":"ARDUINO_UNO"}
```

### Calibration Serial Commands

Open the Arduino IDE Serial Monitor at 9600 baud (Newline line ending) and type:

| Command | Effect |
|---------|--------|
| `tds <ppm>` | Calibrate TDS with a known standard (e.g. `tds 500`) |
| `turb <ntu>` | Calibrate turbidity with a known NTU standard (e.g. `turb 4.5`) |
| `show` | Print current calibration values stored in EEPROM |
| `reset` | Reset calibration to factory defaults |
| `clear` | Clear all stored calibration from EEPROM |

Calibration is saved to EEPROM and persists across power cycles.

---

## Gateway Script: `gateway.py`

The gateway reads the USB serial output and forwards readings to the cloud backend.

### Install dependencies

```bash
pip install pyserial requests python-dotenv
```

### Configure

```bash
cd arduino
cp .env.example .env
# Edit .env and set your COM port and API URL:
# SERIAL_PORT=COM5   (or /dev/ttyUSB0 on Linux)
# API_URL=https://droplet-api-byl8.onrender.com
```

### Run

```bash
python arduino/gateway.py
```

The gateway:
- Auto-detects your Arduino Uno's COM port if `SERIAL_PORT` is not set
- Validates every JSON line (skips bad/incomplete lines, never sends fake values)
- Retries failed HTTP requests with exponential backoff
- Automatically reconnects if the USB cable is unplugged and replugged
- Stops cleanly on **Ctrl+C**

---

## Data Path

```
Arduino Uno (USB 9600 baud)
        |
        ▼
    gateway.py
        |  POST /api/readings (JSON)
        ▼
Render Backend (https://droplet-api-byl8.onrender.com)
        |
        ▼
Vercel Dashboard (https://droplet-cyan.vercel.app/)
```

---

## Legacy Firmware (archived)

The old ESP8266 + ADS1115 firmware lives in `esp32/archive/` for reference.
It is not the active firmware and is not required for the Arduino Uno setup.
