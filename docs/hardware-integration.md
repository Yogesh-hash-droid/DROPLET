# Hardware Integration Guide (ESP32)

## Overview
This document outlines the transition path from the current software simulation environment to physical ESP32 hardware sensors.

## Seamless Transition
The REST API endpoint `POST /api/readings` is built to ingest JSON payloads identical to what the ESP32 will transmit. The frontend dashboard automatically recognizes the `source` field:
- `SIMULATION` displays **SIMULATION MODE**.
- `ESP32` displays **REAL HARDWARE MODE**.

## Target Payload
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

## Planned Sensor Suite
1. **Analog pH Sensor Kit** (e.g., SEN0161 / PH-4502C) connected to ADC Pin (e.g., GPIO 34).
2. **Analog TDS Sensor Module** (e.g., Gravity TDS / SEN0244) connected to ADC Pin (e.g., GPIO 35).
3. **Turbidity Sensor Module** (e.g., TSW-20M / SEN0189) connected to ADC Pin (e.g., GPIO 32).
4. **DS18B20 Waterproof OneWire Temperature Sensor** connected to OneWire bus (e.g., GPIO 4) with 4.7kΩ pullup.

## ESP32 Wi-Fi & HTTP Client Flow
```cpp
// Pseudocode outline for Phase 9
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

void sendReading(float ph, float tds, float turbidity, float temp) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin("http://<server-ip>:8000/api/readings");
    http.addHeader("Content-Type", "application/json");

    StaticJsonDocument<256> doc;
    doc["device_id"] = "ESP32-WATER-001";
    doc["ph"] = ph;
    doc["tds"] = tds;
    doc["turbidity"] = turbidity;
    doc["temperature"] = temp;
    doc["source"] = "ESP32";

    String payload;
    serializeJson(doc, payload);
    int httpResponseCode = http.POST(payload);
    http.end();
  }
}
```
No frontend or database restructuring is needed when flashing and booting physical hardware.
