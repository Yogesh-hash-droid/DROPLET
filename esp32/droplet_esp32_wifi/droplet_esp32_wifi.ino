/*
 * DROPLET - Smart Water Quality Monitoring System
 * Dedicated Wi-Fi Telemetry Firmware for ESP8266 (NodeMCU) + ADS1115 ADC
 *
 * Streams real-time TDS and Turbidity sensor readings to the DROPLET
 * FastAPI backend via HTTPS POST /api/readings.
 *
 * ============================================================================
 * AUTHORITATIVE WIRING CONNECTIONS (From Specification):
 * ============================================================================
 *
 * 1. ESP8266 to ADS1115 (I2C):
 *    - ESP 3V  -> ADS VDD (Wire: Red)
 *    - ESP G   -> ADS GND (Wire: Black)
 *    - ESP G   -> ADS ADDR (Wire: Black — sets I2C address 0x48)
 *    - ESP D1  -> ADS SCL (Wire: Blue — SCL = GPIO 5)
 *    - ESP D2  -> ADS SDA (Wire: Green — SDA = GPIO 4)
 *
 * 2. TDS Meter:
 *    - TDS Red (+)    -> ESP 3V (Wire: Red)
 *    - TDS Black (-)  -> ESP G (Wire: Black)
 *    - TDS Yellow (A) -> ADS A0 (Wire: Yellow)
 *
 * 3. Turbidity Sensor:
 *    - Turbidity V       -> ESP 3V (Wire: Red)
 *    - Turbidity G       -> ESP G (Wire: Black)
 *    - Turbidity Signal  -> ADS A1 (Wire: Purple)
 *    - [IMPORTANT: Set slide switch on Turbidity board to 'A' (Analog)!]
 *
 * Leave Unconnected:
 *    - ESP A0 (Onboard ADC), ADS ALERT, ADS A2, ADS A3.
 * ============================================================================
 */

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
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
// 2. TIMING & HARDWARE CONSTANTS
// ==========================================
const unsigned long SEND_INTERVAL_MS    = 1000;   // 1 reading per second
const unsigned long WIFI_RETRY_MS       = 5000;   // Retry WiFi reconnect every 5s
const unsigned long HTTP_TIMEOUT_MS     = 15000;  // 15s timeout
const unsigned long COLD_START_EXTRA_MS = 25000;  // 25s for first request (cold start)

// ADS1115 I2C Configuration (ADDR connected to GND = 0x48)
#define ADS1115_I2C_ADDR  0x48
#define PIN_I2C_SDA       D2      // GPIO 4
#define PIN_I2C_SCL       D1      // GPIO 5

// Channels on the ADS1115
#define ADS_CH_TDS        0       // Channel A0 = TDS Meter
#define ADS_CH_TURBIDITY  1       // Channel A1 = Turbidity Sensor

const float DEFAULT_TEMPERATURE = 25.0f;  // Standard reference temperature (°C)
const float DEFAULT_PH          = 7.0f;   // Neutral water baseline (activates ML model)

// ==========================================
// 3. GLOBAL STATE & CLIENTS
// ==========================================
unsigned long lastSendTime    = 0;
unsigned long lastWifiRetry   = 0;
bool          firstRequest    = true;
bool          isHttpConnected = false;
bool          ads1115Found    = false;

WiFiClientSecure secureClient;
HTTPClient       httpClient;

// ==========================================
// 4. NATIVE ADS1115 16-BIT I2C ADC DRIVER
// ==========================================

/**
 * Trigger and read single-ended analog voltage from ADS1115 channel (0 to 3).
 * PGA Gain set to +/-4.096V (FS), giving 0.125 mV (0.000125V) per LSB.
 */
float readADS1115Voltage(uint8_t channel, int16_t &outRaw) {
  // Config: OS=1 (start), PGA=+/-4.096V (0x0200), MODE=Single-Shot (0x0100), DR=128SPS (0x0080), COMP_DIS=0x0003
  uint16_t config = 0x8000 | 0x0200 | 0x0100 | 0x0080 | 0x0003;

  if (channel == 0)      config |= 0x4000; // AIN0 vs GND (TDS)
  else if (channel == 1) config |= 0x5000; // AIN1 vs GND (Turbidity)
  else if (channel == 2) config |= 0x6000; // AIN2 vs GND
  else if (channel == 3) config |= 0x7000; // AIN3 vs GND

  // Write Configuration Register (0x01)
  Wire.beginTransmission(ADS1115_I2C_ADDR);
  Wire.write(0x01);
  Wire.write((uint8_t)(config >> 8));
  Wire.write((uint8_t)(config & 0xFF));
  Wire.endTransmission();

  // Wait for 16-bit conversion (128 SPS = ~8ms)
  delay(9);

  // Point to Conversion Register (0x00)
  Wire.beginTransmission(ADS1115_I2C_ADDR);
  Wire.write(0x00);
  Wire.endTransmission();

  // Read 2 bytes (16-bit signed conversion result, MSB first)
  Wire.requestFrom((uint8_t)ADS1115_I2C_ADDR, (uint8_t)2);
  if (Wire.available() >= 2) {
    outRaw = (int16_t)((Wire.read() << 8) | Wire.read());
    if (outRaw < 0) outRaw = 0; // Negative voltage clamp

    // 16-bit LSB = 4.096V / 32768 = 0.000125V (0.125 mV)
    float voltage = outRaw * 0.000125f;
    return voltage;
  }

  outRaw = 0;
  return 0.0f;
}

