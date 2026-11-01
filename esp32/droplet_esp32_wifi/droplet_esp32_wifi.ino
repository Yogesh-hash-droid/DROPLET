/*
 * DROPLET - Smart Water Quality Monitoring System
 * Dedicated Wi-Fi Telemetry Firmware for ESP8266 (NodeMCU) + ADS1115 ADC
 *
 * Streams real-time TDS and Turbidity sensor readings to the DROPLET
 * FastAPI backend via HTTPS POST /api/readings every 1 second.
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
#include <Adafruit_ADS1X15.h>
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
const unsigned long SEND_INTERVAL_MS    = 1000;   // Exactly 1 second
const unsigned long WIFI_RETRY_MS       = 5000;   // Retry WiFi reconnect every 5s
const unsigned long HTTP_TIMEOUT_MS     = 15000;  // 15s timeout
const unsigned long COLD_START_EXTRA_MS = 25000;  // 25s for first request (cold start)

// Channels on the ADS1115 (0 = A0, 1 = A1)
#define ADS_CH_TDS        0       // Channel A0 = TDS Meter (Yellow wire)
#define ADS_CH_TURBIDITY  1       // Channel A1 = Turbidity Sensor (Purple wire)

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
bool          useAdafruitLib  = false;
uint8_t       adsDetectedAddr = 0x48;

Adafruit_ADS1115 ads;
WiFiClientSecure secureClient;
HTTPClient       httpClient;

// ==========================================
// 4. PHYSICAL CALCULATION FORMULAS
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
    ntu = 0.0f; // Probe disconnected or switch on 'D'
  } else {
    // Standard quadratic characteristic curve
    ntu = -1120.4f * powf(voltage, 2) + 5742.3f * voltage - 4352.9f;
    if (ntu < 0.0f) ntu = 0.50f;
    if (ntu > 3000.0f) ntu = 3000.0f;
  }
  return ntu;
}

// ==========================================
// 5. BULLETPROOF DUAL-ENGINE ADS1115 DRIVER
// ==========================================

/**
 * Reads single-ended ADC channel (0 = A0, 1 = A1) with GAIN_ONE (+/-4.096V).
 * Uses Adafruit library if available, with automatic Native Wire fallback.
 */
