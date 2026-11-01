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
// 5. WI-FI MANAGEMENT
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
// 6. TELEMETRY TRANSMISSION (PERSISTENT HTTPS)
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
  httpClient.addHeader(F("User-Agent"),   F("ESP8266-ADS1115-DROPLET/3.1"));
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
// 7. SETUP
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

  // Initialize I2C bus: D2 = SDA (GPIO 4), D1 = SCL (GPIO 5)
  Wire.begin(D2, D1);
  Wire.setClock(100000); // 100 kHz I2C clock

  // Scan I2C bus to verify physical wiring to ADS1115
  Serial.println(F("[I2C] Scanning I2C bus (SDA=D2, SCL=D1)..."));
  uint8_t adsAddr = 0;
  int deviceCount = 0;
  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf("[I2C] Found device at address 0x%02X!\n", address);
      deviceCount++;
      if (address >= 0x48 && address <= 0x4B) {
        adsAddr = address;
      }
    }
  }

  if (deviceCount == 0) {
    Serial.println(F("[I2C] ERROR: No I2C devices detected! Please check jumper wires:"));
    Serial.println(F("      1. ESP 3V -> ADS VDD (Red wire)"));
    Serial.println(F("      2. ESP G  -> ADS GND & ADDR (Black wire)"));
    Serial.println(F("      3. ESP D1 -> ADS SCL (Blue wire)"));
    Serial.println(F("      4. ESP D2 -> ADS SDA (Green wire)"));
  }

  uint8_t targetAddr = (adsAddr != 0) ? adsAddr : 0x48;
  if (ads.begin(targetAddr)) {
    Serial.printf("[ADS1115] SUCCESS: Initialized at address 0x%02X!\n", targetAddr);
    ads.setGain(GAIN_ONE); // +/- 4.096V range, 0.125 mV/count
    ads1115Found = true;
    adsDetectedAddr = targetAddr;
  } else {
    Serial.printf("[ADS1115] ERROR: Initialization failed at 0x%02X!\n", targetAddr);
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
// 8. MAIN LOOP (NON-BLOCKING 1-SECOND TIMER)
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

    // Auto-reconnect to ADS1115 if communication was lost
    if (!ads1115Found) {
      for (uint8_t a = 0x48; a <= 0x4B; a++) {
        Wire.beginTransmission(a);
        if (Wire.endTransmission() == 0) {
          if (ads.begin(a)) {
            ads.setGain(GAIN_ONE);
            ads1115Found = true;
            adsDetectedAddr = a;
            Serial.printf("[ADS1115] Reconnected at 0x%02X!\n", a);
            break;
          }
        }
      }
    }

    if (ads1115Found) {
      // Channel 0 = TDS Meter (Yellow Wire)
      rawTds = ads.readADC_SingleEnded(ADS_CH_TDS);
      vTds   = ads.computeVolts(rawTds);

      // Channel 1 = Turbidity Sensor (Purple Wire)
      rawTurb = ads.readADC_SingleEnded(ADS_CH_TURBIDITY);
      vTurb   = ads.computeVolts(rawTurb);
    } else {
      Serial.println(F("[ADS1115] WARNING: ADS1115 offline (I2C no response)"));
    }

    // Compute Physical Values
    float tdsValue       = calculateTDS(vTds, DEFAULT_TEMPERATURE);
    float turbidityValue = calculateTurbidity(vTurb);

    // Print Local Diagnostics to Serial Monitor
    Serial.println(F("--------------------------------------------------"));
    Serial.printf("[ADS1115] Raw A0: %5d (%.3fV) -> TDS: %.1f ppm  |  Raw A1: %5d (%.3fV) -> Turbidity: %.2f NTU\n",
                  rawTds, vTds, tdsValue, rawTurb, vTurb, turbidityValue);

    if (vTds < 0.015f) {
      Serial.println(F("   -> [TDS TIP] 0.0 ppm: Place the TDS probe in water to see reading rise!"));
    }
    if (vTurb < 0.05f) {
      Serial.println(F("   -> [TURBIDITY TIP] 0.00 NTU: Verify blue adapter switch is on 'A' (Analog), NOT 'D'!"));
    }

    // Stream Telemetry to DROPLET Cloud Backend
    sendTelemetry(tdsValue, turbidityValue, DEFAULT_TEMPERATURE, DEFAULT_PH);
  }

  yield(); // Keep WiFi background tasks active
}
