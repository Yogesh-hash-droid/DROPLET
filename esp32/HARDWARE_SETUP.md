# DROPLET Hardware Integration & Connection Guide

### Authoritative Setup: ESP8266 NodeMCU + ADS1115 (16-bit ADC) + TDS Meter + Turbidity Sensor

This guide details the physical wiring and firmware configuration for the DROPLET smart water quality monitoring system.

---

## 1. System Architecture Overview

```
Physical Water Samples
   │
   ├── TDS Sensor Meter
   └── Turbidity Optical Sensor
         │
         ▼ (Analog Voltage Signals)
     ADS1115 16-bit ADC Module (I2C: Address 0x48)
         │
         ▼ (I2C: SCL -> D1 / SDA -> D2)
     ESP8266 NodeMCU (1.0 ESP-12E Module)
         │
         └── [Wi-Fi Direct HTTPS] ──> Render Backend API (https://droplet-api-byl8.onrender.com)
                                             │
                                             ├──> Safety Rule Engine (WHO/BIS standards)
                                             ├──> Quality Scoring Engine (0-100)
                                             ├──> ML Potability Classifier (Random Forest 97.6% Acc)
                                             └──> MySQL Database
                                                      │
                                                      ▼ (Server-Sent Events 1-sec stream)
                                                  React + Vite Dashboard (Vercel)
```

---

## 2. Complete Wiring Connections Table

### 1. ESP8266 to ADS1115 (I2C Bus & Power)
| From (NodeMCU) | To (ADS1115) | Wire Color | Notes |
| :--- | :--- | :--- | :--- |
| **ESP 3V (3.3V)** | **ADS V (VDD)** | Red | Powers the ADS1115 ADC with regulated 3.3V. |
| **ESP G (GND)** | **ADS G (GND)** | Black | Common Ground. |
| **ESP G (GND)** | **ADS ADDR** | Black | Grounding ADDR sets the I2C address to **`0x48`**. |
| **ESP D1 (GPIO 5)** | **ADS SCL** | Blue | I2C Clock line. |
| **ESP D2 (GPIO 4)** | **ADS SDA** | Green | I2C Data line. |

### 2. TDS Meter to ADS1115
| From (TDS Module) | To (NodeMCU / ADS) | Wire Color | Notes |
| :--- | :--- | :--- | :--- |
| **TDS Red (+)** | **ESP 3V (3.3V)** | Red | Power supply for TDS oscillator. |
| **TDS Black (-)** | **ESP G (GND)** | Black | Common Ground. |
| **TDS Yellow (A)** | **ADS A0 (AIN0)** | Yellow | Analog signal measured by ADS1115 Channel 0. |

### 3. Turbidity Sensor to ADS1115
| From (Turbidity) | To (NodeMCU / ADS) | Wire Color | Notes |
| :--- | :--- | :--- | :--- |
| **Turbidity V (+)** | **ESP 3V (3.3V)** | Red | Power supply for optical IR sensor. |
| **Turbidity G (-)** | **ESP G (GND)** | Black | Common Ground. |
| **Turbidity Signal**| **ADS A1 (AIN1)** | Purple | Analog signal measured by ADS1115 Channel 1. |

### 4. Pins Left Unconnected
* **ESP A0** (Onboard ADC pin on NodeMCU is left unconnected).
* **ADS ALERT** (Comparator alert pin not required).
* **ADS A2** and **ADS A3** (Channels 2 and 3 reserved for future pH or temperature sensors).

---

## 3. Quick Checks & Safety Guidelines

1. **Slide Switch on Turbidity Board:**
   * Make sure the physical slide switch on the blue Turbidity adapter board is set to **`A`** (Analog), **NOT** `D` (Digital).
2. **Common Ground:**
   * All ground lines (`ESP G`, `ADS G`, `TDS Black`, and `Turbidity G`) must connect to a common ground rail.
3. **Power ADS1115 only from 3.3V:**
   * Never connect the ADS1115 to `VIN` or 5V; running at 3.3V guarantees the analog inputs remain safely within the ESP8266 3.3V logic range.
4. **Boot Pin Protection:**
   * Keep pins `D3`, `D4`, and `D8` free because they control ESP8266 boot modes.

---

## 4. Flashing the Firmware

1. Open [`esp32/droplet_esp32_wifi/droplet_esp32_wifi.ino`](file:///c:/Users/sivas/Documents/DROPLET/esp32/droplet_esp32_wifi/droplet_esp32_wifi.ino) in Arduino IDE.
2. Select **Tools** -> **Board** -> **NodeMCU 1.0 (ESP-12E Module)**.
3. Select **Tools** -> **Port** -> **COM9**.
4. Click **Upload** (`Ctrl + U`).
5. Open the **Serial Monitor** at **115200 baud**:
   * You will see:
     ```text
     [I2C] SUCCESS: ADS1115 detected at address 0x48!
     [WiFi] Connected successfully!
     [ADS1115] TDS (A0): 0.812 V -> 238.4 ppm  |  Turbidity (A1): 2.910 V -> 0.50 NTU
     [HTTP POST] Code 201 (182ms) -> {"device_id":"ESP8266-WATER-001",...}
     ```
6. Open your dashboard at **`https://droplet-cyan.vercel.app`** to watch both sensors update live every second!
