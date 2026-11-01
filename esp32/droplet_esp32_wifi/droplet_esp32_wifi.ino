/*
 * DROPLET - Smart Water Quality Monitoring System
 * Dedicated Wi-Fi Telemetry Firmware for ESP8266 (NodeMCU 1.0 ESP-12E)
 *
 * Reads physical water sensors and streams real-time readings
 * to the DROPLET FastAPI backend via HTTPS POST /api/readings.
 *
 * ============================================================================
 * WIRING GUIDE FOR NODEMCU (ESP8266):
 * ============================================================================
 *
 * Sensor Power (Both TDS and Turbidity):
 *   - VCC -> Connect to 3V3 (or VU / 3V pin). DO NOT use VIN (VIN is 0V on USB!)
 *   - GND -> Connect to GND
 *
 * Sensor Signals:
 *   - Analog Out -> Connect to Pin A0
 *   - On the Turbidity module, set the physical slide switch to 'A' (Analog)!
 *
 * ============================================================================
 */

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

// ==========================================
// 1. WI-FI & BACKEND CONFIGURATION
// ==========================================
const char* WIFI_SSID     = "Airtel_kaya_7448";
const char* WIFI_PASSWORD = "Air@84151";

// Public Render HTTPS API URL (no trailing slash)
const char* BACKEND_URL   = "https://droplet-api-byl8.onrender.com/api/readings";

const char* DEVICE_ID     = "ESP8266-WATER-001";
const char* SOURCE_TAG    = "ESP8266";

// ==========================================
// 2. TIMING & SAMPLING CONSTANTS
// ==========================================
const unsigned long SEND_INTERVAL_MS    = 1000;   // 1 reading per second
const unsigned long WIFI_RETRY_MS       = 5000;   // Retry WiFi reconnect every 5s
const unsigned long HTTP_TIMEOUT_MS     = 15000;  // 15s timeout
const unsigned long COLD_START_EXTRA_MS = 25000;  // 25s for first request (cold start)

#define ANALOG_PIN        A0
#define VREF              3.3f
#define ADC_RESOLUTION    1023.0f
#define NUM_SAMPLES       30     // 30 samples x 5ms = 150ms stable window (filters RF noise)

const float DEFAULT_TEMPERATURE = 25.0f;  // °C
const float DEFAULT_PH          = 7.0f;   // Neutral water baseline (activates ML Potability model)

// ==========================================
// 3. GLOBAL STATE & CLIENTS
// ==========================================
unsigned long lastSendTime    = 0;
unsigned long lastWifiRetry   = 0;
bool          firstRequest    = true;
bool          isHttpConnected = false;

WiFiClientSecure secureClient;
HTTPClient       httpClient;

// ==========================================
// 4. SENSOR CALCULATION FUNCTIONS
// ==========================================

// Read analog pin A0 with multi-sample averaging (eliminates electrical jitter)
float readAverageVoltage(int pin) {
  float sum = 0.0f;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    sum += analogRead(pin);
    delay(5);  // 5ms delay between samples
  }
  float avgRaw = sum / (float)NUM_SAMPLES;
  return (avgRaw / ADC_RESOLUTION) * VREF;
}

// Standard Gravity Analog TDS formula (temperature compensated)
float calculateTDS(float voltage, float tempC) {
  float compensationCoefficient = 1.0f + 0.02f * (tempC - 25.0f);
  float compensationVoltage     = voltage / compensationCoefficient;

  float tds = (133.42f * powf(compensationVoltage, 3)
             - 255.86f * powf(compensationVoltage, 2)
             + 857.39f * compensationVoltage) * 0.5f;

  if (tds < 0.0f) tds = 0.0f;
  return tds;
}

// Convert Voltage to Turbidity (NTU)
// In clean water: voltage is high (~2.5V - 3.3V) -> low turbidity (~0.5 NTU)
// In cloudy/murky water: voltage drops -> turbidity increases
float calculateTurbidity(float voltage) {
  float ntu = 0.0f;
  if (voltage >= (VREF * 0.75f)) {
    // Clear water zone (approx 0 - 5 NTU)
    ntu = (VREF - voltage) * 10.0f;
    if (ntu < 0.50f) ntu = 0.50f; // Clean baseline
  } else {
    // Turbid water zone: quadratic characteristic curve
    ntu = -1120.4f * powf(voltage, 2) + 5742.3f * voltage - 4352.9f;
    if (ntu < 0.0f) ntu = 0.0f;
    if (ntu > 3000.0f) ntu = 3000.0f;
  }
  return ntu;
}

// ==========================================
// 5. WI-FI MANAGEMENT
// ==========================================
bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;

  unsigned long now = millis();
  if (now - lastWifiRetry < WIFI_RETRY_MS) return false;
  lastWifiRetry = now;

  Serial.println(F("[WiFi] Disconnected. Reconnecting..."));
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  return false;
}

