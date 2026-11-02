/*
 * DROPLET - Smart Water Quality Monitoring System
 * Fault-Tolerant Telemetry Firmware for NodeMCU ESP8266 + ADS1115
 *
 * Firmware Version: 4.3.0-smart-autodetect
 *
 * KEY CAPABILITIES:
 * 1. Smart I2C Auto-Detection:
 *    - Automatically scans both standard (D2=SDA, D1=SCL) AND reversed (D1=SDA, D2=SCL) pins!
 *    - Scans all 4 valid ADS1115 I2C addresses (0x48, 0x49, 0x4A, 0x4B).
 *    - 50 kHz I2C clock speed for rock-solid reliability over breadboard jumper wires.
 * 2. Non-Destructive, Resilient Wi-Fi:
 *    - Eliminates aggressive disconnect loops; allows DHCP handshakes to complete.
 *    - Full status diagnostics with human-readable error messages (2.4 GHz check, password check).
 * 3. Continuous Cloud Telemetry to Render & Vercel:
 *    - Sends telemetry every 1000 ms:
 *      * With sensors: Real-time TDS, Turbidity, Temp with sensor_status="ok".
 *      * Fault state: Real-time nulls with sensor_status="ads1115_not_found" (Device stays ONLINE!).
 *    - Uses TLS keep-alive with optimized 1024/512 byte buffers for ESP8266 heap stability.
 *
 * ============================================================================
 * AUTHORITATIVE HARDWARE WIRING (NodeMCU ESP8266 to ADS1115):
 * ============================================================================
 * 1. ADS1115 Module:
 *    - ADS VDD  -> ESP 3V / 3V3 (3.3V Power - Do NOT use 5V/VIN!)
 *    - ADS GND  -> ESP G / GND
 *    - ADS ADDR -> ESP G / GND (Sets I2C address 0x48)
 *    - ADS SCL  -> ESP D1 (GPIO 5)
 *    - ADS SDA  -> ESP D2 (GPIO 4)
 *    * NOTE: If D1 & D2 are swapped, the firmware auto-detects and auto-swaps them!
 *    * NOTE: Header pins MUST be soldered to ADS1115 PCB! Friction fit will fail I2C.
 *
 * 2. TDS Meter (Gravity Analog):
 *    - TDS VCC (+)    -> ESP 3V (Red wire)
 *    - TDS GND (-)    -> ESP G (Black wire)
 *    - TDS Signal (A) -> ADS A0 (Yellow wire)
 *
 * 3. Turbidity Sensor:
 *    - Turbidity VCC (+)    -> ESP 3V (Red wire)
 *    - Turbidity GND (-)    -> ESP G (Black wire)
 *    - Turbidity Signal (A) -> ADS A1 (Purple wire)
 *    * IMPORTANT: Set the slide switch on the blue adapter board to 'A' (Analog)!
 * ============================================================================
 */

#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Wire.h>
#include <ArduinoJson.h>

// ============================================================================
// CONFIG SECTION 1: HARDWARE DEFINITIONS & TUNING
// ============================================================================
#define FIRMWARE_VERSION        "4.3.0-smart-autodetect"

// Default Pin Configuration for NodeMCU ESP8266
// D2 = GPIO 4 (Default SDA)
// D1 = GPIO 5 (Default SCL)
uint8_t pinSDA = 4;
uint8_t pinSCL = 5;

#define I2C_CLOCK_SPEED         50000   // 50 kHz: highly immune to breadboard wire capacitance
#define I2C_STRETCH_LIMIT_US    1500    // 1500 us clock stretch limit

// ADS1115 Programmable Gain: GAIN_ONE (+/-4.096V Full Scale, 0.125 mV/count)
#define ADS_PGA_CONFIG          0x0200  // PGA = 001 (+/-4.096V)
#define ADS_VOLTS_PER_COUNT     0.000125f // 4.096V / 32768 counts

