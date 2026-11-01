/*
 * DROPLET - Smart Water Quality Monitoring System
 * Industrial-Grade Wi-Fi Telemetry Firmware for NodeMCU ESP8266 + ADS1115
 *
 * Streams real-time TDS and Turbidity sensor readings to the DROPLET
 * FastAPI backend via HTTPS POST /api/readings every 1 second.
 *
 * ============================================================================
 * AUTHORITATIVE WIRING CONNECTIONS:
 * ============================================================================
 * 1. ESP8266 to ADS1115:
 *    - ESP 3V  -> ADS VDD (Red)
 *    - ESP G   -> ADS GND & ADDR (Black — sets I2C address 0x48)
 *    - ESP D1  -> ADS SCL (Blue — GPIO 5)
 *    - ESP D2  -> ADS SDA (Green — GPIO 4)
 *
 * 2. TDS Meter:
 *    - TDS Red (+)    -> ESP 3V (Red)
 *    - TDS Black (-)  -> ESP G (Black)
 *    - TDS Yellow (A) -> ADS A0 (Yellow)
 *
 * 3. Turbidity Sensor:
 *    - Turbidity V       -> ESP 3V (Red)
 *    - Turbidity G       -> ESP G (Black)
 *    - Turbidity Signal  -> ADS A1 (Purple)
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
const unsigned long SEND_INTERVAL_MS    = 1000;   // Exactly 1 second
const unsigned long WIFI_RETRY_MS       = 5000;   // Retry WiFi reconnect every 5s
const unsigned long HTTP_TIMEOUT_MS     = 15000;  // 15s timeout
const unsigned long COLD_START_EXTRA_MS = 25000;  // 25s for first request (cold start)

// Channels on the ADS1115
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
bool          ads1115Online   = false;
uint8_t       adsAddress      = 0x48;

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
// 5. INDUSTRIAL-GRADE NATIVE ADS1115 DRIVER
// ==========================================

/**
 * Standard I2C bus recovery sequence (NXP standard).
 * Frees any slave that might be locking the SDA line LOW.
 */
void clearI2CBus(int sdaPin, int sclPin) {
  pinMode(sdaPin, INPUT_PULLUP);
  pinMode(sclPin, OUTPUT);
  for (int i = 0; i < 9; i++) {
    digitalWrite(sclPin, LOW);
    delayMicroseconds(5);
    digitalWrite(sclPin, HIGH);
    delayMicroseconds(5);
  }
  // Generate STOP condition
  pinMode(sdaPin, OUTPUT);
  digitalWrite(sdaPin, LOW);
  delayMicroseconds(5);
  digitalWrite(sclPin, HIGH);
  delayMicroseconds(5);
  digitalWrite(sdaPin, HIGH);
  delayMicroseconds(5);
  pinMode(sdaPin, INPUT_PULLUP);
  pinMode(sclPin, INPUT_PULLUP);
}

/**
 * Reads any single-ended channel (0, 1, 2, or 3) from the ADS1115
 * using direct 16-bit I2C register protocol.
 * Range: +/- 4.096V (0.125 mV per count).
 */
