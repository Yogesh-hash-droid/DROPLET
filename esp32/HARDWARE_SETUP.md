# DROPLET Hardware Integration & Connection Guide

This guide details how to physically wire and connect **TDS** and **Turbidity** sensors to your software system to ingest real-time water quality telemetry.

---

## 1. System Architecture Overview

```
Physical Water Samples
   │
   ├── TDS Sensor (e.g. Gravity SEN0244)
   └── Turbidity Sensor (e.g. TSW-20M / SEN0189)
         │
         ▼ (Analog Voltage Signals)
     ESP32 Microcontroller
         │
         ├── [Option A: Wi-Fi Mode] ──> Wi-Fi HTTP POST ──┐
         │                                               │
         └── [Option B: USB Cable]  ──> Serial Bridge ───┼──> FastAPI Backend (:8000)
                                                         │        │
                                                         │        ├── Safety Rule Engine
                                                         │        ├── Quality Scoring Engine
                                                         │        └── MySQL Database
                                                         │                 │
                                                         └───────────────> React + Vite Dashboard
                                                                           (Live "ESP32" telemetry)
```

---

## 2. Hardware Bill of Materials (BOM)

| Component | Recommendation | Function |
| :--- | :--- | :--- |
| **Microcontroller** | ESP32 DevKit V1 (30 or 38 pin) / ESP8266 | Reads analog voltages, processes readings, sends telemetry |
| **TDS Sensor** | DFRobot Gravity Analog TDS Sensor (SEN0244) | Measures Total Dissolved Solids (0 - 1000 ppm) |
| **Turbidity Sensor**| DFRobot Turbidity Sensor (SEN0189 / TSW-20M) | Measures optical suspended particles (0 - 3000 NTU) |
| **Connecting Wires**| Jumper wires (Female-to-Male / Male-to-Male) | Signal and power connections |
| **Power Supply** | Micro-USB Cable (connected to PC or 5V adapter) | Powers ESP32 and sensor modules |

---

## 3. Circuit Wiring & Pinout Guide

### Pinout Connection Table

| Sensor Pin | ESP32 Pin | Notes / Safety Guidelines |
| :--- | :--- | :--- |
| **TDS VCC (+)** | **3.3V** | ESP32 outputs 3.3V power (operates accurately without exceeding ADC limit). |
| **TDS GND (-)** | **GND** | Shared common ground. |
| **TDS Signal (AOUT)** | **GPIO 34** | ADC1 Channel 6 (Input-only analog pin). |
| **Turbidity VCC (+)** | **5V (VIN)** | Most optical turbidity modules require 5V to power internal IR LED. |
| **Turbidity GND (-)** | **GND** | Shared common ground. |
| **Turbidity Signal (AOUT)** | **GPIO 35** | ADC1 Channel 7 (See voltage note below). |

> [!WARNING]
> **ESP32 ADC Voltage Protection:**
> The ESP32 analog pins (GPIO 32 - 39) only tolerate **0V to 3.3V**. 
> - If your Turbidity module has a **3.3V / 5V toggle switch**, slide it to **3.3V**.
> - If it is fixed to 5V, use a simple two-resistor voltage divider (e.g., 10kΩ and 20kΩ) or ensure your analog signal does not exceed 3.3V.

---

## 4. Connection Method A: Direct Wi-Fi HTTP Streaming (Recommended)

In this mode, the ESP32 connects directly to your local Wi-Fi router and sends HTTP POST requests to your computer's local IP address.

### Step 1: Open Firmware in Arduino IDE
1. Open the provided sketch: [`esp32/droplet_esp32_wifi.ino`](file:///c:/Users/sivas/Documents/DROPLET/esp32/droplet_esp32_wifi.ino).
2. Install the required Arduino library:
   - In Arduino IDE, go to **Sketch** -> **Include Library** -> **Manage Libraries...**
   - Search for **ArduinoJson** (by Benoit Blanchon, v6.x or v7.x) and install it.

### Step 2: Configure Credentials
In `droplet_esp32_wifi.ino`, update lines 18-24:
```cpp
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Your computer's local IPv4 address (Detected on your Wi-Fi interface):
const char* BACKEND_URL   = "http://192.168.1.4:8000/api/readings";
```

### Step 3: Flash the ESP32
1. Select Board: **ESP32 Dev Module** (under Tools -> Board -> esp32).
2. Select Port: **COM9** (or detected COM port).
3. Click **Upload**.
4. Open the **Serial Monitor** at **115200 baud** to see connection confirmations and outgoing JSON payloads.

---

## 5. Connection Method B: Direct USB Serial Cable Bridge

If you don't have Wi-Fi access or want instant plug-and-play over USB cable:

### Step 1: Flash Serial Firmware
1. Open [`esp32/droplet_serial_arduino.ino`](file:///c:/Users/sivas/Documents/DROPLET/esp32/droplet_serial_arduino.ino) in Arduino IDE.
2. Select your board (ESP32, ESP8266, or Arduino Uno/Nano).
3. Select port (e.g., **COM9**).
4. Click **Upload**.
5. Close the Arduino Serial Monitor once flashed so the port is free.

### Step 2: Launch the Python Telemetry Bridge
Run the automated bridge script in your terminal:
```powershell
# From the project root (c:\Users\sivas\Documents\DROPLET)
python esp32/serial_to_api_bridge.py --port COM9 --baud 115200
```
The bridge automatically reads live sensor JSON packets from `COM9` and forwards them to the DROPLET backend!

---

## 6. End-to-End Verification Checklist

1. **Start Backend Server**:
   ```powershell
   cd backend
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
   *(Note `--host 0.0.0.0` ensures the ESP32 on your Wi-Fi network can reach the server).*

2. **Start Frontend Dashboard**:
   ```powershell
   cd frontend
   npm run dev
   ```
   Open `http://localhost:5173`.

3. **Verify Real-Time Hardware Mode**:
   - The dashboard top banner switches from `SIMULATION MODE` to **`REAL HARDWARE MODE (ESP32)`** with a green badge.
   - The TDS card shows live parts-per-million (ppm) readings.
   - The Turbidity card shows live nephelometric turbidity units (NTU).
   - The Parameter Rule Check evaluates live readings against WHO/operational thresholds (PASS/WARNING/FAIL).