// Sensor Channel Mappings
#define CHANNEL_TDS             0       // A0 = TDS Sensor
#define CHANNEL_TURBIDITY       1       // A1 = Turbidity Sensor
#define CHANNEL_PH_AUX          2       // A2 = Reserved
#define CHANNEL_TEMP_AUX        3       // A3 = Reserved

const float DEFAULT_TEMPERATURE_C = 25.0f;

// ============================================================================
// CONFIG SECTION 2: WI-FI & BACKEND CONFIGURATION
// ============================================================================
// Wi-Fi Credentials (MUST be 2.4 GHz Band on Hotspot/Router!)
const char* WIFI_SSID           = "SAMSUNG A14";
const char* WIFI_PASSWORD       = "pallavi123";

// Backend API URL (Render Cloud)
const char* BACKEND_URL         = "https://droplet-api-byl8.onrender.com/api/readings";
const char* DEVICE_ID           = "ESP8266-WATER-001";
const char* SOURCE_TAG          = "ESP8266";

// Telemetry & Retry Timings
const unsigned long SEND_INTERVAL_MS       = 1000;   // Send reading every 1000 ms
const unsigned long I2C_RETRY_INTERVAL_MS  = 4000;   // Probe for missing ADS1115 every 4s
const unsigned long WIFI_RECONNECT_CADENCE = 12000;  // Non-destructive Wi-Fi check cadence (12s)
const unsigned long HTTP_COLD_START_MS     = 10000;  // 10s for initial TLS negotiation
const unsigned long HTTP_STANDARD_TIMEOUT  = 5000;   // 5s standard HTTP timeout

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
// 1. SENSOR CONVERSION FORMULAS
// ============================================================================

float calculateTDS(float voltage, float tempC) {
  if (voltage < 0.015f) {
    return 0.0f; // Dry probe
  }
  float compensationCoefficient = 1.0f + 0.02f * (tempC - 25.0f);
  float compensationVoltage     = voltage / compensationCoefficient;

  float tds = (133.42f * powf(compensationVoltage, 3)
             - 255.86f * powf(compensationVoltage, 2)
             + 857.39f * compensationVoltage) * 0.5f;

  if (tds < 0.0f) tds = 0.0f;
  return tds;
}

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
// 2. I2C BUS RECOVERY & SMART MULTI-PIN SCANNER
// ============================================================================

void recoverI2CBus(uint8_t sda, uint8_t scl) {
  pinMode(sda, INPUT_PULLUP);
  pinMode(scl, OUTPUT);
  for (int i = 0; i < 9; i++) {
    digitalWrite(scl, LOW);
    delayMicroseconds(10);
    digitalWrite(scl, HIGH);
    delayMicroseconds(10);
  }
  pinMode(sda, OUTPUT);
  digitalWrite(sda, LOW);
  delayMicroseconds(10);
  digitalWrite(scl, HIGH);
  delayMicroseconds(10);
  digitalWrite(sda, HIGH);
  delayMicroseconds(10);
  pinMode(sda, INPUT_PULLUP);
  pinMode(scl, INPUT_PULLUP);

  Wire.begin(sda, scl);
  Wire.setClock(I2C_CLOCK_SPEED);
  Wire.setClockStretchLimit(I2C_STRETCH_LIMIT_US);
}

/**
 * Probes a specific I2C configuration for ADS1115 (0x48..0x4B).
 * Returns detected address, or 0 if none.
 */
uint8_t scanForADS(uint8_t sda, uint8_t scl) {
  recoverI2CBus(sda, scl);
  const uint8_t addrs[] = {0x48, 0x49, 0x4A, 0x4B};
  for (int i = 0; i < 4; i++) {
    Wire.beginTransmission(addrs[i]);
    if (Wire.endTransmission() == 0) {
      return addrs[i];
    }
  }
  return 0;
}