// Average multiple ADS1115 samples for ultra-clean filtering
float readAverageADSVoltage(uint8_t channel, int samples = 5) {
  float sum = 0.0f;
  int16_t dummyRaw;
  for (int i = 0; i < samples; i++) {
    sum += readADS1115Voltage(channel, dummyRaw);
    delay(2);
  }
  return sum / (float)samples;
}

// ==========================================
// 5. PHYSICAL CALCULATION FORMULAS
// ==========================================

/**
 * Standard Gravity Analog TDS calculation polynomial (temperature-compensated).
 */
float calculateTDS(float voltage, float tempC) {
  if (voltage < 0.015f) {
    return 0.0f; // Dry probe in air
  }

  float compensationCoefficient = 1.0f + 0.02f * (tempC - 25.0f);
  float compensationVoltage     = voltage / compensationCoefficient;

  float tds = (133.42f * powf(compensationVoltage, 3)
             - 255.86f * powf(compensationVoltage, 2)
             + 857.39f * compensationVoltage) * 0.5f;

  if (tds < 0.0f) tds = 0.0f;
  return tds;
}

/**
 * Turbidity calculation (0 to 3000 NTU).
 * In clean water: optical transmittance is high (voltage ~2.0V - 3.2V) -> ~0.50 NTU.
 * As water clouds up: voltage drops -> NTU increases.
 */
float calculateTurbidity(float voltage) {
  float ntu = 0.0f;
  if (voltage >= 2.50f) {
    // Clear water baseline
    ntu = (3.3f - voltage) * 10.0f;
    if (ntu < 0.50f) ntu = 0.50f;
  } else if (voltage < 0.05f) {
    ntu = 0.0f; // Probe disconnected
  } else {
    // Standard quadratic characteristic curve
    ntu = -1120.4f * powf(voltage, 2) + 5742.3f * voltage - 4352.9f;
    if (ntu < 0.0f) ntu = 0.50f;
    if (ntu > 3000.0f) ntu = 3000.0f;
  }
  return ntu;
}

// ==========================================
// 6. WI-FI MANAGEMENT
// ==========================================
bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;

  unsigned long now = millis();
  if (now - lastWifiRetry < WIFI_RETRY_MS) return false;
  lastWifiRetry = now;

  Serial.println(F("[WiFi] Reconnecting..."));
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  return false;
}

// ==========================================
// 7. TELEMETRY TRANSMISSION (PERSISTENT HTTPS)
// ==========================================
void sendTelemetry(float tds, float turbidity, float tempC, float phVal) {
  if (!ensureWiFi()) {
    Serial.println(F("[HTTP] Skipping — WiFi not ready"));
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
    httpClient.setReuse(true);  // Keep connection open across 1s loop
    isHttpConnected = true;
  }

  httpClient.addHeader(F("Content-Type"), F("application/json"));
  httpClient.addHeader(F("User-Agent"),   F("ESP8266-ADS1115-DROPLET/3.0"));
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
    } else {
      Serial.printf("[HTTP POST] Server returned %d. Re-establishing socket.\n", httpCode);
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
// 8. SETUP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println(F("\n========================================================"));
  Serial.println(F("  DROPLET Water Telemetry - NodeMCU ESP8266 + ADS1115   "));
  Serial.println(F("========================================================"));
  Serial.printf("[Config] Backend URL: %s\n", BACKEND_URL);
  Serial.printf("[Config] Device ID  : %s\n", DEVICE_ID);
  Serial.printf("[Config] Interval   : %lums (1 reading/second)\n", SEND_INTERVAL_MS);

  // Initialize I2C bus for ADS1115 (D2 = SDA / GPIO 4, D1 = SCL / GPIO 5)
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(100000); // 100 kHz standard I2C clock

  // Probe ADS1115 on I2C address 0x48
  Wire.beginTransmission(ADS1115_I2C_ADDR);
  byte i2cError = Wire.endTransmission();
  if (i2cError == 0) {
    Serial.println(F("[I2C] SUCCESS: ADS1115 detected at address 0x48!"));
    ads1115Found = true;
  } else {
    Serial.printf("[I2C] WARNING: ADS1115 NOT detected at 0x48 (error %d)!\n", i2cError);
    Serial.println(F("      Verify wiring: D1 -> SCL, D2 -> SDA, ESP 3V -> VDD, G -> GND & ADDR"));
    ads1115Found = false;
  }

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
// 9. MAIN LOOP (NON-BLOCKING millis() TIMER)
// ==========================================
void loop() {
  unsigned long now = millis();

  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = now;

    // 1. Read ADS1115 Channel A0 (TDS Meter) and Channel A1 (Turbidity Sensor)
    float vTds  = readAverageADSVoltage(ADS_CH_TDS, 5);
    float vTurb = readAverageADSVoltage(ADS_CH_TURBIDITY, 5);

    // 2. Compute Physical Values
    float tdsValue       = calculateTDS(vTds, DEFAULT_TEMPERATURE);
    float turbidityValue = calculateTurbidity(vTurb);

    // 3. Print Local Diagnostics to Serial Monitor
    Serial.println(F("--------------------------------------------------"));
    Serial.printf("[ADS1115] TDS (A0): %.3f V -> %.1f ppm  |  Turbidity (A1): %.3f V -> %.2f NTU\n",
                  vTds, tdsValue, vTurb, turbidityValue);

    // 4. Stream Telemetry to DROPLET Cloud Backend
    sendTelemetry(tdsValue, turbidityValue, DEFAULT_TEMPERATURE, DEFAULT_PH);
  }

  yield(); // Keep WiFi background tasks active
}
