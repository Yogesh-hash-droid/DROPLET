/*
 * DROPLET - Smart Water Quality Monitoring System
 * Dedicated Firmware for ESP8266 (NodeMCU 1.0 ESP-12E)
 *
 * Reads physical water sensors and streams real-time readings
 * to the DROPLET FastAPI backend via HTTP POST /api/readings.
 *
 * Hardware Pinout on NodeMCU:
 * - TDS Sensor Signal       -> Pin A0
 * - TDS Sensor VCC          -> Pin 3V3 (3.3V)
 * - TDS Sensor GND          -> Pin GND
 *
 * Note on ESP8266 ADC:
 * NodeMCU boards have ONE analog input (Pin A0).
 * It reads 0.0V to 3.3V with 10-bit resolution (0 - 1023).
 */

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>


// ==========================================
// 1. WI-FI & BACKEND CONFIGURATION
// ==========================================
const char* WIFI_SSID     = "Airtel_kaya_7448";
const char* WIFI_PASSWORD = "Air@84151";

// Local IP of your computer running the DROPLET backend:
const char* BACKEND_URL   = "http://192.168.1.4:8000/api/readings";

const char* DEVICE_ID     = "ESP8266-WATER-001";
const char* SOURCE_TAG    = "ESP8266";

// Telemetry transmit interval (in milliseconds)
const unsigned long SEND_INTERVAL_MS = 5000; // Send reading every 5 seconds

// ==========================================
// 2. HARDWARE CONSTANTS
// ==========================================
#define ANALOG_PIN     A0      // NodeMCU analog pin
#define VREF           3.3     // Voltage reference (3.3V on NodeMCU A0)
#define ADC_RESOLUTION 1023.0  // ESP8266 10-bit ADC (0 - 1023)
#define NUM_SAMPLES    30      // Samples per reading for noise filtering

const float DEFAULT_TEMPERATURE = 25.0; // °C
unsigned long lastSendTime = 0;

// ==========================================
// 3. SENSOR CALCULATION FUNCTIONS
// ==========================================

// Read analog pin A0 with multi-sample averaging to eliminate electrical jitter
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
  float compensationCoefficient = 1.0 + 0.02 * (tempC - 25.0);
  float compensationVoltage = voltage / compensationCoefficient;

  // Standard Gravity TDS polynomial conversion
  float tds = (133.42 * pow(compensationVoltage, 3) 
             - 255.86 * pow(compensationVoltage, 2) 
             + 857.39 * compensationVoltage) * 0.5;

  if (tds < 0.0) tds = 0.0;
  return tds;
}

// Convert Voltage to Turbidity (NTU)
float calculateTurbidity(float voltage) {
  float ntu = 0.0;
  if (voltage >= (VREF * 0.75)) {
    ntu = (VREF - voltage) * 10.0;
    if (ntu < 0.0) ntu = 0.0;
  } else {
    ntu = -1120.4 * pow(voltage, 2) + 5742.3 * voltage - 4352.9;
    if (ntu < 0.0) ntu = 0.0;
    if (ntu > 3000.0) ntu = 3000.0;
  }
  return ntu;
}

// ==========================================
// 4. HTTP POST TRANSMISSION FUNCTION
// ==========================================
void sendTelemetry(float tds, float turbidity, float tempC) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[Wi-Fi] Disconnected! Attempting reconnect...");
    WiFi.reconnect();
    return;
  }

  HTTPClient http;
  WiFiClient wifiClient;
  WiFiClientSecure secureClient;

  String url = String(BACKEND_URL);
  if (url.startsWith("https://")) {
    secureClient.setInsecure(); // Bypass SSL fingerprint check on ESP8266
    http.begin(secureClient, url);
  } else {
    http.begin(wifiClient, url);
  }

  http.addHeader("Content-Type", "application/json");


  // Construct JSON payload matching DROPLET API schema:
  // TDS and Turbidity are required; temperature is optional.
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
      Serial.printf("[HTTP POST] Server response: %s\n", response.c_str());
    }
  } else {
    Serial.printf("[HTTP POST] Failed error: %s\n", http.errorToString(httpCode).c_str());
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
  Serial.println("  DROPLET - ESP8266 (NodeMCU) Telemetry   ");
  Serial.println("==========================================");

  pinMode(ANALOG_PIN, INPUT);

  // Connect to Wi-Fi
  Serial.printf("[Wi-Fi] Connecting to %s ", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[Wi-Fi] Connected successfully!");
    Serial.print("[Wi-Fi] NodeMCU IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n[Wi-Fi] Connection pending. Retrying in loop...");
  }
}

void loop() {
  unsigned long now = millis();

  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;

    // 1. Read Analog Voltage from A0
    float a0Voltage = readAverageVoltage(ANALOG_PIN);

    // 2. Compute TDS from A0
    float tdsValue = calculateTDS(a0Voltage, DEFAULT_TEMPERATURE);

    // Note: ESP8266 has 1 ADC pin (A0). If your TDS probe is plugged into A0,
    // turbidity defaults to a nominal clean baseline (0.50 NTU).
    float turbidityValue = 0.50;

    // 3. Print Local Diagnostics to Serial Monitor
    Serial.println("------------------------------------------");
    Serial.printf("Raw A0 Voltage: %.3f V  --> TDS: %.1f ppm\n", a0Voltage, tdsValue);
    Serial.printf("Turbidity:      %.2f NTU\n", turbidityValue);

    // 4. Stream Telemetry to DROPLET Backend
    sendTelemetry(tdsValue, turbidityValue, DEFAULT_TEMPERATURE);
  }
}
