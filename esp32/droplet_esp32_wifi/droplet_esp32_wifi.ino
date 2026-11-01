/*
 * DROPLET - Smart Water Quality Monitoring System
 * Dedicated Firmware for ESP8266 (NodeMCU 1.0 ESP-12E)
 *
 * Reads physical water sensors and streams real-time readings
 * to the DROPLET FastAPI backend via HTTPS POST /api/readings.
 *
 * KEY CHANGES (v2):
 *   - 1-second telemetry interval using millis() (no blocking delay() in main loop)
 *   - ADC samples taken at 1ms intervals (non-blocking between readings is future work)
 *   - Connection reuse: persistent WiFiClientSecure + http.setReuse(true)
 *   - Automatic WiFi reconnect with backoff (no crash on cold-start)
 *   - Full HTTP code diagnostic output on Serial
 *   - source = "ESP8266" matches the backend DeviceSource enum
 *   - TODO: Replace setInsecure() with certificate pinning before production
 *
 * Hardware Pinout on NodeMCU:
 *   TDS Sensor Signal  -> Pin A0
 *   TDS Sensor VCC     -> Pin 3V3 (3.3V)
 *   TDS Sensor GND     -> Pin GND
 *
 * HTTP Response Code Reference:
 *   201 Created     = reading accepted and stored (success)
 *   200 OK          = success (some proxies return 200 instead of 201)
 *   400 Bad Request = malformed JSON or field validation failed
 *   404 Not Found   = wrong URL path
 *   422 Unprocessable = field value out of range (e.g. negative TDS)
 *   500 Server Error = backend crash (check Render logs)
 *   -1 (connection failed) = DNS fail, TLS handshake fail, or Render sleeping
 *   -11 (read timeout) = backend too slow or sleeping (cold start)
 *   301/302 Redirect = wrong URL (http:// instead of https://)
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

// Public Render HTTPS URL — must match exactly (no trailing slash)
const char* BACKEND_URL   = "https://droplet-api-byl8.onrender.com/api/readings";

const char* DEVICE_ID     = "ESP8266-WATER-001";
const char* SOURCE_TAG    = "ESP8266";  // Matches backend DeviceSource enum

// ==========================================
// 2. TIMING CONSTANTS
// ==========================================
// Target: 1 reading per second using millis() (non-blocking)
const unsigned long SEND_INTERVAL_MS    = 1000;   // 1 second between sends
const unsigned long WIFI_RETRY_MS       = 5000;   // WiFi reconnect retry interval
const unsigned long HTTP_TIMEOUT_MS     = 15000;  // 15s TLS/HTTP timeout (Render cold start)
const unsigned long COLD_START_EXTRA_MS = 25000;  // Extra timeout for very first request

// ==========================================
// 3. HARDWARE CONSTANTS
// ==========================================
#define ANALOG_PIN     A0
#define VREF           3.3f
#define ADC_RESOLUTION 1023.0f
#define NUM_SAMPLES    10      // Reduced from 30 to allow 1s loop (10 x 1ms = 10ms)

const float DEFAULT_TEMPERATURE = 25.0f;  // °C (no temperature sensor fitted)

// ==========================================
// 4. STATE VARIABLES
// ==========================================
unsigned long lastSendTime   = 0;
unsigned long lastWifiRetry  = 0;
bool          firstRequest   = true;       // Longer timeout on cold start

// Persistent HTTPS client & HTTPClient — reused across requests (no TLS re-handshake every second)
WiFiClientSecure secureClient;
HTTPClient       httpClient;
bool             isHttpConnected = false;

// ==========================================
// 5. SENSOR CALCULATION FUNCTIONS
// ==========================================

// Read A0 with averaging — 1ms between samples to fit inside 1s loop
float readAverageVoltage() {
  float sum = 0.0f;
  for (int i = 0; i < NUM_SAMPLES; i++) {
    sum += analogRead(ANALOG_PIN);
    delay(1);  // 1ms — 10 samples = 10ms total
  }
  return (sum / NUM_SAMPLES / ADC_RESOLUTION) * VREF;
}

// Standard Gravity TDS sensor polynomial (temperature-compensated)
float calculateTDS(float voltage, float tempC) {
  float compensationCoefficient = 1.0f + 0.02f * (tempC - 25.0f);
  float compensationVoltage     = voltage / compensationCoefficient;
  float tds = (133.42f * powf(compensationVoltage, 3)
             - 255.86f * powf(compensationVoltage, 2)
             + 857.39f * compensationVoltage) * 0.5f;
  return max(tds, 0.0f);
}

// Simple voltage-to-turbidity (NTU) mapping
float calculateTurbidity(float voltage) {
  float ntu;
  if (voltage >= (VREF * 0.75f)) {
    ntu = (VREF - voltage) * 10.0f;
  } else {
    ntu = -1120.4f * powf(voltage, 2) + 5742.3f * voltage - 4352.9f;
  }
  return constrain(ntu, 0.0f, 3000.0f);
}

// ==========================================
// 6. WIFI MANAGEMENT
// ==========================================
bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;

  unsigned long now = millis();
  if (now - lastWifiRetry < WIFI_RETRY_MS) return false;
  lastWifiRetry = now;

  Serial.println(F("[WiFi] Disconnected. Reconnecting..."));
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  // Non-blocking: caller retries on next loop tick
  return false;
}

// ==========================================
// 7. HTTP POST TRANSMISSION (connection reuse)
// ==========================================
void sendTelemetry(float tds, float turbidity, float tempC) {
  if (!ensureWiFi()) {
    Serial.println(F("[HTTP] Skipping — WiFi not ready"));
    return;
  }

  // Build JSON payload (latest value only; 256-byte static buffer survives drops without RAM exhaustion)
  StaticJsonDocument<256> doc;
  doc["device_id"]   = DEVICE_ID;
  doc["tds"]         = round(tds * 10.0f) / 10.0f;       // 1 dp
  doc["turbidity"]   = round(turbidity * 100.0f) / 100.0f; // 2 dp
  doc["temperature"] = round(tempC * 10.0f) / 10.0f;
  doc["source"]      = SOURCE_TAG;

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  // Initialize or re-establish TLS session if disconnected
  if (!isHttpConnected || !httpClient.connected()) {
    Serial.println(F("[HTTP] Connecting TLS session (keep-alive)..."));
    secureClient.setInsecure();  // TODO: pin the Render TLS cert before production
    secureClient.setBufferSizes(2048, 512); // Conserve RAM to avoid OOM
    httpClient.begin(secureClient, BACKEND_URL);
    httpClient.setTimeout(firstRequest ? COLD_START_EXTRA_MS : HTTP_TIMEOUT_MS);
    httpClient.setReuse(true);  // Keep-alive: reuse TCP/TLS session
    isHttpConnected = true;
  }

  httpClient.addHeader(F("Content-Type"), F("application/json"));
  httpClient.addHeader(F("User-Agent"),   F("ESP8266-DROPLET/2.0"));
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
      Serial.printf("[HTTP POST] Success (%d bytes, keep-alive active)\n", resp.length());
      // Crucial: do NOT call httpClient.end() here! Keep connection open for next second's send.
    } else {
      Serial.printf("[HTTP POST] Server returned HTTP %d\n", httpCode);
      httpClient.end();
      isHttpConnected = false;
    }
  } else {
    // Negative error: network drop / timeout -> reset connection for next loop
    Serial.printf("[HTTP POST] Connection error %d: %s\n", httpCode,
                  httpClient.errorToString(httpCode).c_str());
    httpClient.end();
    isHttpConnected = false;
  }
}

// ==========================================
// 8. SETUP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println(F("\n=========================================="));
  Serial.println(F("  DROPLET - ESP8266 (NodeMCU) v2.0"));
  Serial.println(F("=========================================="));
  Serial.print(F("[Config] Backend URL: "));
  Serial.println(BACKEND_URL);
  Serial.print(F("[Config] Device ID : "));
  Serial.println(DEVICE_ID);
  Serial.print(F("[Config] Interval  : "));
  Serial.print(SEND_INTERVAL_MS);
  Serial.println(F("ms (1 reading/second)"));

  pinMode(ANALOG_PIN, INPUT);

  // Connect to Wi-Fi (blocking only at boot)
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
    Serial.println(F("[WiFi] Connected!"));
    Serial.print(F("[WiFi] IP Address: "));
    Serial.println(WiFi.localIP());
  } else {
    Serial.println(F("[WiFi] Not connected at boot — will retry in loop"));
  }
}

// ==========================================
// 9. MAIN LOOP (millis()-based, non-blocking)
// ==========================================
void loop() {
  unsigned long now = millis();

  // Check if it's time to send a reading
  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;

    // Read analog voltage
    float voltage     = readAverageVoltage();
    float tdsValue    = calculateTDS(voltage, DEFAULT_TEMPERATURE);
    float turbidity   = 0.50f;  // No turbidity probe on A0; TDS is on A0.
                                  // Turbidity defaults to clean-water nominal (0.50 NTU).
                                  // Wire a turbidity sensor to a second ADC (GPIO+voltage divider)
                                  // or an ESP32 for dual-ADC operation.

    Serial.println(F("------------------------------------------"));
    Serial.printf("A0 Voltage  : %.3f V\n", voltage);
    Serial.printf("TDS         : %.1f ppm\n", tdsValue);
    Serial.printf("Turbidity   : %.2f NTU (nominal, no probe)\n", turbidity);
    Serial.printf("Temperature : %.1f C (default, no probe)\n", DEFAULT_TEMPERATURE);

    sendTelemetry(tdsValue, turbidity, DEFAULT_TEMPERATURE);
  }

  // Keep-alive: handle background WiFi events without blocking
  yield();
}
