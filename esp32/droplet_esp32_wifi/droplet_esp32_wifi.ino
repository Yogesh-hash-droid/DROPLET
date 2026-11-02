/*
 * ============================================================================
 * DROPLET — Smart Water Quality Monitoring System
 * Wi-Fi Cloud Telemetry Firmware (ESP32 / ESP8266)
 * ============================================================================
 * Based on the authoritative sensor and calibration logic from:
 *   water_quality_uno_final.ino
 *
 * ⚠️ Educational Prototype Disclaimer:
 * This system is for learning and demonstration purposes only.
 * TDS readings are NOT temperature-compensated.
 * Does NOT certify water potability or safety.
 *
 * SENSORS:
 *   1. Analog TDS Module (Gravity / Keyestudio)
 *   2. Analog Turbidity Sensor Module (Gravity / TSW-20M / SEN0189)
 *   * No pH sensor, no temperature sensor in this setup.
 *
 * HARDWARE WIRING (ESP32):
 *   --------------------------------------------------------------------------
 *   Sensor Wire         ESP32 Pin          Notes
 *   --------------------------------------------------------------------------
 *   TDS red (+)         GPIO 23            Powered ONLY while reading (prevents
 *                                          interference and probe degradation)
 *   TDS black (-)       GND                Common Ground
 *   TDS yellow (Signal) GPIO 34 (ADC1_CH6) Analog input (safe with Wi-Fi)
 *   Turbidity VCC       5V (or 3.3V)       Continuous power
 *   Turbidity GND       GND                Common Ground
 *   Turbidity Signal    GPIO 35 (ADC1_CH7) Analog input (safe with Wi-Fi)
 *                       * Adapter switch set to 'A' (Analog)!
 *   --------------------------------------------------------------------------
 *
 * SERIAL MONITOR CALIBRATION COMMANDS (115200 baud, line ending: Newline):
 *   tds <ppm>   -> Place probe in standard solution (e.g. `tds 500`) -> saves TDS factor
 *   clear       -> Place turbidity probe in clean water -> saves 0 NTU clear-point
 *   turb <ntu>  -> Place turbidity probe in known NTU solution (e.g. `turb 100`) -> saves span
 *   show        -> Display current calibration stored in EEPROM/Flash
 *   reset       -> Erase saved calibration back to factory defaults
 * ============================================================================
 */

#if defined(ESP32)
  #include <WiFi.h>
  #include <HTTPClient.h>
  #include <WiFiClientSecure.h>
  #define BOARD_NAME "ESP32"
  #define DEFAULT_DEVICE_ID "ESP32-WATER-001"
  #define DEFAULT_SOURCE "ESP32"
  const uint8_t PIN_TDS_PWR  = 23;   // Digital pin: powers TDS module only during read
  const uint8_t PIN_TDS_ADC  = 34;   // ADC1_CH6 (input only, unaffected by Wi-Fi)
  const uint8_t PIN_TURB_ADC = 35;   // ADC1_CH7 (input only, unaffected by Wi-Fi)
  const float   ADC_VREF     = 3.3f; // ESP32 operating voltage
  const float   ADC_MAX      = 4095.0f; // 12-bit ADC
#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266HTTPClient.h>
  #include <WiFiClientSecure.h>
  #define BOARD_NAME "ESP8266"
  #define DEFAULT_DEVICE_ID "ESP8266-WATER-001"
  #define DEFAULT_SOURCE "ESP8266"
  const uint8_t PIN_TDS_PWR  = 14;   // D5 / GPIO 14
  const uint8_t PIN_TDS_ADC  = A0;   // ESP8266 single analog pin
  const uint8_t PIN_TURB_ADC = A0;
  const float   ADC_VREF     = 3.3f;
  const float   ADC_MAX      = 1023.0f; // 10-bit ADC
#else
  #error "This firmware is designed for ESP32 or ESP8266."
#endif

#include <Wire.h>
#include <EEPROM.h>
#include <ArduinoJson.h>

// ============================================================================
// CONFIGURATION: WI-FI & CLOUD BACKEND
// ============================================================================
// Wi-Fi Credentials (supports 2.4 GHz Mobile Hotspots and Home Routers)
const char* WIFI_SSID       = "Vgp";
const char* WIFI_PASSWORD   = "guru2006";

// DROPLET Cloud API Endpoint
const char* BACKEND_URL     = "https://droplet-api-byl8.onrender.com/api/readings";
const char* DEVICE_ID       = DEFAULT_DEVICE_ID;
const char* SOURCE_TAG      = DEFAULT_SOURCE;
const char* FIRMWARE_VER    = "5.0.0-dual-sensor";

