/*
 * DROPLET - Smart Water Quality Monitoring System
 * Universal Wi-Fi Telemetry Firmware for ESP8266 (NodeMCU) & ESP32
 *
 * Reads physical water sensors and streams real-time readings
 * to the DROPLET FastAPI backend via HTTPS POST /api/readings.
 *
 * ============================================================================
 * HARDWARE WIRING GUIDE:
 * ============================================================================
 *
 * 1. ESP8266 (NodeMCU 1.0 ESP-12E):
 *    - TDS Sensor Signal      -> Pin A0
 *    - TDS Sensor VCC         -> Pin VIN (5V from USB — DO NOT use 3V3!)
 *                               [IMPORTANT: 5V is REQUIRED for the probe's
 *                               onboard AC oscillator to run. On 3.3V, many
 *                               clone boards fail to oscillate and output 0V!]
 *    - TDS Sensor GND         -> Pin GND
 *
 *    Optional Dual-Sensor on ESP8266 (Mode 3: SENSOR_MODE_DUAL_SWITCH):
 *    - TDS VCC                -> Pin D5 (GPIO 14)
 *    - Turbidity VCC          -> Pin D6 (GPIO 12)
 *    - Both Signal pins (AOUT)-> Pin A0
 *    - Shared GND             -> Pin GND
 *
 * 2. ESP32 DevKit V1:
 *    - TDS Sensor Signal      -> GPIO 34 (ADC1_CH6)
 *    - TDS Sensor VCC         -> 5V (VIN) or 3.3V
 *    - TDS Sensor GND         -> GND
 *    - Turbidity Sensor Signal-> GPIO 35 (ADC1_CH7)
 *    - Turbidity Sensor VCC   -> 5V (VIN)
 *    - Turbidity Sensor GND   -> GND
 *
 * ============================================================================
 * HTTP RESPONSE CODES:
 *   201 Created       = Reading accepted, stored, rules evaluated, ML predicted
 *   200 OK            = Success
 *   -1 (conn failed)  = DNS or TLS handshake fail (Render waking up)
 *   -11 (timeout)     = Backend slow or cold start
 * ============================================================================
 */

// ==========================================
// 1. BOARD ARCHITECTURE DETECTION & INCLUDES
// ==========================================
#if defined(ESP32)
  #include <WiFi.h>
  #include <HTTPClient.h>
  #include <WiFiClientSecure.h>
  #include <ArduinoJson.h>

  #define BOARD_NAME         "ESP32 DevKit"
  #define DEFAULT_DEVICE_ID  "ESP32-WATER-001"
  #define DEFAULT_SOURCE_TAG "ESP32"

  #define PIN_TDS            34   // ADC1 Channel 6
  #define PIN_TURBIDITY      35   // ADC1 Channel 7
  #define ADC_MAX            4095.0f
  #define VREF               3.3f

#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <WiFiClientSecure.h>
  #include <ArduinoJson.h>

  #define BOARD_NAME         "NodeMCU ESP8266"
  #define DEFAULT_DEVICE_ID  "ESP8266-WATER-001"
  #define DEFAULT_SOURCE_TAG "ESP8266"

  #define PIN_ANALOG_A0      A0
  #define PIN_TDS_POWER      14   // NodeMCU pin D5 (for dual-switch mode)
  #define PIN_TURB_POWER     12   // NodeMCU pin D6 (for dual-switch mode)
  #define ADC_MAX            1023.0f
  #define VREF               3.3f

#else
  #error "Unsupported microcontroller. This firmware supports ESP8266 and ESP32."
#endif

// ==========================================
// 2. WI-FI & BACKEND CONFIGURATION
// ==========================================
const char* WIFI_SSID     = "Airtel_kaya_7448";
const char* WIFI_PASSWORD = "Air@84151";

// Public Render HTTPS API URL (no trailing slash)
const char* BACKEND_URL   = "https://droplet-api-byl8.onrender.com/api/readings";

const char* DEVICE_ID     = DEFAULT_DEVICE_ID;
const char* SOURCE_TAG    = DEFAULT_SOURCE_TAG;