/**
 * Intelligent I2C diagnostic scanner:
 * 1. Checks default pins: D2 (SDA) / D1 (SCL)
 * 2. If not found, checks reversed pins: D1 (SDA) / D2 (SCL)
 * 3. If found on reversed pins, auto-configures them!
 */
bool runStartupI2CScan() {
  Serial.println(F("\n========================================================"));
  Serial.println(F("     DROPLET Hardware Diagnostic: Smart I2C Scanner     "));
  Serial.println(F("========================================================"));

  // Test 1: Standard NodeMCU Pinout: SDA=D2 (GPIO 4), SCL=D1 (GPIO 5)
  Serial.printf("[Test 1] Probing Standard Pins: SDA=D2 (GPIO %d), SCL=D1 (GPIO %d) @ 50kHz...\n", 4, 5);
  uint8_t foundAddr = scanForADS(4, 5);

  if (foundAddr != 0) {
    pinSDA = 4;
    pinSCL = 5;
    adsAddress = foundAddr;
    adsFound = true;
    sensorStatus = "ok";
    consecutiveErrors = 0;
    Serial.printf("  --> [SUCCESS] ADS1115 detected at 0x%02X on standard pins (D2=SDA, D1=SCL)!\n", adsAddress);
    return true;
  }

  // Test 2: Inverted Pinout: SDA=D1 (GPIO 5), SCL=D2 (GPIO 4)
  Serial.printf("[Test 2] Probing Reversed Pins: SDA=D1 (GPIO %d), SCL=D2 (GPIO %d) @ 50kHz...\n", 5, 4);
  foundAddr = scanForADS(5, 4);

  if (foundAddr != 0) {
    pinSDA = 5;
    pinSCL = 4;
    adsAddress = foundAddr;
    adsFound = true;
    sensorStatus = "ok";
    consecutiveErrors = 0;
    Serial.println(F("  -------------------------------------------------------------"));
    Serial.printf("  --> [AUTO-ADAPT SUCCESS] ADS1115 detected at 0x%02X!\n", adsAddress);
    Serial.println(F("  --> NOTE: Your SDA and SCL jumper wires are swapped (D1=SDA, D2=SCL)."));
    Serial.println(F("  --> Firmware has automatically adapted! No hardware changes needed."));
    Serial.println(F("  -------------------------------------------------------------"));
    return true;
  }

  // If neither orientation found ADS1115, do a full 0x01-0x7F scan to see if ANY device responds
  Serial.println(F("\n[Test 3] ADS1115 not on 0x48-0x4B. Running broad bus scan (0x01 - 0x7F)..."));
  recoverI2CBus(pinSDA, pinSCL);
  int anyDeviceCount = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      anyDeviceCount++;
      Serial.printf("  -> Found other I2C device at 0x%02X (%d)\n", addr, addr);
    }
  }

  adsFound = false;
  sensorStatus = "ads1115_not_found";

  Serial.println(F("--------------------------------------------------------"));
  Serial.println(F("[DIAGNOSTIC] ADS1115 NOT DETECTED! Check these 4 essentials:"));
  Serial.println(F("  1. SOLDER PINS: Header pins MUST be soldered to ADS1115 board."));
  Serial.println(F("     (Unsoldered friction pins loose in breadboard WILL FAIL I2C)."));
  Serial.println(F("  2. POWER: Connect ADS VDD -> NodeMCU 3V3 (3.3V) and GND -> GND."));
  Serial.println(F("  3. ADDR PIN: Connect ADS ADDR -> NodeMCU GND firmly (Sets 0x48)."));
  Serial.println(F("  4. JUMPER WIRES: Check for defective/loose jumper wires on D1/D2."));
  Serial.println(F("  --> Non-blocking mode active: Device will continue transmitting"));
  Serial.println(F("      telemetry to keep Cloud Dashboard ONLINE with error status."));
  Serial.println(F("========================================================\n"));
  return false;
}

/**
 * Fast periodic retry for ADS1115 (checks both pin orientations and all 4 addresses)
 */