// Sampling & Telemetry Intervals
const int           SAMPLES             = 30;     // Noise reduction sample count
const unsigned long INTERVAL_MS         = 2000;   // Ingestion rate: every 2 seconds
const unsigned long WIFI_CHECK_INTERVAL = 10000;  // Non-blocking Wi-Fi monitor (10s)

// ============================================================================
// CALIBRATION DATA STRUCTURE (Saved in EEPROM / Flash)
// ============================================================================
struct CalData {
  uint16_t magic;
  float    tdsK;
  float    vClear;
  float    vKnown;
  float    ntuKnown;
  bool     turbOk;
};

CalData cal;
const uint16_t CAL_MAGIC = 0xA55A;

float lastTdsRaw = 0.0f;  // Raw ppm before calibration factor
float lastVTurb  = 0.0f;  // Last measured turbidity voltage
String sensorStatus = "ok";

void loadCalibration() {
  EEPROM.begin(sizeof(CalData) + 16);
  EEPROM.get(0, cal);
  if (cal.magic != CAL_MAGIC) {
    Serial.println(F("[EEPROM] No saved calibration found. Initializing factory defaults."));
    cal.magic    = CAL_MAGIC;
    cal.tdsK     = 1.0f;
    cal.vClear   = 2.5f;     // Default nominal clean water voltage (~2.5V - 3.0V)
    cal.vKnown   = 1.0f;
    cal.ntuKnown = 500.0f;
    cal.turbOk   = false;
  } else {
    Serial.println(F("[EEPROM] Calibration loaded successfully from Flash."));
  }
}

void saveCalibration() {
  EEPROM.put(0, cal);
  EEPROM.commit();
}

// ============================================================================
// SENSOR READING & PHYSICAL CONVERSION (Authoritative Logic)
// ============================================================================
// Median-style sorted sample filter to eliminate ADC electrical ripple
float readFilteredVolts(uint8_t pin) {
  analogRead(pin); // Discard initial read after pin mux switch
  delay(5);

  int s[SAMPLES];
  for (int i = 0; i < SAMPLES; i++) {
    s[i] = analogRead(pin);
    delay(4);
  }

  // Insertion sort
  for (int i = 1; i < SAMPLES; i++) {
    int key = s[i];
    int j = i - 1;
    while (j >= 0 && s[j] > key) {
      s[j + 1] = s[j];
      j--;
    }
    s[j + 1] = key;
  }

  // Average the middle 50% of readings (interquartile mean)
  long sum = 0;
  int from = SAMPLES / 4;
  int to   = SAMPLES - SAMPLES / 4;
  for (int i = from; i < to; i++) {
    sum += s[i];
  }

  float avgAdc = (float)sum / (to - from);
  float volts = (avgAdc / ADC_MAX) * ADC_VREF;
  return volts;
}

// Gravity Analog TDS standard equation (uncalibrated ppm at ~25 C)
float tdsRawPpm(float v) {
  float ppm = (133.42f * v * v * v - 255.86f * v * v + 857.39f * v) * 0.5f;
  return ppm < 0.0f ? 0.0f : ppm;
}

// Turbidity conversion: Uses 2-point calibration if available, or nominal curve
float turbidityNtu(float v) {
  if (cal.turbOk) {
    float span = cal.vClear - cal.vKnown;
    if (fabs(span) > 0.05f) {
      float ntu = (cal.vClear - v) * (cal.ntuKnown / span);
      return ntu < 0.0f ? 0.0f : ntu;
    }
  }
  // Standard Gravity turbidity response curve fallback (uncalibrated)
  // Clean water ~ 2.5V-3.0V -> 0 NTU; High turbidity ~ 0.5V -> 3000 NTU
  if (v >= 2.5f) return 0.0f;
  if (v <= 0.5f) return 3000.0f;
  float ntu = -1120.4f * v * v + 5742.3f * v - 4352.9f;
  if (ntu < 0.0f) ntu = 0.0f;
  if (ntu > 3000.0f) ntu = 3000.0f;
  return ntu;
}

// ============================================================================
// SERIAL MONITOR CALIBRATION COMMANDS
// ============================================================================
void showCalibration() {
  Serial.println(F("\n--- CURRENT CALIBRATION ---"));
  Serial.print(F("TDS Factor K     : ")); Serial.println(cal.tdsK, 4);
  Serial.print(F("Clear-water V    : ")); Serial.print(cal.vClear, 3); Serial.println(F(" V"));
  Serial.print(F("Known-point V    : ")); Serial.print(cal.vKnown, 3); Serial.println(F(" V"));
  Serial.print(F("Known Point NTU  : ")); Serial.print(cal.ntuKnown, 1); Serial.println(F(" NTU"));
  Serial.print(F("Turbidity Ready  : ")); Serial.println(cal.turbOk ? F("YES (2-Point Active)") : F("NO (Using Standard Curve)"));
  Serial.println(F("---------------------------\n"));
}

