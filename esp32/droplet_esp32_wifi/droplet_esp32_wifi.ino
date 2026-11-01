/*
 * DROPLET - Smart Water Quality Monitoring System
 * Universal Hardware Telemetry Firmware (ESP32 & ESP8266 / NodeMCU)
 *
 * Reads physical TDS and Turbidity sensors and streams real-time readings
 * to the DROPLET FastAPI backend via HTTP POST /api/readings.
 *
 * Auto-detects whether you are compiling for ESP32 or ESP8266 (NodeMCU 1.0).
 */

// ==========================================
// 1. BOARD-SPECIFIC LIBRARIES & PIN DEFINITIONS
// ==========================================
#if defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <WiFiClient.h>
  
  // ESP8266 (NodeMCU) has only ONE analog input: A0 (0 - 3.3V, 10-bit ADC)
  #define TDS_PIN        A0
  #define TURBIDITY_PIN  A0      // Note: NodeMCU has 1 ADC. See notes below.
  #define VREF           3.3     // NodeMCU onboard divider maps 0-3.3V to 1023
  #define ADC_RESOLUTION 1023.0  // 10-bit ADC (0 - 1023)
  #define DEFAULT_DEVICE "ESP8266-WATER-001"
  #define DEFAULT_SOURCE "ESP8266"

#elif defined(ESP32)
  #include <WiFi.h>
  #include <HTTPClient.h>
  
  // ESP32 has multiple 12-bit ADC1 channels
  #define TDS_PIN        34      // ADC1 Pin for TDS sensor (GPIO 34)
  #define TURBIDITY_PIN  35      // ADC1 Pin for Turbidity sensor (GPIO 35)
  #define VREF           3.3     // ESP32 ADC Reference Voltage (0 - 3.3V)
  #define ADC_RESOLUTION 4095.0  // 12-bit ADC (0 - 4095)
  #define DEFAULT_DEVICE "ESP32-WATER-001"
  #define DEFAULT_SOURCE "ESP32"

#else
  #include <WiFi.h>
  #include <HTTPClient.h>
  #define TDS_PIN        A0
  #define TURBIDITY_PIN  A1
  #define VREF           5.0
  #define ADC_RESOLUTION 1023.0
  #define DEFAULT_DEVICE "ESP32-WATER-001"
  #define DEFAULT_SOURCE "ESP32"
#endif

#include <ArduinoJson.h>

// ==========================================
// 2. NETWORK & BACKEND CONFIGURATION
// ==========================================
const char* WIFI_SSID     = "Airtel_kaya_7448";         // Your 2.4GHz Wi-Fi SSID
const char* WIFI_PASSWORD = "Air@84151";                // Your Wi-Fi password

// Your computer's local IP address running the DROPLET backend:
const char* BACKEND_URL   = "http://192.168.1.4:8000/api/readings";

const char* DEVICE_ID     = DEFAULT_DEVICE;
const char* SOURCE_TAG    = DEFAULT_SOURCE;

// Telemetry transmit interval (in milliseconds)
const unsigned long SEND_INTERVAL_MS = 5000; // Send reading every 5 seconds

#define NUM_SAMPLES    30      // Samples per reading for noise filtering
const float DEFAULT_TEMPERATURE = 25.0; // °C

unsigned long lastSendTime = 0;

// ==========================================
// 3. SENSOR READING & CONVERSION FUNCTIONS
// ==========================================

// Read analog pin with multi-sample averaging to reduce electrical noise
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

  // Standard Gravity TDS polynomial formula
  float tds = (133.42 * pow(compensationVoltage, 3) 
             - 255.86 * pow(compensationVoltage, 2) 
             + 857.39 * compensationVoltage) * 0.5;

  if (tds < 0.0) tds = 0.0;
  return tds;
}

// Convert Voltage to Turbidity (NTU)
// Gravity Turbidity characteristic curve
float calculateTurbidity(float voltage) {
  float ntu = 0.0;

  if (voltage >= (VREF * 0.75)) {
    // Clear water zone (approx 0 - 5 NTU)
    ntu = (VREF - voltage) * 10.0;
    if (ntu < 0.0) ntu = 0.0;
  } else {
    // Turbid water zone
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

#if defined(ESP8266)
  WiFiClient wifiClient;
  http.begin(wifiClient, BACKEND_URL);
#else
  http.begin(BACKEND_URL);
#endif

  http.addHeader("Content-Type", "application/json");

  // Construct JSON payload matching DROPLET API schema
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
#if defined(ESP8266)
  Serial.println("  DROPLET - ESP8266 (NodeMCU) Telemetry Node");
#else
  Serial.println("  DROPLET - ESP32 Hardware Telemetry Node");
#endif
  Serial.println("==========================================");

  // Configure ADC pins
  pinMode(TDS_PIN, INPUT);

#if defined(ESP32)
  pinMode(TURBIDITY_PIN, INPUT);
  analogReadResolution(12);       // 12-bit resolution (0-4095)
  analogSetAttenuation(ADC_11db); // Full range 0 - 3.3V
#endif

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
    Serial.print("[Wi-Fi] Board IP Address: ");
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

#if defined(ESP8266)
    // ESP8266 only has 1 analog pin (A0). If you have TDS on A0,
    // we set a nominal clean-water turbidity (0.5 NTU) or you can alternate.
    float turbidityVoltage = tdsVoltage;
    float turbidityValue = 0.50;
#else
    float turbidityVoltage = readAverageVoltage(TURBIDITY_PIN);
    float turbidityValue = calculateTurbidity(turbidityVoltage);
#endif

    // 2. Compute Physical Values
    float tdsValue = calculateTDS(tdsVoltage, DEFAULT_TEMPERATURE);

    // 3. Print Local Diagnostics
    Serial.println("------------------------------------------");
    Serial.printf("Raw TDS Voltage:       %.3f V  --> TDS: %.1f ppm\n", tdsVoltage, tdsValue);
    Serial.printf("Turbidity NTU:         %.2f NTU\n", turbidityValue);

    // 4. Stream to DROPLET Backend
    sendTelemetry(tdsValue, turbidityValue, DEFAULT_TEMPERATURE);
  }
}