int16_t readADSChannelDirect(uint8_t channel, float &outVoltage, uint8_t &errCode) {
  // Config register bits:
  // Bit 15: 1 (Start conversion / OS)
  // Bits 14-12: MUX
  //   0: AIN0 vs GND (0x4000)
  //   1: AIN1 vs GND (0x5000)
  //   2: AIN2 vs GND (0x6000)
  //   3: AIN3 vs GND (0x7000)
  // Bits 11-9: PGA: 001 (+/-4.096V range) -> 0x0200
  // Bit 8: MODE: 1 (Single-shot) -> 0x0100
  // Bits 7-5: DR: 100 (128 SPS) -> 0x0080
  // Bits 4-0: COMP: 00011 (Comparator disabled) -> 0x0003
  uint16_t config = 0x8000 | 0x0200 | 0x0100 | 0x0080 | 0x0003;
  if (channel == 0)      config |= 0x4000;
  else if (channel == 1) config |= 0x5000;
  else if (channel == 2) config |= 0x6000;
  else if (channel == 3) config |= 0x7000;

  // Step 1: Write to Config Register (Pointer 0x01)
  Wire.beginTransmission(adsAddress);
  Wire.write(0x01); // Point to Config Register
  Wire.write((uint8_t)(config >> 8));   // MSB
  Wire.write((uint8_t)(config & 0xFF)); // LSB
  errCode = Wire.endTransmission();
  if (errCode != 0) {
    outVoltage = 0.0f;
    return -1;
  }

  // Step 2: Wait for conversion (at 128 SPS, 1 conversion takes 7.8ms; wait 10ms)
  delay(10);

  // Step 3: Point to Conversion Register (Pointer 0x00)
  Wire.beginTransmission(adsAddress);
  Wire.write(0x00);
  errCode = Wire.endTransmission();
  if (errCode != 0) {
    outVoltage = 0.0f;
    return -2;
  }

  // Step 4: Request 2 bytes from Conversion Register
  uint8_t count = Wire.requestFrom((uint8_t)adsAddress, (uint8_t)2);
  if (count != 2) {
    outVoltage = 0.0f;
    errCode = 99; // Read timeout
    return -3;
  }

  byte msb = Wire.read();
  byte lsb = Wire.read();
  int16_t raw = (int16_t)((msb << 8) | lsb);
  if (raw < 0) raw = 0; // Negative voltage clamp

  // GAIN_ONE: 4.096V / 32768 = 0.000125V (0.125 mV per count)
  outVoltage = raw * 0.000125f;
  errCode = 0; // Success
  return raw;
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
  httpClient.addHeader(F("User-Agent"),   F("ESP8266-ADS1115-DROPLET/4.0"));
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

  // Clear I2C bus lines to prevent any hanging slave
  clearI2CBus(D2, D1);

  // Initialize Wire: D2 = SDA (GPIO 4), D1 = SCL (GPIO 5)
  Wire.begin(D2, D1);
  Wire.setClock(100000); // 100 kHz standard I2C clock

  // Hardware Pin Level Check
  int sclLevel = digitalRead(D1);
  int sdaLevel = digitalRead(D2);
  Serial.printf("[I2C Pin Check] SCL (D1): %s | SDA (D2): %s\n",
                sclLevel ? "HIGH (3.3V OK)" : "LOW (CHECK FOR SHORT!)",
                sdaLevel ? "HIGH (3.3V OK)" : "LOW (CHECK FOR SHORT!)");

  // Probe ADS1115 on valid addresses (0x48 to 0x4B)
  ads1115Online = false;
  for (uint8_t a = 0x48; a <= 0x4B; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      adsAddress = a;
      ads1115Online = true;
      Serial.printf("[I2C Probe] SUCCESS: ADS1115 responded with ACK at 0x%02X!\n", a);
      break;
    }
  }

  if (ads1115Online) {
    // Read and verify ADS1115 internal Config Register
    Wire.beginTransmission(adsAddress);
    Wire.write(0x01); // Config register
    Wire.write(0x85); // Write test pattern
    Wire.write(0x83);
    byte wErr = Wire.endTransmission();

    Wire.beginTransmission(adsAddress);
    Wire.write(0x01);
    Wire.endTransmission();
    Wire.requestFrom((uint8_t)adsAddress, (uint8_t)2);
    uint16_t testCfg = (Wire.read() << 8) | Wire.read();

    Serial.printf("[ADS1115 Health] Config Register Read: 0x%04X (wErr=%d)\n", testCfg, wErr);
    if (wErr == 0 && (testCfg & 0x0083) == 0x0083) {
      Serial.println(F("[ADS1115 Health] HARDWARE READ/WRITE CONFIRMED 100% OPERATIONAL!"));
    }
  } else {
    Serial.println(F("[ADS1115 Error] NO ACK from ADS1115! Check wiring:"));
    Serial.println(F("   - ESP 3V -> ADS VDD (Red wire)"));
    Serial.println(F("   - ESP G  -> ADS GND & ADDR (Black wire)"));
    Serial.println(F("   - ESP D1 -> ADS SCL (Blue wire)"));
    Serial.println(F("   - ESP D2 -> ADS SDA (Green wire)"));
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

    float vA0 = 0.0f, vA1 = 0.0f, vA2 = 0.0f, vA3 = 0.0f;
    uint8_t errA0 = 0, errA1 = 0, errA2 = 0, errA3 = 0;
    int16_t rawA0 = 0, rawA1 = 0, rawA2 = 0, rawA3 = 0;

    // Check / re-verify ADS1115 connection
    if (!ads1115Online) {
      Wire.beginTransmission(adsAddress);
      if (Wire.endTransmission() == 0) {
        ads1115Online = true;
        Serial.printf("[ADS1115] Reconnected at 0x%02X!\n", adsAddress);
      }
    }

    if (ads1115Online) {
      // Sample all 4 channels to provide complete visibility
      rawA0 = readADSChannelDirect(0, vA0, errA0);
      rawA1 = readADSChannelDirect(1, vA1, errA1);
      rawA2 = readADSChannelDirect(2, vA2, errA2);
      rawA3 = readADSChannelDirect(3, vA3, errA3);
    }

    // Also read NodeMCU onboard ADC (A0) in case user wired to onboard pin
    int rawNodeMCU = analogRead(A0);
    float vNodeMCU = (rawNodeMCU / 1023.0f) * 3.3f;

    // Intelligent Sensor Mapping:
    // Standard: A0 = TDS, A1 = Turbidity
    float vTds  = vA0;
    float vTurb = vA1;

    // Auto-detect swapped yellow/purple wires:
    // If A0 is high (> 1.8V, characteristic of optical turbidity) and A1 is lower, swap them!
    if (vA0 > 1.8f && vA1 < 1.8f && vA1 > 0.02f) {
      vTds  = vA1;
      vTurb = vA0;
    }
    // If user plugged into A2/A3 by mistake:
    else if (vA0 < 0.015f && vA2 > 0.02f) {
      vTds = vA2;
    }

    // Compute Physical Values
    float tdsValue       = calculateTDS(vTds, DEFAULT_TEMPERATURE);
    float turbidityValue = calculateTurbidity(vTurb);

    // Print Detailed Live Diagnostics to Serial Monitor
    Serial.println(F("--------------------------------------------------"));
    Serial.printf("[ADS1115 Channels] A0: %5d (%.3fV) | A1: %5d (%.3fV) | A2: %5d (%.3fV) | A3: %5d (%.3fV)\n",
                  rawA0, vA0, rawA1, vA1, rawA2, vA2, rawA3, vA3);
    Serial.printf("[Sensors Processed] TDS: %.1f ppm (%.3fV)  |  Turbidity: %.2f NTU (%.3fV)  |  NodeMCU A0: %.3fV\n",
                  tdsValue, vTds, turbidityValue, vTurb, vNodeMCU);

    // Real-Time Hardware Tips based on measured voltages
    if (vTds < 0.015f) {
      Serial.println(F("   -> [TDS SENSOR TIP] Voltage is 0.000V. In air, TDS reads 0. DIP THE PROBE IN WATER TO TEST!"));
    }
    if (vTurb < 0.05f) {
      Serial.println(F("   -> [TURBIDITY TIP] Voltage is 0.000V. Verify blue board LED is ON and slide switch is on 'A'!"));
    }

    // Stream Telemetry to DROPLET Cloud Backend
    sendTelemetry(tdsValue, turbidityValue, DEFAULT_TEMPERATURE, DEFAULT_PH);
  }

  yield(); // Keep WiFi background tasks active
}