void handleSerialCommand(String cmd) {
  cmd.trim();
  cmd.toLowerCase();
  if (cmd.length() == 0) return;

  if (cmd.startsWith("tds ")) {
    float ref = cmd.substring(4).toFloat();
    if (ref > 0.0f && lastTdsRaw > 1.0f) {
      cal.tdsK = ref / lastTdsRaw;
      saveCalibration();
      Serial.printf("[CAL] Saved TDS factor K = %0.4f (reference: %0.1f ppm)\n", cal.tdsK, ref);
    } else {
      Serial.println(F("[CAL ERROR] Submerge TDS probe in solution reading > 1 ppm before calibrating!"));
    }
  } else if (cmd == "clear") {
    cal.vClear = lastVTurb;
    cal.turbOk = (cal.vClear - cal.vKnown) > 0.1f && cal.ntuKnown > 0.0f;
    saveCalibration();
    Serial.printf("[CAL] Saved clear-water reading: %0.3f V (0 NTU reference point)\n", cal.vClear);
  } else if (cmd.startsWith("turb ")) {
    float ntu = cmd.substring(5).toFloat();
    if (ntu > 0.0f) {
      cal.vKnown = lastVTurb;
      cal.ntuKnown = ntu;
      cal.turbOk = (cal.vClear - cal.vKnown) > 0.1f;
      saveCalibration();
      Serial.printf("[CAL] Saved known turbidity point: %0.3f V = %0.1f NTU\n", cal.vKnown, ntu);
      if (!cal.turbOk) {
        Serial.println(F("   -> TIP: Calibrate 'clear' in clean water first."));
      }
    } else {
      Serial.println(F("[CAL ERROR] Usage: turb <known_ntu>  (e.g., turb 100)"));
    }
  } else if (cmd == "show") {
    showCalibration();
  } else if (cmd == "reset") {
    cal.magic = 0;
    loadCalibration();
    saveCalibration();
    Serial.println(F("[CAL] Stored calibration erased. Reset to factory defaults."));
  } else {
    Serial.println(F("Commands: tds <ppm> | clear | turb <ntu> | show | reset"));
  }
}

// ============================================================================
// WI-FI & CLOUD HTTP POST TELEMETRY
// ============================================================================
WiFiClientSecure secureClient;
unsigned long lastWifiCheck = 0;

void ensureWiFiConnection() {
  if (WiFi.status() == WL_CONNECTED) return;

  unsigned long now = millis();
  if (now - lastWifiCheck < WIFI_CHECK_INTERVAL) return;
  lastWifiCheck = now;

  Serial.printf("[WiFi] Connecting to '%s'...", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 15) {
    delay(400);
    Serial.print(F("."));
    tries++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[WiFi] Connected! IP: %s | RSSI: %d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.printf("[WiFi] Not yet connected (Status: %d). Continuing telemetry loop...\n", WiFi.status());
    if (WiFi.status() == WL_NO_SSID_AVAIL) {
      Serial.println(F("   -> [HOTSPOT TIP] Ensure mobile hotspot is ON and set to 2.4 GHz band."));
    }
  }
}

void postTelemetryToRender(float tdsVal, float turbVal, bool sensorsOk) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(F("[HTTP] Wi-Fi offline — skipping cloud upload (will retry next tick)."));
    return;
  }

  // Construct JSON payload
  // pH and temperature are intentionally omitted / null (Uno & 2-sensor ESP setup)
  StaticJsonDocument<384> doc;
  doc["device_id"]        = DEVICE_ID;
  doc["source"]           = SOURCE_TAG;
  doc["firmware_version"] = FIRMWARE_VER;
  doc["uptime"]           = (unsigned long)(millis() / 1000);
  doc["wifi_rssi"]        = WiFi.RSSI();
  doc["sensor_status"]    = sensorsOk ? "ok" : "sensor_fault";

  if (sensorsOk) {
    doc["tds"]       = round(tdsVal * 10.0f) / 10.0f;
    doc["turbidity"] = round(turbVal * 100.0f) / 100.0f;
  } else {
    doc["tds"]       = nullptr;
    doc["turbidity"] = nullptr;
  }
  doc["ph"]          = nullptr;
  doc["temperature"] = nullptr;

  String body;
  serializeJson(doc, body);

  secureClient.setInsecure(); // Let's Encrypt TLS validation
  HTTPClient http;
  http.begin(secureClient, BACKEND_URL);
  http.addHeader(F("Content-Type"), F("application/json"));
  http.addHeader(F("User-Agent"), F("DROPLET-ESP/5.0"));
  http.setTimeout(8000);

  unsigned long t0 = millis();
  int code = http.POST(body);
  unsigned long duration = millis() - t0;

  if (code == 200 || code == 201) {
    Serial.printf("[HTTP POST %d] OK (%lums) -> Ingested successfully into DROPLET!\n", code, duration);
  } else if (code > 0) {
    Serial.printf("[HTTP POST %d] Server response: %s\n", code, http.getString().c_str());
  } else {
    Serial.printf("[HTTP POST Error] Code: %d (%s)\n", code, http.errorToString(code).c_str());
  }
  http.end();
}