// ==========================================
// 6. TELEMETRY TRANSMISSION (PERSISTENT HTTPS)
// ==========================================
void sendTelemetry(float tds, float turbidity, float tempC, float phVal) {
  if (!ensureWiFi()) {
    Serial.println(F("[HTTP] Skipping — WiFi not connected"));
    return;
  }

  // Build JSON payload matching DROPLET API schema
  StaticJsonDocument<256> doc;
  doc["device_id"]   = DEVICE_ID;
  doc["ph"]          = round(phVal * 10.0f) / 10.0f;       // Activates ML model
  doc["tds"]         = round(tds * 10.0f) / 10.0f;         // 1 dp (ppm)
  doc["turbidity"]   = round(turbidity * 100.0f) / 100.0f; // 2 dp (NTU)
  doc["temperature"] = round(tempC * 10.0f) / 10.0f;       // 1 dp (°C)
  doc["source"]      = SOURCE_TAG;

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  // Initialize or re-establish TLS session if disconnected
  if (!isHttpConnected || !httpClient.connected()) {
    Serial.println(F("[HTTP] Connecting TLS session (keep-alive)..."));
    secureClient.setInsecure();  // Bypass certificate fingerprint on ESP8266
    secureClient.setBufferSizes(2048, 512); // Conserve RAM
    httpClient.begin(secureClient, BACKEND_URL);
    httpClient.setTimeout(firstRequest ? COLD_START_EXTRA_MS : HTTP_TIMEOUT_MS);
    httpClient.setReuse(true);  // Keep connection open for 1s loop
    isHttpConnected = true;
  }

  httpClient.addHeader(F("Content-Type"), F("application/json"));
  httpClient.addHeader(F("User-Agent"),   F("ESP8266-DROPLET/2.2"));
  httpClient.addHeader(F("Accept"),       F("application/json"));
  httpClient.addHeader(F("Connection"),   F("keep-alive"));

  unsigned long t0 = millis();
  int httpCode = httpClient.POST(jsonPayload);
  unsigned long durationMs = millis() - t0;
  firstRequest = false;

  Serial.printf("[HTTP POST] Code %d (%lums) -> %s\n", httpCode, durationMs, jsonPayload.c_str());

  if (httpCode > 0) {
    if (httpCode == HTTP_CODE_CREATED || httpCode == HTTP_CODE_OK) {
      String resp = httpClient.getString();
      Serial.printf("[HTTP POST] OK (%d bytes response, keep-alive active)\n", resp.length());
      // Keep connection open across 1-second ticks
    } else {
      Serial.printf("[HTTP POST] Server response %d. Reconnecting.\n", httpCode);
      httpClient.end();
      isHttpConnected = false;
    }
  } else {
    Serial.printf("[HTTP POST] Connection error %d: %s\n",
                  httpCode, httpClient.errorToString(httpCode).c_str());
    httpClient.end();
    isHttpConnected = false;
  }
}

// ==========================================
// 7. SETUP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println(F("\n=============================================="));
  Serial.println(F("  DROPLET Water Telemetry - NodeMCU ESP8266   "));
  Serial.println(F("=============================================="));
  Serial.printf("[Config] Backend URL: %s\n", BACKEND_URL);
  Serial.printf("[Config] Device ID  : %s\n", DEVICE_ID);
  Serial.printf("[Config] Interval   : %lums (1 reading/second)\n", SEND_INTERVAL_MS);

  pinMode(ANALOG_PIN, INPUT);

  // Connect to Wi-Fi
  Serial.printf("[WiFi] Connecting to %s ", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(F("."));
    attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println(F("[WiFi] Connected successfully!"));
    Serial.printf("[WiFi] NodeMCU IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println(F("[WiFi] Connection pending. Retrying in loop..."));
  }
}

// ==========================================
// 8. MAIN LOOP (NON-BLOCKING millis() TIMER)
// ==========================================
void loop() {
  unsigned long now = millis();

  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;

    // 1. Read Analog Voltage from A0
    float a0Voltage = readAverageVoltage(ANALOG_PIN);

    // 2. Compute Physical Values
    float tdsValue = calculateTDS(a0Voltage, DEFAULT_TEMPERATURE);
    float turbidityValue = calculateTurbidity(a0Voltage);

    // 3. Print Local Diagnostics to Serial Monitor
    Serial.println(F("--------------------------------------------------"));
    Serial.printf("[SENSORS] A0 Voltage: %.3f V  |  TDS: %.1f ppm  |  Turbidity: %.2f NTU\n",
                  a0Voltage, tdsValue, turbidityValue);

    // 4. Stream Telemetry to DROPLET Cloud Backend
    sendTelemetry(tdsValue, turbidityValue, DEFAULT_TEMPERATURE, DEFAULT_PH);
  }

  yield(); // Keep WiFi background tasks active
}