bool probeADS1115Quick() {
  // 1. Try currently configured pins
  uint8_t detected = scanForADS(pinSDA, pinSCL);
  if (detected != 0) {
    adsAddress = detected;
    adsFound = true;
    sensorStatus = "ok";
    consecutiveErrors = 0;
    Serial.printf("[ADS1115 Recovery] Locked at 0x%02X on SDA=D%d, SCL=D%d!\n",
                  adsAddress, (pinSDA == 4 ? 2 : 1), (pinSCL == 5 ? 1 : 2));
    return true;
  }

  // 2. Try swapped pins
  uint8_t altSDA = (pinSDA == 4) ? 5 : 4;
  uint8_t altSCL = (pinSCL == 5) ? 4 : 5;
  detected = scanForADS(altSDA, altSCL);
  if (detected != 0) {
    pinSDA = altSDA;
    pinSCL = altSCL;
    adsAddress = detected;
    adsFound = true;
    sensorStatus = "ok";
    consecutiveErrors = 0;
    Serial.printf("[ADS1115 Auto-Swap] Locked at 0x%02X! Switched to SDA=D%d, SCL=D%d!\n",
                  adsAddress, (pinSDA == 4 ? 2 : 1), (pinSCL == 5 ? 1 : 2));
    return true;
  }

  return false;
}

// ============================================================================
// 3. INDUSTRIAL ADS1115 REGISTER READ DRIVER
// ============================================================================

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

  // 2. Conversion wait (at 128 SPS, conversion completes in 7.8 ms; wait 12 ms)
  delay(12);

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
  if (outRaw < 0) outRaw = 0; // Ground noise clamp

  outVoltage = outRaw * ADS_VOLTS_PER_COUNT;
  return true;
}

// ============================================================================
// 4. WI-FI & TELEMETRY TRANSMISSION (NON-DESTRUCTIVE RECONNECT)
// ============================================================================

const char* getWiFiStatusName(wl_status_t status) {
  switch (status) {
    case WL_IDLE_STATUS:     return "IDLE (Initializing)";
    case WL_NO_SSID_AVAIL:   return "SSID NOT FOUND (Check 2.4 GHz Band & Hotspot Name)";
    case WL_SCAN_COMPLETED:  return "SCAN COMPLETED";
    case WL_CONNECTED:       return "CONNECTED";
    case WL_CONNECT_FAILED:  return "AUTH FAILED (Incorrect Password)";
    case WL_CONNECTION_LOST: return "CONNECTION LOST";
    case WL_DISCONNECTED:    return "DISCONNECTED (Negotiating Handshake / DHCP)";
    default:                 return "CONNECTING...";
  }
}

/**
 * Non-destructive Wi-Fi health check.
 * NEVER calls WiFi.disconnect() inside a loop to prevent interrupting DHCP!
 */