// ============================================================================
// SETUP
// ============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println(F("\n========================================================"));
  Serial.printf("  DROPLET Water Telemetry — %s (v%s)\n", BOARD_NAME, FIRMWARE_VER);
  Serial.println(F("========================================================"));
  Serial.printf("  Backend URL : %s\n", BACKEND_URL);
  Serial.printf("  Device ID   : %s\n", DEVICE_ID);
  Serial.printf("  TDS Read Pin: GPIO %d (ADC) | Power: GPIO %d\n", PIN_TDS_ADC, PIN_TDS_PWR);
  Serial.printf("  Turbidity   : GPIO %d (ADC)\n", PIN_TURB_ADC);
  Serial.println(F("========================================================"));

  // Configure TDS power gating pin
  pinMode(PIN_TDS_PWR, OUTPUT);
  digitalWrite(PIN_TDS_PWR, LOW); // TDS powered OFF when idle

  // Load EEPROM calibration
  loadCalibration();
  showCalibration();

  // Connect Wi-Fi
  ensureWiFiConnection();

  delay(2000); // Sensor stabilization delay
}

// ============================================================================
// MAIN LOOP
// ============================================================================
unsigned long lastReadTime = 0;

void loop() {
  // 1. Process Serial Monitor calibration commands
  if (Serial.available()) {
    handleSerialCommand(Serial.readStringUntil('\n'));
  }

  // 2. Wi-Fi reconnection monitor (non-blocking)
  ensureWiFiConnection();

  // 3. Sensor sampling & cloud transmission at fixed cadence
  unsigned long now = millis();
  if (now - lastReadTime >= INTERVAL_MS) {
    lastReadTime = now;

    // A. Read Turbidity first (TDS module is completely unpowered to prevent optical/electrolytic interference)
    float vTurb = readFilteredVolts(PIN_TURB_ADC);

    // B. Power on TDS module, allow RC settling, take filtered samples, power off
    digitalWrite(PIN_TDS_PWR, HIGH);
    delay(350); // Settling delay
    float vTds = readFilteredVolts(PIN_TDS_ADC);
    digitalWrite(PIN_TDS_PWR, LOW);

    lastVTurb  = vTurb;
    lastTdsRaw = tdsRawPpm(vTds);
    float tdsVal = lastTdsRaw * cal.tdsK;
    float turbVal = turbidityNtu(vTurb);

    bool sensorsOk = true;
    if (vTds < 0.015f && vTurb < 0.015f) {
      sensorsOk = false;
      sensorStatus = "sensor_fault";
    } else {
      sensorStatus = "ok";
    }

    // Diagnostics print to Serial Monitor
    Serial.println(F("--------------------------------------------------"));
    Serial.printf("[Telemetry] Uptime: %lus | WiFi RSSI: %d dBm | Status: %s\n",
                  (unsigned long)(millis() / 1000), WiFi.RSSI(), sensorStatus.c_str());
    Serial.printf("  TDS       : %0.3f V -> %0.1f ppm (raw: %0.1f ppm)\n", vTds, tdsVal, lastTdsRaw);
    Serial.printf("  Turbidity : %0.3f V -> %0.1f NTU\n", vTurb, turbVal);

    if (vTds < 0.02f) {
      Serial.println(F("   -> [TDS TIP] Probe in air reads 0 ppm. Submerge in water to measure!"));
    }
    if (vTurb < 0.05f) {
      Serial.println(F("   -> [TURB TIP] 0.00V detected. Check wiring and ensure adapter switch is set to 'A' (Analog)!"));
    }

    // C. Forward to DROPLET cloud API
    postTelemetryToRender(tdsVal, turbVal, sensorsOk);
  }
}