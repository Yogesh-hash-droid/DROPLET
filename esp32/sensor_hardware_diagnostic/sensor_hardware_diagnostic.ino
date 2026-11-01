/*
 * DROPLET - Instant Hardware & Sensor Diagnostic Tool
 * Works on ESP8266 (NodeMCU) & ESP32 DevKit
 *
 * PURPOSE:
 * Use this lightweight sketch to test your physical TDS and Turbidity
 * sensors over USB Serial (115200 baud) WITHOUT needing Wi-Fi or cloud.
 *
 * INSTRUCTIONS:
 * 1. Open this sketch in Arduino IDE.
 * 2. Select your Board (NodeMCU 1.0 or ESP32) and Port (COM9).
 * 3. Upload and open Serial Monitor at 115200 baud.
 * 4. Dip your probe in water / clean water / dirty water.
 *    Watch the Raw ADC count and Voltage change live in real-time!
 */

#if defined(ESP32)
  #define PIN_ADC_TDS        34
  #define PIN_ADC_TURB       35
  #define ADC_MAX            4095.0f
  #define VREF               3.3f
#elif defined(ESP8266)
  #define PIN_ADC_A0         A0
  #define PIN_D5_SWITCH      14 // D5 (GPIO 14)
  #define PIN_D6_SWITCH      12 // D6 (GPIO 12)
  #define ADC_MAX            1023.0f
  #define VREF               3.3f
#endif

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println(F("\n========================================================"));
  Serial.println(F("       DROPLET - Real-Time Sensor Hardware Diagnostic     "));
  Serial.println(F("========================================================"));
#if defined(ESP32)
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  pinMode(PIN_ADC_TDS, INPUT);
  pinMode(PIN_ADC_TURB, INPUT);
  Serial.println(F("Platform: ESP32 (Dual ADC: GPIO 34 for TDS, GPIO 35 for Turbidity)"));
#elif defined(ESP8266)
  pinMode(PIN_ADC_A0, INPUT);
  Serial.println(F("Platform: NodeMCU ESP8266 (Single Analog Pin: A0)"));
  Serial.println(F("Tip: Connect Sensor VCC to 3V3 (or VU) and Signal to A0"));
#endif
  Serial.println(F("========================================================\n"));
}

void printBar(float voltage, float maxV) {
  int width = 25;
  int filled = (int)((voltage / maxV) * width);
  filled = constrain(filled, 0, width);
  Serial.print(F(" ["));
  for (int i = 0; i < width; i++) {
    if (i < filled) Serial.print(F("="));
    else Serial.print(F(" "));
  }
  Serial.print(F("] "));
}

void loop() {
#if defined(ESP8266)
  // Read A0 on NodeMCU
  long sum = 0;
  for (int i = 0; i < 20; i++) {
    sum += analogRead(PIN_ADC_A0);
    delay(2);
  }
  int rawADC = (int)(sum / 20);
  float voltage = ((float)rawADC / ADC_MAX) * VREF;

  Serial.printf("A0 RAW: %4d / 1023 | Voltage: %.3f V", rawADC, voltage);
  printBar(voltage, VREF);

  if (voltage < 0.05f) {
    Serial.println(F("-> DRY / DISCONNECTED (0.0 ppm)"));
  } else if (voltage >= 0.05f && voltage < 1.8f) {
    // Standard TDS calculation
    float compV = voltage / (1.0f + 0.02f * (25.0f - 25.0f));
    float tds = (133.42f * powf(compV, 3) - 255.86f * powf(compV, 2) + 857.39f * compV) * 0.5f;
    Serial.printf("-> TDS SENSOR ACTIVE: ~%.1f ppm\n", tds);
  } else if (voltage >= 2.0f && voltage <= 3.3f) {
    // Turbidity calculation
    float ntu = 0.5f;
    if (voltage < (VREF * 0.75f)) {
      ntu = -1120.4f * powf(voltage, 2) + 5742.3f * voltage - 4352.9f;
    }
    Serial.printf("-> TURBIDITY ACTIVE: ~%.2f NTU (Clear/Normal)\n", max(ntu, 0.0f));
  } else {
    Serial.println(F("-> HIGH VOLTAGE"));
  }

#elif defined(ESP32)
  int rawTds = analogRead(PIN_ADC_TDS);
  int rawTurb = analogRead(PIN_ADC_TURB);
  float vTds = ((float)rawTds / ADC_MAX) * VREF;
  float vTurb = ((float)rawTurb / ADC_MAX) * VREF;

  Serial.printf("TDS (GPIO 34): %4d (%.3fV) | Turbidity (GPIO 35): %4d (%.3fV)\n",
                rawTds, vTds, rawTurb, vTurb);
#endif

  delay(500); // Sample twice per second for quick visual feedback
}