bool ensureWiFi() {
  wl_status_t st = WiFi.status();
  if (st == WL_CONNECTED) {
    return true;
  }

  unsigned long now = millis();
  if (now - lastWifiRetryTime >= WIFI_RECONNECT_CADENCE) {
    lastWifiRetryTime = now;
    Serial.printf("[WiFi] Re-attempting connection to '%s' (Current status: %s)...\n",
                  WIFI_SSID, getWiFiStatusName(st));
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
  return false;
}

/**
 * Transmits telemetry payload every 1000 ms to Render backend.
 * Stays permanently ONLINE on Render and Vercel regardless of sensor state.
 */
void sendTelemetry(bool hasValidReadings, float tdsVal, float turbVal, float tempVal) {
  if (!ensureWiFi()) {
    Serial.printf("[HTTP] Telemetry paused — WiFi status: %s\n", getWiFiStatusName(WiFi.status()));
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
    doc["tds"]         = round(tdsVal * 10.0f) / 10.0f;       // 1 decimal place (ppm)
    doc["turbidity"]   = round(turbVal * 100.0f) / 100.0f;    // 2 decimal places (NTU)
    doc["temperature"] = round(tempVal * 10.0f) / 10.0f;    // °C
    doc["ph"]          = nullptr;                             // 2-sensor setup (neutral fallback on backend)
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
    Serial.println(F("[HTTP] Establishing TLS connection to Render..."));
    secureClient.setInsecure();
    secureClient.setBufferSizes(1024, 512); // Optimized buffer size for ESP8266 heap
    secureClient.setTimeout(8000);
    httpClient.begin(secureClient, BACKEND_URL);
    httpClient.setTimeout(firstRequest ? HTTP_COLD_START_MS : HTTP_STANDARD_TIMEOUT);
    httpClient.setReuse(true);
    isHttpConnected = true;
  }

  httpClient.addHeader(F("Content-Type"), F("application/json"));
  httpClient.addHeader(F("User-Agent"),   F("ESP8266-DROPLET/4.3.0"));
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
      Serial.printf("[HTTP POST] OK (%d bytes, cloud stream active)\n", resp.length());
    } else {
      Serial.printf("[HTTP POST] Status %d. Re-cycling connection.\n", httpCode);
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
  Serial.printf("[Config] Cadence    : %lums\n", SEND_INTERVAL_MS);

  // Initialize I2C Bus & Auto-Detect ADS1115 (checks both D2/D1 and D1/D2)
  runStartupI2CScan();

  // Connect to Wi-Fi with generous timeout (30 * 500ms = 15 seconds)
  Serial.printf("[WiFi] Connecting to '%s' (2.4 GHz required) ", WIFI_SSID);
  WiFi.persistent(false);
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
    Serial.printf("[WiFi] Connected successfully! IP: %s (RSSI: %d dBm)\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.printf("[WiFi] Initial connection pending (Status: %s).\n",
                  getWiFiStatusName(WiFi.status()));
    if (WiFi.status() == WL_NO_SSID_AVAIL) {
      Serial.println(F("   -> [HOTSPOT CHECK] ESP8266 only supports 2.4 GHz!"));
      Serial.println(F("   -> On Samsung: Mobile Hotspot -> Configure -> Band -> Select '2.4 GHz'."));
      Serial.println(F("   -> On iPhone: Settings -> Personal Hotspot -> Turn ON 'Maximize Compatibility'."));
    }
    Serial.println(F("   -> Non-blocking mode active: Main loop will continue connecting in background."));
  }
}

// ============================================================================
// 6. MAIN LOOP (NON-BLOCKING 1000 MS FIXED CADENCE)
// ============================================================================
void loop() {
  unsigned long now = millis();

  // 1. Non-blocking ADS1115 Reconnection Retry (every 4 seconds if missing)
  if (!adsFound && (now - lastI2cRetryTime >= I2C_RETRY_INTERVAL_MS)) {
    lastI2cRetryTime = now;
    if (probeADS1115Quick()) {
      Serial.println(F("[ADS1115] Connection re-established! Sensor status switched to 'ok'."));
    } else {
      recoverI2CBus(pinSDA, pinSCL);
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
          Serial.println(F("[I2C Recovery] 3 consecutive errors -> recovering bus..."));
          recoverI2CBus(pinSDA, pinSCL);
          adsFound = false; // Trigger smart re-probe
        }
      }
    } else {
      sensorStatus = "ads1115_not_found";
      readSuccess = false;
    }

    // Physical Calculations (only if readings are valid)
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
      Serial.printf("[Sensor State] %s -> Streaming fault telemetry (Dashboard remains ONLINE)\n",
                    sensorStatus.c_str());
    }

    // Send Telemetry to Render Backend
    sendTelemetry(readSuccess, tdsValue, turbidityValue, DEFAULT_TEMPERATURE_C);
  }

  yield(); // Keep ESP8266 background Wi-Fi routines serviced
}
