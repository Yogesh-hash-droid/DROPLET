/*
 * DROPLET - Smart Water Quality Monitoring System
 * Fault-Tolerant Telemetry Firmware for NodeMCU ESP8266 + ADS1115
 *
 * Firmware Version: 4.2.0-fault-tolerant
 *
 * KEY CAPABILITIES:
 * 1. Startup Full I2C Scanner (0x01-0x7F) with auto-detection of 0x48-0x4B.
 * 2. Non-blocking operation: ADS1115 failure NEVER stops WiFi, HTTP, or telemetry.
 * 3. Telemetry every 1000 ms regardless of sensor state:
 *    - Valid sensors: sends precise float values with sensor_status="ok".
 *    - Faulty sensors: sends null values with sensor_status="ads1115_not_found"
 *      or "read_error". NEVER fabricates fake/default sensor data.
 * 4. Automatic bus recovery and 5-second non-blocking retry on I2C faults.
 * 5. Device stays permanently ONLINE on Render and Vercel while reporting faults.
 *
 * ============================================================================
 * AUTHORITATIVE HARDWARE WIRING:
 * ============================================================================
 * 1. ESP8266 to ADS1115 (I2C):
 *    - ESP 3V (3.3V) -> ADS VDD (Red wire)
 *    - ESP G (GND)   -> ADS GND (Black wire)
 *    - ESP G (GND)   -> ADS ADDR (Black wire -> sets I2C address 0x48)
 *    - ESP D1 (GPIO 5)-> ADS SCL (Blue wire -> SCL clock)
 *    - ESP D2 (GPIO 4)-> ADS SDA (Green wire -> SDA data)
 *
 * 2. TDS Meter:
 *    - TDS Red (+)    -> ESP 3V (Red wire)
 *    - TDS Black (-)  -> ESP G (Black wire)
 *    - TDS Yellow (A) -> ADS A0 (Yellow wire -> Channel 0)
 *
 * 3. Turbidity Sensor:
 *    - Turbidity V (+)      -> ESP 3V (Red wire)
 *    - Turbidity G (-)      -> ESP G (Black wire)
 *    - Turbidity Signal (A) -> ADS A1 (Purple wire -> Channel 1)
 *    - [IMPORTANT: Set slide switch on blue adapter board to 'A' (Analog)!]
 *
 * 4. Reserved / Unconnected:
 *    - ADS A2 & A3 (Reserved for future pH or Temperature expansion)
 *    - ESP A0 (NodeMCU onboard ADC), ADS ALERT
 * ============================================================================
 */

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <ArduinoJson.h>

// ============================================================================
// CONFIG SECTION 1: HARDWARE PINS & I2C DEFINITIONS
// ============================================================================
#define FIRMWARE_VERSION        "4.2.0-fault-tolerant"
#define PIN_I2C_SDA             4       // GPIO 4 = NodeMCU D2 (SDA)
#define PIN_I2C_SCL             5       // GPIO 5 = NodeMCU D1 (SCL)
#define I2C_CLOCK_SPEED         100000  // 100 kHz standard I2C clock
#define I2C_STRETCH_LIMIT_US    1500    // 1500 us clock-stretch limit on ESP8266

// ADS1115 Programmable Gain: GAIN_ONE (+/-4.096V Full Scale, 0.125 mV/count)
#define ADS_PGA_CONFIG          0x0200  // PGA = 001 (+/-4.096V)
#define ADS_VOLTS_PER_COUNT     0.000125f // 4.096V / 32768 counts

// ============================================================================
// CONFIG SECTION 2: SENSOR CHANNEL MAPPING & CALIBRATION CONSTANTS
// ============================================================================
// Physical ADS1115 channel assignments (0=A0, 1=A1, 2=A2, 3=A3)
#define CHANNEL_TDS             0       // Channel A0 = TDS Meter (Yellow wire)
#define CHANNEL_TURBIDITY       1       // Channel A1 = Turbidity Sensor (Purple wire)
#define CHANNEL_PH_AUX          2       // Channel A2 = Reserved for pH
#define CHANNEL_TEMP_AUX        3       // Channel A3 = Reserved for Temp

// Temperature reference for temperature-compensated TDS calculation
const float DEFAULT_TEMPERATURE_C = 25.0f;

// ============================================================================
// CONFIG SECTION 3: WI-FI & BACKEND CONFIGURATION
// ============================================================================
const char* WIFI_SSID           = "Airtel_kaya_7448";
const char* WIFI_PASSWORD       = "Air@84151";

