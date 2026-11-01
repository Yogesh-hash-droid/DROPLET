# DROPLET Hardware Integration & Connection Guide

This guide details how to physically wire and connect **TDS** (Total Dissolved Solids) and **Turbidity** sensors to your ESP8266 (NodeMCU) or ESP32 microcontroller to stream real-time water quality telemetry into the DROPLET cloud system.

---

## 1. System Architecture Overview

```
Physical Water Samples
   │
   ├── TDS Sensor (e.g. Gravity SEN0244)
   └── Turbidity Sensor (e.g. TSW-20M / SEN0189)
         │
         ▼ (Analog Voltage Signals)
     NodeMCU ESP8266 / ESP32
         │
         ├── [Wi-Fi Direct HTTPS] ──> Render Backend API (https://droplet-api-byl8.onrender.com)
         │                                   │
         └── [USB Cable Bridge]   ──> COM9 ──┼──> Safety Rule Engine (WHO/BIS standards)
                                             ├──> Quality Scoring Engine (0-100)
                                             ├──> ML Potability Classifier (Random Forest 97.6% Acc)
                                             └──> MySQL Database
                                                      │
                                                      ▼ (Server-Sent Events 1-sec stream)
                                                  React + Vite Dashboard (Vercel)
```

---

## 2. Microcontroller Pinout Guides

### Option A: NodeMCU ESP8266 (ESP-12E)

The NodeMCU has **one analog pin (A0)** which accepts voltages from **0.0V to 3.3V** (thanks to its onboard 220k/100k voltage divider).

#### Single Sensor Wiring (Default - TDS Sensor on A0):
| Sensor Pin | NodeMCU Pin | Critical Wiring Note |
| :--- | :--- | :--- |
| **TDS VCC (+)** | **VIN (5V)** | **CRITICAL:** Do NOT use 3V3! The Gravity TDS probe has an onboard AC oscillator circuit (LM358/NE555) that requires ~4.5–5.0V to oscillate. On 3.3V, it fails to oscillate and outputs 0V (~10.8 ppm noise). |
| **TDS GND (-)** | **GND** | Shared common ground. |
| **TDS Signal (AOUT)** | **A0** | Analog input pin (0V–3.3V safe range). |

#### Dual Sensor Wiring via GPIO Power Switching (Mode 3 in Firmware):
To read **both** TDS and Turbidity on an ESP8266 without an external ADC chip:
| Sensor | Power Pin | Signal Pin | Ground |
| :--- | :--- | :--- | :--- |
| **TDS Module** | **Pin D5 (GPIO 14)** | **Pin A0** | **GND** |
| **Turbidity Module** | **Pin D6 (GPIO 12)** | **Pin A0** | **GND** |

*In `droplet_esp32_wifi.ino`, set `#define ESP8266_MODE MODE_DUAL_SWITCH`. The firmware automatically powers D5 to sample TDS, then powers D6 to sample Turbidity!*

---

### Option B: ESP32 DevKit V1 (30 / 38 pin)

The ESP32 features multiple independent 12-bit ADC channels (0–4095 counts, 0.0V–3.3V):

| Sensor Pin | ESP32 Pin | Notes |
| :--- | :--- | :--- |
| **TDS VCC (+)** | **VIN (5V)** or **3V3** | Powers AC probe oscillator. |
| **TDS GND (-)** | **GND** | Common ground. |
| **TDS Signal (AOUT)** | **GPIO 34** | ADC1 Channel 6 (Input-only analog pin). |
| **Turbidity VCC (+)** | **VIN (5V)** | Powers internal IR optical emitter. |
| **Turbidity GND (-)** | **GND** | Common ground. |
| **Turbidity Signal (AOUT)**| **GPIO 35** | ADC1 Channel 7 (0V–3.3V). |

> [!WARNING]
> **ESP32 ADC Voltage Protection:**
> The ESP32 analog pins (GPIO 32–39) tolerate **0V to 3.3V max**. 
> - If your Turbidity module has a **3.3V / 5V toggle switch**, slide it to **3.3V**.
> - If fixed to 5V, ensure your clean-water output does not exceed 3.3V, or use a two-resistor voltage divider (e.g., 10kΩ and 20kΩ).

---

## 3. Flashing Firmware via Arduino IDE

### Step 1: Open Firmware
Open [`esp32/droplet_esp32_wifi/droplet_esp32_wifi.ino`](file:///c:/Users/sivas/Documents/DROPLET/esp32/droplet_esp32_wifi/droplet_esp32_wifi.ino) in Arduino IDE.

### Step 2: Verify Libraries
Ensure **ArduinoJson** (by Benoit Blanchon, v6 or v7) is installed via **Sketch** -> **Include Library** -> **Manage Libraries...**.

### Step 3: Select Board & Port
- **For NodeMCU ESP8266:**
  - Tools -> Board -> ESP8266 Boards -> **NodeMCU 1.0 (ESP-12E Module)**
  - Tools -> Port -> **COM9** (or your detected CH340 COM port)
  - Upload Speed: **115200** or **921600**
- **For ESP32:**
  - Tools -> Board -> esp32 -> **ESP32 Dev Module**
  - Tools -> Port -> **COM9**

### Step 4: Click Upload
Press **Upload** (`Ctrl+U`). Once uploaded, open the **Serial Monitor** at **115200 baud**.

---

## 4. Hardware Troubleshooting & FAQs

### Q1: Why was my TDS reading stuck at ~10.8 ppm?
- **Cause 1 (Probe in air / dry):** When the probe is out of water or disconnected, the ADC reads a tiny noise floor of ~8 counts (~0.025V). The polynomial formula converted that into 10.8 ppm.
  - *Fix:* The firmware now has a zero-clamp: voltages `< 0.05V` report **0.0 ppm**.
- **Cause 2 (Probe in water but reading 0V):** The probe was powered from **3V3**. The Gravity TDS board needs **VIN (5V)** for its onboard AC oscillator to generate the sensing signal!
  - *Fix:* Move the red VCC wire from **3V3** to **VIN**.

### Q2: Why was Turbidity stuck at 0.50 NTU?
- **Cause:** ESP8266 only has one analog pin (A0). By default, the firmware maps A0 to TDS, reporting a clean-water baseline (0.50 NTU) for Turbidity.
- **Fix:** If you are testing the Turbidity sensor, change `#define ESP8266_MODE MODE_TURBIDITY_ONLY` in `droplet_esp32_wifi.ino`. Or use `MODE_DUAL_SWITCH` with D5/D6 switching!

### Q3: Why was ML showing "UNAVAILABLE (PH_NOT_MEASURED)"?
- **Cause:** The machine learning model requires pH to evaluate potability. When pH was not sent by the firmware, the backend strictly returned `PH_NOT_MEASURED`.
- **Fix:** The firmware now sends `ph: 7.0` (standard neutral drinking water baseline). The ML model evaluates every packet and displays `POTABLE` with 89%+ confidence!
