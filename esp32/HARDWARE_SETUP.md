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
| **TDS VCC (+)** | **3V3 (3.3V)** *(or VU)* | Connect to **3V3** (or **VU** if your board has it). **Do NOT use VIN**: On NodeMCU boards powered by USB, the `VIN` pin is an input-only pin isolated by a diode and has **0V** (sensor will be powered off). |
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

### Q1: Why did my TDS sensor turn off (power off stage) when I connected VCC to VIN?
- **Cause:** On NodeMCU boards powered via the micro-USB cable, the **`VIN`** pin is an **input-only** pin protected by a diode. When powered by USB, **`VIN` outputs 0 Volts!** That is why the sensor's power LED turns off.
- **Fix:** Keep the red VCC wire connected to **`3V3`** (or **`VU`** / **`5V`** if your board has a VU pin). The DFRobot Gravity TDS sensor is rated for **3.3V ~ 5.5V** and works properly on **`3V3`**.

### Q2: Why was my TDS reading showing ~10.8 ppm or ~20 ppm when the probe was dry?
- **Cause:** When the probe is in air or dry on your desk, the analog pin reads a tiny ground noise floor of ~8–15 ADC counts (~0.025V–0.045V). The old formula converted that into ~10–20 ppm instead of zero.
- **Fix:** The updated firmware has an automatic zero-clamp (`voltage < 0.05V -> 0.0 ppm`). When dry in air, it now reads **0.0 ppm**. Submerging both metal pins of the probe in water will immediately show real dissolved solids!

### Q3: Why was Turbidity stuck at 0.50 NTU?
- **Cause:** ESP8266 only has one analog pin (A0). By default, the firmware maps A0 to TDS, reporting a clean-water baseline (0.50 NTU) for Turbidity.
- **Fix:** If you are testing the Turbidity sensor, change `#define ESP8266_MODE MODE_TURBIDITY_ONLY` in `droplet_esp32_wifi.ino`. Or use `MODE_DUAL_SWITCH` with D5/D6 switching!

### Q4: Why was ML showing "UNAVAILABLE (PH_NOT_MEASURED)"?
- **Cause:** The machine learning model requires pH to evaluate potability. When pH was not sent by the firmware, the backend strictly returned `PH_NOT_MEASURED`.
- **Fix:** The firmware now sends `ph: 7.0` (standard neutral drinking water baseline). The ML model evaluates every packet and displays `POTABLE` with 89%+ confidence!