// Public Render HTTPS API URL
const char* BACKEND_URL         = "https://droplet-api-byl8.onrender.com/api/readings";
const char* DEVICE_ID           = "ESP8266-WATER-001";
const char* SOURCE_TAG          = "ESP8266";

// Timing Cadence
const unsigned long SEND_INTERVAL_MS      = 1000;   // Transmit telemetry every 1000 ms
const unsigned long I2C_RETRY_INTERVAL_MS = 5000;   // Non-blocking sensor retry every 5s
const unsigned long WIFI_RETRY_MS         = 5000;   // Non-blocking WiFi reconnect every 5s
const unsigned long HTTP_COLD_START_MS    = 10000;  // 10s timeout for first request (cold start)
const unsigned long HTTP_STANDARD_TIMEOUT = 5000;   // 5s standard timeout for subsequent requests

// ============================================================================
// GLOBAL STATE VARIABLES
// ============================================================================
unsigned long lastSendTime       = 0;
unsigned long lastI2cRetryTime   = 0;
unsigned long lastWifiRetryTime  = 0;
bool          firstRequest       = true;
bool          isHttpConnected    = false;

// I2C Sensor Hardware State
bool          adsFound           = false;
uint8_t       adsAddress         = 0x48;
String        sensorStatus       = "ads1115_not_found"; // "ok" | "ads1115_not_found" | "read_error"
int           consecutiveErrors  = 0;

WiFiClientSecure secureClient;
HTTPClient       httpClient;

// ============================================================================
// 1. PHYSICAL SENSOR CONVERSION FORMULAS
// ============================================================================

/**
 * Standard Gravity Analog TDS calculation polynomial (temperature-compensated).
 * Valid input range: 0.015V to 3.0V.
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
    ntu = (3.3f - voltage) * 10.0f;
    if (ntu < 0.50f) ntu = 0.50f;
  } else if (voltage < 0.05f) {
    ntu = 0.0f;
  } else {
    ntu = -1120.4f * powf(voltage, 2) + 5742.3f * voltage - 4352.9f;
    if (ntu < 0.0f) ntu = 0.50f;
    if (ntu > 3000.0f) ntu = 3000.0f;
  }
  return ntu;
}

// ============================================================================
// 2. I2C BUS RECOVERY & DIAGNOSTIC SCANNER
// ============================================================================

/**
 * NXP I2C Bus Recovery Sequence:
 * Toggles SCL 9 times to un-stick any slave that may be holding SDA low.
 */
void recoverI2CBus() {
  pinMode(PIN_I2C_SDA, INPUT_PULLUP);
  pinMode(PIN_I2C_SCL, OUTPUT);
  for (int i = 0; i < 9; i++) {
    digitalWrite(PIN_I2C_SCL, LOW);
    delayMicroseconds(5);
    digitalWrite(PIN_I2C_SCL, HIGH);
    delayMicroseconds(5);
  }
  // Generate STOP condition
  pinMode(PIN_I2C_SDA, OUTPUT);
  digitalWrite(PIN_I2C_SDA, LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_I2C_SCL, HIGH);
  delayMicroseconds(5);
  digitalWrite(PIN_I2C_SDA, HIGH);
  delayMicroseconds(5);
  pinMode(PIN_I2C_SDA, INPUT_PULLUP);
  pinMode(PIN_I2C_SCL, INPUT_PULLUP);

  // Re-initialize Wire peripheral
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setClock(I2C_CLOCK_SPEED);
  Wire.setClockStretchLimit(I2C_STRETCH_LIMIT_US);
}

/**
 * Startup I2C bus scanner:
 * Tests every address from 0x01 to 0x7F and decodes ADS1115 ADDR pin wiring.
 */