// ==========================================
// 3. ESP8266 SENSOR SELECTION MODE
// ==========================================
// Mode 1: TDS sensor on A0. Turbidity reports clean baseline (0.50 NTU).
// Mode 2: Turbidity sensor on A0. TDS reports clean tap baseline (150.0 ppm).
// Mode 3: Dual sensors on single A0 switched via GPIO pins D5 and D6.
#define MODE_TDS_ONLY        1
#define MODE_TURBIDITY_ONLY  2
#define MODE_DUAL_SWITCH     3

// Set your active ESP8266 hardware wiring mode here:
#define ESP8266_MODE         MODE_TDS_ONLY

// ==========================================
// 4. TIMING & SAMPLING CONSTANTS
// ==========================================
const unsigned long SEND_INTERVAL_MS    = 1000;   // 1 reading per second
const unsigned long WIFI_RETRY_MS       = 5000;   // Retry WiFi reconnect every 5s
const unsigned long HTTP_TIMEOUT_MS     = 15000;  // 15s timeout
const unsigned long COLD_START_EXTRA_MS = 25000;  // 25s for first request (cold start)
const int           NUM_ADC_SAMPLES     = 10;     // 10 samples x 1ms = 10ms sampling

// Nominal reference values when specific sensors are not physically attached
const float DEFAULT_TEMPERATURE = 25.0f;  // Standard reference temperature (°C)
const float DEFAULT_PH          = 7.0f;   // Neutral drinking water baseline (activates ML)

// Optional calibration factor (adjust if reading against a calibrated meter)
const float TDS_CALIBRATION_K   = 1.0f;

// ==========================================
// 5. GLOBAL STATE & CLIENTS
// ==========================================
unsigned long lastSendTime    = 0;
unsigned long lastWifiRetry   = 0;
bool          firstRequest    = true;
bool          isHttpConnected = false;

WiFiClientSecure secureClient;
HTTPClient       httpClient;

// ==========================================
// 6. SENSOR MEASUREMENT & CALCULATION FUNCTIONS
// ==========================================

/**
 * Read average analog voltage from a specified pin.
 * Also returns the raw integer ADC count for serial diagnostics.
 */
float readAnalogVoltage(int pin, int &rawADC) {
  long sum = 0;
  for (int i = 0; i < NUM_ADC_SAMPLES; i++) {
    sum += analogRead(pin);
    delay(1);
  }
  rawADC = (int)(sum / NUM_ADC_SAMPLES);
  return ((float)rawADC / ADC_MAX) * VREF;
}

/**
 * Standard Gravity Analog TDS calculation polynomial.
 * Includes dry-probe zero-clamping (< 0.05V) and temperature compensation.
 */
float calculateTDS(float voltage, float tempC) {
  // If voltage is very low, probe is dry in air or disconnected.
  // Clamp to 0.0 ppm to eliminate false ~10.8 ppm ADC noise.
  if (voltage < 0.05f) {
    return 0.0f;
  }

  // Temperature compensation to 25.0 °C
  float compensationCoefficient = 1.0f + 0.02f * (tempC - 25.0f);
  float compensationVoltage     = voltage / compensationCoefficient;

  // DFRobot Gravity TDS 3rd-order polynomial
  float tds = (133.42f * powf(compensationVoltage, 3)
             - 255.86f * powf(compensationVoltage, 2)
             + 857.39f * compensationVoltage) * 0.5f;

  tds *= TDS_CALIBRATION_K;
  return max(tds, 0.0f);
}

/**
 * Turbidity calculation (0 to 3000 NTU).
 * In clean water, optical sensor outputs high voltage (~3.0 - 4.2V).
 * As water clouds up, voltage drops.
 */
float calculateTurbidity(float voltage) {
  if (voltage >= (VREF * 0.75f)) {
    return 0.50f;  // Clean clear water nominal baseline
  }
  if (voltage < 0.05f) {
    return 0.0f;   // Probe disconnected or unpowered
  }

  // Quadratic conversion curve: NTU = -1120.4*V^2 + 5742.3*V - 4352.9
  float ntu = -1120.4f * powf(voltage, 2) + 5742.3f * voltage - 4352.9f;
  return constrain(ntu, 0.0f, 3000.0f);
}

// ==========================================
// 7. WI-FI CONNECTION MANAGEMENT
// ==========================================
bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;

  unsigned long now = millis();
  if (now - lastWifiRetry < WIFI_RETRY_MS) return false;
  lastWifiRetry = now;

  Serial.println(F("[WiFi] Connection lost. Reconnecting..."));
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  return false;
}

