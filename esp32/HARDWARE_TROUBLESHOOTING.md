# DROPLET Hardware Troubleshooting & Diagnostic Guide

### NodeMCU ESP8266 + ADS1115 (16-bit ADC) + TDS & Turbidity Sensors

---

## 1. Text Wiring Diagram

```
+-----------------------------------------------------------------------------------+
|                              ESP8266 NodeMCU 1.0                                  |
|                                                                                   |
|  [3V3]   [GND]   [D1/GPIO5]   [D2/GPIO4]                                          |
|    |       |         |            |                                               |
+----+-------+---------+------------+-----------------------------------------------+
     |       |         |            |
     |       |      (Blue)       (Green)
   (Red)  (Black)      |            |
     |       |         |            |
     |       +-------------------+  |
     |       |                   |  |
     v       v                   v  v
+----+-------+---------+---------+--+-----------------------------------------------+
|   VDD     GND      ADDR       SCL SDA        A0       A1      A2      A3   ALERT  |
|                                                                                   |
|                        ADS1115 16-bit I2C ADC Module                              |
+-----------------------------------------------+--------+--------------------------+
                                                ^        ^
                                                |        |
                         (Yellow Signal Wire) --+        | (Purple Signal Wire)
                                                         |
                 +---------------------------+           |
                 |      TDS Meter Probe      |           |
                 |  VCC (+)  --> ESP 3V3     |           |
                 |  GND (-)  --> ESP GND     |           |
                 |  Signal   --> ADS1115 A0  +-----------+
                 +---------------------------+           |
                                                         |
                 +---------------------------------------+--+
                 |       Turbidity Optical Sensor Board     |
                 |  VCC (V)  --> ESP 3V3                    |
                 |  GND (G)  --> ESP GND                    |
                 |  Signal   --> ADS1115 A1                 |
                 |  Switch   --> Set to 'A' (Analog Mode)   |
                 +------------------------------------------+
```

---

## 2. Pinout & Interconnection Summary

| Module | Pin | Connects To | Wire Color | Function / Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **ADS1115** | `VDD` | NodeMCU `3V3` | Red | Regulated 3.3V Power (Do NOT connect to 5V/VIN) |
| **ADS1115** | `GND` | NodeMCU `GND` | Black | Common Ground |
| **ADS1115** | `ADDR`| NodeMCU `GND` | Black | Sets I2C Address to **`0x48`** |
| **ADS1115** | `SCL` | NodeMCU `D1` (GPIO 5) | Blue | I2C Bus Clock |
| **ADS1115** | `SDA` | NodeMCU `D2` (GPIO 4) | Green | I2C Bus Data |
| **ADS1115** | `A0`  | TDS Meter Signal | Yellow | Channel 0: Total Dissolved Solids Voltage |
| **ADS1115** | `A1`  | Turbidity Signal | Purple | Channel 1: Optical Turbidity Voltage |
| **TDS Meter** | `VCC` | NodeMCU `3V3` | Red | 3.3V DC Power |
| **TDS Meter** | `GND` | NodeMCU `GND` | Black | Ground Return |
| **Turbidity** | `VCC` | NodeMCU `3V3` | Red | 3.3V DC Power |
| **Turbidity** | `GND` | NodeMCU `GND` | Black | Ground Return |
| **Turbidity** | Slide Switch | **'A' Position** | N/A | **Analog Output** mode (not 'D' digital) |

---

## 3. ADS1115 I2C Address Map (ADDR Pin Configuration)

The ADS1115 hardware address is configured by the electrical connection of the **ADDR** pin:

| ADDR Connection | I2C Address (Hex) | Binary | Notes |
| :--- | :--- | :--- | :--- |
| **GND** (Current Config) | **`0x48`** | `1001000` | Standard default address used by DROPLET |
| **VDD (3.3V)** | **`0x49`** | `1001001` | Alternate address 1 |
| **SDA** | **`0x4A`** | `1001010` | Alternate address 2 |
| **SCL** | **`0x4B`** | `1001011` | Alternate address 3 |

> **IMPORTANT:** If the ADDR pin is floating (unconnected), the ADS1115 I2C address will float unpredictably, causing intermittent communication failures. **ADDR must be physically tied to GND.**

---

## 4. Hardware Checklist: Root Cause Troubleshooting

If the Serial Monitor displays `[ADS1115] ERROR: No ACK at 0x48! Verify wiring`:

- [ ] **1. Header Pins Soldered:**
  Inspect the ADS1115 module. Header pins **MUST be soldered** to the PCB pads. Loose push-fit pins on breadboards do not make electrical contact.
- [ ] **2. Measure VDD Voltage with a Multimeter:**
  Measure DC voltage between ADS1115 `VDD` and `GND`. You should read **3.28V – 3.32V**. If 0V, verify the red jumper wire. **Do NOT connect VDD to 5V/VIN** (the ESP8266 GPIO pins are not 5V-tolerant).
- [ ] **3. ADDR Pin Tied to GND:**
  Verify that the `ADDR` pin is firmly plugged into the common Ground rail. Do not leave ADDR floating.
- [ ] **4. Check SDA / SCL Pin Assignment:**
  On ESP8266 NodeMCU:
  - `D1` = `GPIO 5` = **SCL**
  - `D2` = `GPIO 4` = **SDA**
  Confirm wires are NOT swapped (SDA to D2, SCL to D1).
- [ ] **5. Replace Jumper Wires:**
  DuPont breadboard wires frequently suffer from internal fractures or loose crimps. Swap the four I2C wires (3V3, GND, SCL, SDA) with fresh tested jumpers.
- [ ] **6. Turbidity Board Switch on 'A':**
  The small blue adapter board for the turbidity sensor has a 2-position slide switch labeled `A` and `D`. It **must be set to `A`** (Analog). In `D` position, it outputs a digital 0/1 trigger that corrupts analog readings.
- [ ] **7. Wet Probe Testing:**
  TDS probe dry in air reads **0.000V** (physical open circuit). Submerge probe in tap water (~150-300 ppm) or salted water to confirm analog deflection.