int16_t readADS1115Channel(uint8_t channel, float &voltage) {
  int16_t raw = 0;

  // Method A: Adafruit Library (if successfully initialized)
  if (useAdafruitLib) {
    raw = ads.readADC_SingleEnded(channel);
    voltage = ads.computeVolts(raw);
    if (raw >= 0) return raw;
  }

  // Method B: Native Wire Direct Register Access (100% reliable on ESP8266)
  // Config: OS=1 (start), GAIN_ONE=+/-4.096V (0x0200), SINGLE_SHOT (0x0100), 128_SPS (0x0080), COMP_DIS (0x0003)
  uint16_t config = 0x8000 | 0x0200 | 0x0100 | 0x0080 | 0x0003;
  if (channel == 0)      config |= 0x4000; // AIN0 vs GND (TDS)
  else if (channel == 1) config |= 0x5000; // AIN1 vs GND (Turbidity)

  // 1. Point to Config Register (0x01) and write configuration
  Wire.beginTransmission(adsDetectedAddr);
  Wire.write(0x01);
  Wire.write((uint8_t)(config >> 8));
  Wire.write((uint8_t)(config & 0xFF));
  if (Wire.endTransmission() != 0) {
    voltage = 0.0f;
    return 0;
  }

  // 2. Wait conversion time (128 SPS = 7.8ms; wait 9ms)
  delay(9);

  // 3. Point to Conversion Register (0x00)
  Wire.beginTransmission(adsDetectedAddr);
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) {
    voltage = 0.0f;
    return 0;
  }

  // 4. Read 2-byte 16-bit conversion result
  if (Wire.requestFrom((uint8_t)adsDetectedAddr, (uint8_t)2) >= 2) {
    raw = (int16_t)((Wire.read() << 8) | Wire.read());
    if (raw < 0) raw = 0;
    // GAIN_ONE: 4.096V / 32768 = 0.125 mV per count
    voltage = raw * 0.000125f;
    return raw;
  }

  voltage = 0.0f;
  return 0;
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
  httpClient.addHeader(F("User-Agent"),   F("ESP8266-ADS1115-DROPLET/3.2"));
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

  // Stabilize I2C bus pins on NodeMCU (D2 = SDA / GPIO 4, D1 = SCL / GPIO 5)
  pinMode(D1, INPUT_PULLUP);
  pinMode(D2, INPUT_PULLUP);
  Wire.begin(D2, D1);
  Wire.setClock(100000);           // 100 kHz standard I2C clock
  Wire.setClockStretchLimit(2000); // 2ms max stretch (prevents freezing)
  delay(50);                       // Settle bus

  // Instant ADS1115 Hardware Probe (takes 2ms instead of 67s)
  Serial.println(F("[I2C] Probing ADS1115 on SDA=D2, SCL=D1..."));
  for (uint8_t addr = 0x48; addr <= 0x4B; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      adsDetectedAddr = addr;
      ads1115Found = true;
      Serial.printf("[I2C] Hardware ACK at address 0x%02X!\n", addr);
      break;
    }
  }

  if (ads1115Found) {
    // Attempt Adafruit library initialization
    if (ads.begin(adsDetectedAddr)) {
      ads.setGain(GAIN_ONE);
      useAdafruitLib = true;
      Serial.printf("[ADS1115] Driver initialized via Adafruit (0x%02X)\n", adsDetectedAddr);
    } else {
      // Automatic Native Wire fallback (100% reliable on ESP8266)
      useAdafruitLib = false;
      Serial.printf("[ADS1115] Driver initialized via Native Wire (0x%02X)\n", adsDetectedAddr);
    }
  } else {
    Serial.println(F("[ADS1115] ERROR: No ACK at 0x48! Verify wiring:"));
    Serial.println(F("      ESP 3V -> ADS VDD (Red)"));
    Serial.println(F("      ESP G  -> ADS GND & ADDR (Black)"));
    Serial.println(F("      ESP D1 -> ADS SCL (Blue)"));
    Serial.println(F("      ESP D2 -> ADS SDA (Green)"));
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
// 9. MAIN LOOP (NON-BLOCKING 1-SECOND TIMER)
// ==========================================
void loop() {
  unsigned long now = millis();

  // Exactly every 1000ms (1 second)
  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime += SEND_INTERVAL_MS;
    if (now - lastSendTime >= SEND_INTERVAL_MS) {
      lastSendTime = now;
    }

    float vTds  = 0.0f;
    float vTurb = 0.0f;
    int16_t rawTds = 0;
    int16_t rawTurb = 0;

    // Auto-reconnect if device wasn't detected at boot
    if (!ads1115Found) {
      Wire.beginTransmission(adsDetectedAddr);
      if (Wire.endTransmission() == 0) {
        ads1115Found = true;
        Serial.printf("[ADS1115] Reconnected at 0x%02X!\n", adsDetectedAddr);
      }
    }

    if (ads1115Found) {
      // Channel 0 = TDS Meter (Yellow wire to ADS A0)
      rawTds = readADS1115Channel(ADS_CH_TDS, vTds);

      // Channel 1 = Turbidity Sensor (Purple wire to ADS A1)
      rawTurb = readADS1115Channel(ADS_CH_TURBIDITY, vTurb);
    }

    // Compute Physical Values
    float tdsValue       = calculateTDS(vTds, DEFAULT_TEMPERATURE);
    float turbidityValue = calculateTurbidity(vTurb);

    // Print Local Diagnostics to Serial Monitor
    Serial.println(F("--------------------------------------------------"));
    Serial.printf("[ADS1115] Raw A0: %5d (%.3fV) -> TDS: %.1f ppm  |  Raw A1: %5d (%.3fV) -> Turbidity: %.2f NTU\n",
                  rawTds, vTds, tdsValue, rawTurb, vTurb, turbidityValue);

    if (vTds < 0.015f) {
      Serial.println(F("   -> [TDS TIP] 0.0 ppm: Submerge the TDS metal probe in water to see reading rise!"));
    }
    if (vTurb < 0.05f) {
      Serial.println(F("   -> [TURBIDITY TIP] 0.00 NTU: Verify blue adapter switch is on 'A' (Analog), NOT 'D'!"));
    }

    // Stream Telemetry to DROPLET Cloud Backend
    sendTelemetry(tdsValue, turbidityValue, DEFAULT_TEMPERATURE, DEFAULT_PH);
  }

  yield(); // Keep WiFi background tasks active
}