// ==========================================
// 8. TELEMETRY TRANSMISSION (PERSISTENT HTTPS)
// ==========================================
void sendTelemetry(float tds, float turbidity, float tempC, float phVal) {
  if (!ensureWiFi()) {
    Serial.println(F("[HTTP] Postponed — WiFi connecting..."));
    return;
  }

  // Build JSON payload matching FastAPI WaterReadingCreate schema
  StaticJsonDocument<256> doc;
  doc["device_id"]   = DEVICE_ID;
  doc["ph"]          = round(phVal * 10.0f) / 10.0f;       // Enables ML Potability prediction!
  doc["tds"]         = round(tds * 10.0f) / 10.0f;         // 1 decimal place (ppm)
  doc["turbidity"]   = round(turbidity * 100.0f) / 100.0f; // 2 decimal places (NTU)
  doc["temperature"] = round(tempC * 10.0f) / 10.0f;       // 1 decimal place (°C)
  doc["source"]      = SOURCE_TAG;

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  // Initialize or re-establish TLS session if disconnected
  if (!isHttpConnected || !httpClient.connected()) {
    Serial.println(F("[HTTP] Establishing TLS keep-alive session..."));
    secureClient.setInsecure();  // Bypass certificate validation for cloud IoT
    secureClient.setBufferSizes(2048, 512); // Conserve RAM
    httpClient.begin(secureClient, BACKEND_URL);
    httpClient.setTimeout(firstRequest ? COLD_START_EXTRA_MS : HTTP_TIMEOUT_MS);
    httpClient.setReuse(true);  // Keep connection open across 1-second ticks
    isHttpConnected = true;
  }

  httpClient.addHeader(F("Content-Type"), F("application/json"));
  httpClient.addHeader(F("User-Agent"),   F("ESP-DROPLET/2.1"));
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
      // Do NOT call httpClient.end() here to keep socket open for 1s loop!
    } else {
      Serial.printf("[HTTP POST] Server response %d. Re-establishing socket.\n", httpCode);
      httpClient.end();
      isHttpConnected = false;
    }
  } else {
    Serial.printf("[HTTP POST] Network/TLS error %d: %s\n",
                  httpCode, httpClient.errorToString(httpCode).c_str());
    httpClient.end();
    isHttpConnected = false;
  }
}

// ==========================================
// 9. SETUP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(600);

  Serial.println(F("\n=============================================="));
  Serial.printf("  DROPLET Water Telemetry - %s v2.1\n", BOARD_NAME);
  Serial.println(F("=============================================="));
  Serial.printf("[Config] Backend URL: %s\n", BACKEND_URL);
  Serial.printf("[Config] Device ID  : %s\n", DEVICE_ID);
  Serial.printf("[Config] Interval   : %lums\n", SEND_INTERVAL_MS);

#if defined(ESP32)
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db); // 0V - 3.3V range
  pinMode(PIN_TDS, INPUT);
  pinMode(PIN_TURBIDITY, INPUT);
  Serial.println(F("[Hardware] Dual-ADC Active: GPIO 34 (TDS) & GPIO 35 (Turbidity)"));

#elif defined(ESP8266)
  pinMode(PIN_ANALOG_A0, INPUT);
  #if (ESP8266_MODE == MODE_DUAL_SWITCH)
    pinMode(PIN_TDS_POWER, OUTPUT);
    pinMode(PIN_TURB_POWER, OUTPUT);
    digitalWrite(PIN_TDS_POWER, LOW);
    digitalWrite(PIN_TURB_POWER, LOW);
    Serial.println(F("[Hardware] Dual-Switch Mode: D5 (TDS Power) & D6 (Turb Power) on A0"));
  #elif (ESP8266_MODE == MODE_TURBIDITY_ONLY)
    Serial.println(F("[Hardware] Single-Sensor Mode: Turbidity Probe on A0"));
  #else
    Serial.println(F("[Hardware] Single-Sensor Mode: TDS Probe on A0"));
    Serial.println(F("[Notice] Connect TDS VCC to VIN (5V) so AC oscillator runs!"));
  #endif
