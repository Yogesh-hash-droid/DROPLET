/*
 * DROPLET - Smart Water Quality Monitoring System
 * Serial Telemetry Firmware (Arduino Uno / Nano / ESP32 / ESP8266)
 *
 * Reads physical TDS and Turbidity sensors and prints clean JSON to Serial.
 * Used with `serial_to_api_bridge.py` to stream hardware readings directly
 * into the DROPLET backend via USB Cable (e.g., COM9).
 *
 * Pinout:
 * - TDS Sensor: Analog Pin A0 (or GPIO 34 on ESP32)
 * - Turbidity Sensor: Analog Pin A1 (or GPIO 35 on ESP32)
 */

#if defined(ESP32)
  #define TDS_PIN        34
  #define TURBIDITY_PIN  35
  #define VREF           3.3
  #define ADC_MAX        4095.0
  #define SOURCE_TAG     "ESP32"
#elif defined(ESP8266)
  #define TDS_PIN        A0
  #define TURBIDITY_PIN  A0
  #define VREF           3.3
  #define ADC_MAX        1023.0
  #define SOURCE_TAG     "ESP8266"
#else // Standard Arduino Uno / Nano (5V)
  #define TDS_PIN        A0
  #define TURBIDITY_PIN  A1
  #define VREF           5.0
  #define ADC_MAX        1023.0
  #define SOURCE_TAG     "ESP32" // Identified as hardware in DROPLET
#endif

#define SAMPLES 30
const float DEFAULT_TEMPERATURE = 25.0; // °C

float readVoltage(int pin) {
  long sum = 0;
  for (int i = 0; i < SAMPLES; i++) {
    sum += analogRead(pin);
    delay(5);
  }
  float avg = sum / (float)SAMPLES;
  return (avg / ADC_MAX) * VREF;
}

float calculateTDS(float voltage, float tempC) {
  float coeff = 1.0 + 0.02 * (tempC - 25.0);
  float compV = voltage / coeff;
  float tds = (133.42 * pow(compV, 3) - 255.86 * pow(compV, 2) + 857.39 * compV) * 0.5;
  return (tds < 0.0) ? 0.0 : tds;
}

float calculateTurbidity(float voltage) {
  // If sensor is powered by 5V, voltage in clean water is ~3.8-4.2V
  // If voltage drops, turbidity increases
  float ntu = 0.0;
  if (voltage >= (VREF * 0.75)) {
    ntu = 0.5; // Clear water baseline
  } else {
    ntu = -1120.4 * pow(voltage, 2) + 5742.3 * voltage - 4352.9;
    if (ntu < 0.0) ntu = 0.0;
    if (ntu > 3000.0) ntu = 3000.0;
  }
  return ntu;
}

void setup() {
  Serial.begin(115200);
  #if defined(ESP32)
    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);
  #endif
  delay(1000);
  Serial.println("{\"status\":\"INITIALIZED\",\"device_id\":\"ESP32-WATER-001\"}");
}

void loop() {
  float vTds = readVoltage(TDS_PIN);
  float vTurb = readVoltage(TURBIDITY_PIN);

  float tdsVal = calculateTDS(vTds, DEFAULT_TEMPERATURE);
  float turbVal = calculateTurbidity(vTurb);

  // Print strict JSON string per line for Python Serial Bridge:
  Serial.print("{\"device_id\":\"ESP32-WATER-001\",");
  Serial.print("\"tds\":");
  Serial.print(tdsVal, 1);
  Serial.print(",\"turbidity\":");
  Serial.print(turbVal, 2);
  Serial.print(",\"temperature\":");
  Serial.print(DEFAULT_TEMPERATURE, 1);
  Serial.print(",\"source\":\"");
  Serial.print(SOURCE_TAG);
  Serial.println("\"}");

  delay(3000); // Send reading every 3 seconds
}
