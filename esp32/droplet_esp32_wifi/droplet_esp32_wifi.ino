/*
 * DROPLET - Smart Water Quality Monitoring System
 * ESP32 Wi-Fi Hardware Telemetry Firmware
 *
 * Reads physical TDS and Turbidity sensors and streams real-time readings
 * to the DROPLET FastAPI backend via HTTP POST /api/readings.
 *
 * Hardware Pinout:
 * - TDS Sensor Analog Output      -> GPIO 34 (ADC1_CH6)
 * - Turbidity Sensor Analog Output -> GPIO 35 (ADC1_CH7)
 * - Power: 3.3V / 5V (See HARDWARE_SETUP.md for ADC voltage safety)
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ==========================================
// 1. NETWORK & BACKEND CONFIGURATION
// ==========================================
const char* WIFI_SSID     = "Airtel_kaya_7448";         // Replace with your 2.4GHz Wi-Fi SSID
const char* WIFI_PASSWORD = "Air@84151";     // Replace with your Wi-Fi password

// Replace with your computer's local IP address running the backend.
// Example: "http://192.168.1.4:8000/api/readings"
const char* BACKEND_URL   = "http://192.168.1.4:8000/api/readings";

const char* DEVICE_ID     = "ESP32-WATER-001";
const char* SOURCE_TAG    = "ESP32";

// Telemetry transmit interval (in milliseconds)
const unsigned long SEND_INTERVAL_MS = 5000; // Send reading every 5 seconds

// ==========================================
// 2. HARDWARE PINS & CALIBRATION CONSTANTS
// ==========================================
#define TDS_PIN        34      // ADC1 Pin for TDS sensor
#define TURBIDITY_PIN  35      // ADC1 Pin for Turbidity sensor

#define VREF           3.3     // ESP32 ADC Reference Voltage
#define ADC_RESOLUTION 4095.0  // 12-bit ADC (0 - 4095)
#define NUM_SAMPLES    30      // Samples per reading for noise filtering

// Default temperature for compensation if no physical temp sensor is attached
const float DEFAULT_TEMPERATURE = 25.0; // °C

unsigned long lastSendTime = 0;

// ==========================================
// 3. SENSOR READING & CONVERSION FUNCTIONS
// ==========================================

// Read analog pin with multi-sample averaging to reduce ADC noise
float readAverageVoltage(int pin) {
  float sum = 0.0;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    sum += analogRead(pin);
    delay(5);
  }
  float avgRaw = sum / NUM_SAMPLES;
  return (avgRaw / ADC_RESOLUTION) * VREF;
}

// Convert Voltage to TDS (ppm) with temperature compensation
// Standard Gravity Analog TDS formula
float calculateTDS(float voltage, float tempC) {
  // Temperature compensation coefficient
  float compensationCoefficient = 1.0 + 0.02 * (tempC - 25.0);
  float compensationVoltage = voltage / compensationCoefficient;

  // Polynomial conversion formula for standard Gravity TDS sensor:
  // TDS = (133.42 * V^3 - 255.86 * V^2 + 857.39 * V) * 0.5
  float tds = (133.42 * pow(compensationVoltage, 3) 
             - 255.86 * pow(compensationVoltage, 2) 
             + 857.39 * compensationVoltage) * 0.5;

  if (tds < 0.0) tds = 0.0;
  return tds;
}

// Convert Voltage to Turbidity (NTU)
// Standard Gravity Turbidity Sensor characteristic curve:
// In clear water (~0 NTU), voltage is typically around 3.8V - 4.2V (or ~2.5V-3.0V on 3.3V rail).
// When turbidity increases, voltage drops.
float calculateTurbidity(float voltage) {
  // Turbidity characteristic equation: y = -1120.4*x^2 + 5742.3*x - 4352.9
  // Clamped appropriately for real-world thresholds.
  float ntu = 0.0;

  if (voltage >= 2.5) {
    // Clear water zone (approx 0 - 5 NTU)
    // Linear interpolation for stable readings near clean water threshold:
    ntu = (3.0 - voltage) * 10.0;
    if (ntu < 0.0) ntu = 0.0;
  } else {
    // Highly turbid water zone
    ntu = -1120.4 * pow(voltage, 2) + 5742.3 * voltage - 4352.9;
    if (ntu < 0.0) ntu = 0.0;
    if (ntu > 3000.0) ntu = 3000.0;
  }

  return ntu;
}

// ==========================================
// 4. HTTP TRANSMISSION FUNCTION
// ==========================================
void sendTelemetry(float tds, float turbidity, float tempC) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[Wi-Fi] Disconnected! Attempting reconnect...");
    WiFi.reconnect();
    return;
  }

  HTTPClient http;
  http.begin(BACKEND_URL);
  http.addHeader("Content-Type", "application/json");

  // Construct JSON payload matching DROPLET API schema:
  // TDS and Turbidity are required; pH and temperature are optional.
  StaticJsonDocument<256> doc;
  doc["device_id"]   = DEVICE_ID;
  doc["tds"]         = serialized(String(tds, 1));        // 1 decimal place (ppm)
  doc["turbidity"]   = serialized(String(turbidity, 2));  // 2 decimal places (NTU)
  doc["temperature"] = serialized(String(tempC, 1));
  doc["source"]      = SOURCE_TAG;

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  Serial.print("[HTTP POST] Sending payload: ");
  Serial.println(jsonPayload);

  int httpCode = http.POST(jsonPayload);

  if (httpCode > 0) {
    Serial.printf("[HTTP POST] Response Code: %d\n", httpCode);
    if (httpCode == HTTP_CODE_CREATED || httpCode == HTTP_CODE_OK) {
      String response = http.getString();
      Serial.printf("[HTTP POST] Success response: %s\n", response.c_str());
    }
  } else {
    Serial.printf("[HTTP POST] Error: %s\n", http.errorToString(httpCode).c_str());
  }

  http.end();
}

// ==========================================
// 5. SETUP & MAIN LOOP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n==========================================");
  Serial.println("  DROPLET - ESP32 Hardware Telemetry Node");
  Serial.println("==========================================");

  // Configure ADC pins
  pinMode(TDS_PIN, INPUT);
  pinMode(TURBIDITY_PIN, INPUT);
  analogReadResolution(12); // 12-bit resolution (0-4095)
  analogSetAttenuation(ADC_11db); // Full range 0 - 3.3V

  // Connect to Wi-Fi
  Serial.printf("[Wi-Fi] Connecting to %s ", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[Wi-Fi] Connected successfully!");
    Serial.print("[Wi-Fi] ESP32 IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n[Wi-Fi] Failed to connect. Will retry during loop.");
  }
}

void loop() {
  unsigned long now = millis();

  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;

    // 1. Read Raw Voltages
    float tdsVoltage = readAverageVoltage(TDS_PIN);
    float turbidityVoltage = readAverageVoltage(TURBIDITY_PIN);

    // 2. Compute Physical Values
    float tdsValue = calculateTDS(tdsVoltage, DEFAULT_TEMPERATURE);
    float turbidityValue = calculateTurbidity(turbidityVoltage);

    // 3. Print Local Diagnostics
    Serial.println("------------------------------------------");
    Serial.printf("Raw TDS Voltage:       %.3f V  --> TDS: %.1f ppm\n", tdsVoltage, tdsValue);
    Serial.printf("Raw Turbidity Voltage: %.3f V  --> Turbidity: %.2f NTU\n", turbidityVoltage, turbidityValue);

    // 4. Stream to DROPLET Backend
    sendTelemetry(tdsValue, turbidityValue, DEFAULT_TEMPERATURE);
  }
}