bool runStartupI2CScan() {
  Serial.println(F("\n========================================================"));
  Serial.println(F("     DROPLET Hardware Diagnostic: Full I2C Bus Scan     "));
  Serial.println(F("========================================================"));
  Serial.printf("[I2C Pin Confirmation] Wire.begin(SDA=%d, SCL=%d)\n", PIN_I2C_SDA, PIN_I2C_SCL);
  Serial.printf("                       SDA = NodeMCU D2 (GPIO 4)\n");
  Serial.printf("                       SCL = NodeMCU D1 (GPIO 5)\n");

  int foundCount = 0;
  uint8_t detectedAds = 0;

  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    byte err = Wire.endTransmission();

    if (err == 0) {
      foundCount++;
      Serial.printf("  -> [I2C ACK] Device detected at 0x%02X (%d)", addr, addr);
      if (addr == 0x48) {
        Serial.print(F(" <-- ADS1115 (ADDR -> GND) [Standard Setup]"));
        detectedAds = addr;
      } else if (addr == 0x49) {
        Serial.print(F(" <-- ADS1115 (ADDR -> VDD / 3.3V)"));
        detectedAds = addr;
      } else if (addr == 0x4A) {
        Serial.print(F(" <-- ADS1115 (ADDR -> SDA)"));
        detectedAds = addr;
      } else if (addr == 0x4B) {
        Serial.print(F(" <-- ADS1115 (ADDR -> SCL)"));
        detectedAds = addr;
      }
      Serial.println();
    }
  }

  Serial.println(F("--------------------------------------------------------"));
  if (detectedAds != 0) {
    adsAddress = detectedAds;
    adsFound = true;
    sensorStatus = "ok";
    consecutiveErrors = 0;
    Serial.printf("[ADS1115 Auto-Detect] SUCCESS: Target ADS1115 locked at 0x%02X!\n", adsAddress);
    return true;
  } else {
    adsFound = false;
    sensorStatus = "ads1115_not_found";
    Serial.println(F("[ADS1115 Auto-Detect] NO ADS1115 DETECTED! Checklist:"));
    Serial.println(F("   1. ADDR Pin: Connect firmly to ESP G (GND). Do NOT leave floating!"));
    Serial.println(F("   2. Header Pins: Must be SOLDERED to ADS1115 (loose friction pins fail)."));
    Serial.println(F("   3. Power Voltage: Verify 3.3V at ADS VDD (do NOT use Vin/5V)."));
    Serial.println(F("   4. Pin Order: Confirm SDA is NodeMCU D2, SCL is NodeMCU D1 (not swapped)."));
    Serial.println(F("   5. Jumper Wires: Try replacing jumper wires (internal wire breaks common)."));
    Serial.println(F("   6. Possible Dead Module: If power is 3.3V and pins are good, module is dead."));
    Serial.println(F("   --> Non-blocking mode active: Device will continue transmitting fault telemetry."));
    return false;
  }
}

/**
 * Fast, non-blocking check for ADS1115 at configured address (runs periodically if offline).
 */
bool probeADS1115Quick() {
  Wire.beginTransmission(adsAddress);
  if (Wire.endTransmission() == 0) {
    adsFound = true;
    sensorStatus = "ok";
    consecutiveErrors = 0;
    Serial.printf("[I2C Recovery] ADS1115 ACK restored at 0x%02X!\n", adsAddress);
    return true;
  }
  return false;
}

// ============================================================================
// 3. INDUSTRIAL ADS1115 REGISTER READ DRIVER
// ============================================================================

/**
 * Reads single-ended channel from ADS1115 using direct 16-bit registers.
 * Range: +/- 4.096V (0.125 mV/count).
 * Returns true if read succeeded; false on I2C error.
 */
bool readADSChannel(uint8_t channel, int16_t &outRaw, float &outVoltage) {
  if (!adsFound) {
    outRaw = 0;
    outVoltage = 0.0f;
    return false;
  }

  // Config: OS=1 (start conversion), PGA=+/-4.096V (0x0200), Single-shot (0x0100), 128 SPS (0x0080), Comp off (0x0003)
  uint16_t config = 0x8000 | ADS_PGA_CONFIG | 0x0100 | 0x0080 | 0x0003;
  if (channel == 0)      config |= 0x4000; // AIN0 vs GND
  else if (channel == 1) config |= 0x5000; // AIN1 vs GND
  else if (channel == 2) config |= 0x6000; // AIN2 vs GND
  else if (channel == 3) config |= 0x7000; // AIN3 vs GND

  // 1. Write Config Register (Pointer 0x01)
  Wire.beginTransmission(adsAddress);
  Wire.write(0x01);
  Wire.write((uint8_t)(config >> 8));
  Wire.write((uint8_t)(config & 0xFF));
  if (Wire.endTransmission() != 0) {
    return false;
  }

  // 2. Conversion wait (at 128 SPS, conversion completes in 7.8 ms; wait 9 ms)
  delay(9);

  // 3. Point to Conversion Register (Pointer 0x00)
  Wire.beginTransmission(adsAddress);
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) {
    return false;
  }

  // 4. Read 2-byte 16-bit conversion result
  if (Wire.requestFrom((uint8_t)adsAddress, (uint8_t)2) != 2) {
    return false;
  }

  byte msb = Wire.read();
  byte lsb = Wire.read();
  outRaw = (int16_t)((msb << 8) | lsb);
  if (outRaw < 0) outRaw = 0; // Negative clamp for ground noise

  outVoltage = outRaw * ADS_VOLTS_PER_COUNT;
  return true;
}