#endif

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
    Serial.printf("[WiFi] IP Address: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println(F("[WiFi] Not connected at boot — will retry automatically"));
  }
}

// ==========================================
// 10. MAIN LOOP (NON-BLOCKING millis() TIMER)
// ==========================================
void loop() {
  unsigned long now = millis();

  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;

    float tdsVal   = 0.0f;
    float turbVal  = 0.50f;
    float tempC    = DEFAULT_TEMPERATURE;
    float phVal    = DEFAULT_PH;

    int rawTds  = 0;
    int rawTurb = 0;
    float vTds  = 0.0f;
    float vTurb = 0.0f;

#if defined(ESP32)
    // ESP32: Read both ADC channels simultaneously
    vTds   = readAnalogVoltage(PIN_TDS, rawTds);
    vTurb  = readAnalogVoltage(PIN_TURBIDITY, rawTurb);
    tdsVal = calculateTDS(vTds, tempC);
    turbVal = calculateTurbidity(vTurb);

#elif defined(ESP8266)
  #if (ESP8266_MODE == MODE_DUAL_SWITCH)
    // Power TDS sensor, sample A0, power down
    digitalWrite(PIN_TDS_POWER, HIGH);
    digitalWrite(PIN_TURB_POWER, LOW);
    delay(15);
    vTds = readAnalogVoltage(PIN_ANALOG_A0, rawTds);
    digitalWrite(PIN_TDS_POWER, LOW);

    // Power Turbidity sensor, sample A0, power down
    digitalWrite(PIN_TURB_POWER, HIGH);
    delay(15);
    vTurb = readAnalogVoltage(PIN_ANALOG_A0, rawTurb);
    digitalWrite(PIN_TURB_POWER, LOW);

    tdsVal  = calculateTDS(vTds, tempC);
    turbVal = calculateTurbidity(vTurb);

  #elif (ESP8266_MODE == MODE_TURBIDITY_ONLY)
    // A0 is Turbidity sensor
    vTurb   = readAnalogVoltage(PIN_ANALOG_A0, rawTurb);
    turbVal = calculateTurbidity(vTurb);
    tdsVal  = 150.0f; // Baseline tap water TDS

  #else // MODE_TDS_ONLY (Default)
    // A0 is TDS sensor
    vTds    = readAnalogVoltage(PIN_ANALOG_A0, rawTds);
    tdsVal  = calculateTDS(vTds, tempC);
    turbVal = 0.50f;  // Baseline clear water turbidity
  #endif
#endif

    // Print clear diagnostic inspection output to Arduino Serial Monitor:
    Serial.println(F("--------------------------------------------------"));
#if defined(ESP32) || (defined(ESP8266) && ESP8266_MODE == MODE_DUAL_SWITCH)
    Serial.printf("[ADC]  TDS Raw: %4d (%.3fV)  |  Turbidity Raw: %4d (%.3fV)\n",
                  rawTds, vTds, rawTurb, vTurb);
#elif (defined(ESP8266) && ESP8266_MODE == MODE_TURBIDITY_ONLY)
    Serial.printf("[ADC]  A0 Raw: %4d / %d  |  Voltage: %.3f V (Turbidity Probe)\n",
                  rawTurb, (int)ADC_MAX, vTurb);
#else
    Serial.printf("[ADC]  A0 Raw: %4d / %d  |  Voltage: %.3f V (TDS Probe)\n",
                  rawTds, (int)ADC_MAX, vTds);
#endif

    Serial.printf("[DATA] TDS: %.1f ppm  |  Turbidity: %.2f NTU  |  pH: %.1f  |  Temp: %.1f C\n",
                  tdsVal, turbVal, phVal, tempC);

    if (vTds < 0.05f && (vTurb == 0.0f || vTurb < 0.05f)) {
      Serial.println(F("[INFO] Probe in AIR / DRY (0.0 ppm). Dip probe into water to test."));
      Serial.println(F("       TIP: If probe is in water but reads 0V, ensure VCC is on VIN (5V)!"));
    } else {
      Serial.printf("[INFO] Sensor reading active! TDS: %.1f ppm\n", tdsVal);
    }

    // Stream telemetry to Render FastAPI backend
    sendTelemetry(tdsVal, turbVal, tempC, phVal);
  }

  yield(); // Keep WiFi background stack active
}