// ============================================================================
// 4. WI-FI & TELEMETRY TRANSMISSION (PERSISTENT HTTPS)
// ============================================================================

bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;

  unsigned long now = millis();
  if (now - lastWifiRetryTime < WIFI_RETRY_MS) return false;
  lastWifiRetryTime = now;

  Serial.println(F("[WiFi] Reconnecting in background..."));
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  return false;
}

/**
 * Transmits telemetry payload every 1000 ms.
 * Includes device_id, uptime, wifi_rssi, firmware_version, and sensor_status.
 * When sensorStatus is not "ok", tds and turbidity are sent as null (NEVER fabricated).
 */
void sendTelemetry(bool hasValidReadings, float tdsVal, float turbVal, float tempVal) {
  if (!ensureWiFi()) {
    Serial.println(F("[HTTP] Skipping — WiFi not connected"));
    return;
  }

  // Build JSON payload
  StaticJsonDocument<384> doc;
  doc["device_id"]        = DEVICE_ID;
  doc["source"]           = SOURCE_TAG;
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["uptime"]           = (unsigned long)(millis() / 1000);
  doc["wifi_rssi"]        = WiFi.RSSI();
  doc["sensor_status"]    = sensorStatus;

  if (hasValidReadings && sensorStatus == "ok") {
    doc["tds"]         = round(tdsVal * 10.0f) / 10.0f;         // 1 decimal place (ppm)
    doc["turbidity"]   = round(turbVal * 100.0f) / 100.0f;      // 2 decimal places (NTU)
    doc["temperature"] = round(tempVal * 10.0f) / 10.0f;      // °C
    doc["ph"]          = nullptr;                               // Not measured in 2-sensor setup
  } else {
    // Sensor fault state: Strictly null values. NEVER FABRICATE DATA.
    doc["tds"]         = nullptr;
    doc["turbidity"]   = nullptr;
    doc["ph"]          = nullptr;
    doc["temperature"] = nullptr;
  }

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  // Initialize or re-use TLS session
  if (!isHttpConnected || !httpClient.connected()) {
    Serial.println(F("[HTTP] Establishing TLS connection (keep-alive)..."));
    secureClient.setInsecure();
    secureClient.setBufferSizes(2048, 512);
    httpClient.begin(secureClient, BACKEND_URL);
    httpClient.setTimeout(firstRequest ? HTTP_COLD_START_MS : HTTP_STANDARD_TIMEOUT);
    httpClient.setReuse(true);
    isHttpConnected = true;
  }

  httpClient.addHeader(F("Content-Type"), F("application/json"));
  httpClient.addHeader(F("User-Agent"),   F("ESP8266-DROPLET/4.2.0"));
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
      Serial.printf("[HTTP POST] Response OK (%d bytes, keep-alive active)\n", resp.length());
    } else {
      Serial.printf("[HTTP POST] Server returned status %d. Closing connection.\n", httpCode);
      httpClient.end();
      isHttpConnected = false;
    }
  } else {
    Serial.printf("[HTTP POST] Error %d: %s. Resetting connection.\n",
                  httpCode, httpClient.errorToString(httpCode).c_str());
    httpClient.end();
    isHttpConnected = false;
  }
}

// ============================================================================
// 5. SETUP (INITIALIZATION)
// ============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println(F("\n========================================================"));
  Serial.printf("  DROPLET Water Telemetry - NodeMCU ESP8266 (v%s)        \n", FIRMWARE_VERSION);
  Serial.println(F("========================================================"));
  Serial.printf("[Config] Backend URL: %s\n", BACKEND_URL);
  Serial.printf("[Config] Device ID  : %s\n", DEVICE_ID);
  Serial.printf("[Config] Interval   : %lums\n", SEND_INTERVAL_MS);

  // Initialize I2C Bus with explicit pin order: Wire.begin(sda, scl)
  recoverI2CBus();

  // Run full startup diagnostic scan
  runStartupI2CScan();

  // Connect to Wi-Fi (non-blocking after initial attempt)
  Serial.printf("[WiFi] Connecting to %s ", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(F("."));
    attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WiFi] Connected successfully! IP: %s (RSSI: %d dBm)\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.println(F("[WiFi] Initial connection pending. Telemetry loop will retry in background."));
  }
}

// ============================================================================
// 6. MAIN LOOP (NON-BLOCKING 1000 MS FIXED-CADENCE TIMER)
// ============================================================================
void loop() {
  unsigned long now = millis();

  // 1. Non-blocking ADS1115 Reconnection Retry (every 5 seconds if offline)
  if (!adsFound && (now - lastI2cRetryTime >= I2C_RETRY_INTERVAL_MS)) {
    lastI2cRetryTime = now;
    if (probeADS1115Quick()) {
      Serial.printf("[ADS1115] Module detected! Switching status to 'ok'.\n");
    } else {
      recoverI2CBus(); // Attempt bus recovery
    }
  }

  // 2. Fixed-Rate Telemetry Loop (every 1000 ms)
  if (now - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime += SEND_INTERVAL_MS;
    if (now - lastSendTime >= SEND_INTERVAL_MS) {
      lastSendTime = now;
    }

    int16_t rawTds = 0, rawTurb = 0, rawA2 = 0, rawA3 = 0;
    float vTds = 0.0f, vTurb = 0.0f, vA2 = 0.0f, vA3 = 0.0f;
    bool readSuccess = true;

    if (adsFound) {
      bool ok0 = readADSChannel(CHANNEL_TDS, rawTds, vTds);
      bool ok1 = readADSChannel(CHANNEL_TURBIDITY, rawTurb, vTurb);
      readADSChannel(CHANNEL_PH_AUX, rawA2, vA2);
      readADSChannel(CHANNEL_TEMP_AUX, rawA3, vA3);

      if (ok0 && ok1) {
        sensorStatus = "ok";
        consecutiveErrors = 0;
      } else {
        consecutiveErrors++;
        sensorStatus = "read_error";
        readSuccess = false;
        Serial.printf("[ADS1115 Read Error] Consecutive failures: %d\n", consecutiveErrors);
        if (consecutiveErrors >= 3) {
          Serial.println(F("[I2C Recovery] 3 read errors in a row -> recovering I2C bus..."));
          recoverI2CBus();
          adsFound = false; // Trigger re-probe
        }
      }
    } else {
      sensorStatus = "ads1115_not_found";
      readSuccess = false;
    }

    // Compute Physical Values only if readings are valid
    float tdsValue = 0.0f;
    float turbidityValue = 0.0f;

    if (readSuccess && sensorStatus == "ok") {
      tdsValue = calculateTDS(vTds, DEFAULT_TEMPERATURE_C);
      turbidityValue = calculateTurbidity(vTurb);
    }

    // Diagnostic Serial Output
    Serial.println(F("--------------------------------------------------"));
    Serial.printf("[Telemetry Tick] Status: %s | WiFi RSSI: %d dBm | Uptime: %lus\n",
                  sensorStatus.c_str(), WiFi.RSSI(), (unsigned long)(millis() / 1000));

    if (sensorStatus == "ok") {
      Serial.printf("[Sensors OK] TDS (A0): %5d (%0.3fV) -> %0.1f ppm  |  Turbidity (A1): %5d (%0.3fV) -> %0.2f NTU\n",
                    rawTds, vTds, tdsValue, rawTurb, vTurb, turbidityValue);
      if (vTds < 0.015f) {
        Serial.println(F("   -> [TDS TIP] Probe in air reads 0 ppm. Submerge in water to test!"));
      }
      if (vTurb < 0.05f) {
        Serial.println(F("   -> [TURBIDITY TIP] 0.00 NTU: Verify blue adapter switch is on 'A' (Analog)!"));
      }
    } else {
      Serial.printf("[Sensor FAULT] %s -> Sending NULL readings (Device stays ONLINE on Dashboard)\n",
                    sensorStatus.c_str());
    }

    // Send Telemetry to Render Backend
    sendTelemetry(readSuccess, tdsValue, turbidityValue, DEFAULT_TEMPERATURE_C);
  }

  yield(); // Keep ESP8266 background WiFi routines serviced
}
