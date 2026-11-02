#include <WiFi.h>
#include <HTTPClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <ArduinoJson.h>
#include "time.h"

// Configuration Constants
const char* WIFI_SSID     = "Vgp";
const char* WIFI_PASSWORD = "guru2006";
const char* CONVEX_URL    = "https://aware-jaguar-705.convex.site/ingest";[cite: 1]
const char* USER_ID       = "jh719cf5sggytsft8983tyeqjn8gxp34";[cite: 1]
const char* SEED_ID       = "jd7aq34an93s039ab9z8zeknad8gx8ph";[cite: 1]

// NTP Server Configuration (UTC)
const char* NTP_SERVER    = "pool.ntp.org";
const long  GMT_OFFSET_SEC = 0;
const int   DAYLIGHT_OFFSET_SEC = 0;

// DS18B20 Hardware Config
#define ONE_WIRE_BUS 4
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

// Function Prototypes
float readSoilTemperature();
bool sendToAgriFlow(const char* seedId, const char* userId, float temperatureC, float moisturePct);
String getIsoTimestamp();

void setup() {
  Serial.begin(115200);

  // Connect WiFi
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);[cite: 1]
  while (WiFi.status() != WL_CONNECTED) {[cite: 1]
    delay(500);[cite: 1]
    Serial.print(".");[cite: 1]
  }
  Serial.println("\nWiFi connected");[cite: 1]

  // Sync time with NTP Server
  configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET_SEC, NTP_SERVER);
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    Serial.println("Failed to obtain NTP time");
  } else {
    Serial.println("NTP Time Synced");
  }

  // Initialize DS18B20 sensor
  sensors.begin();[cite: 1]
}

void loop() {
  float tempC = readSoilTemperature();
  if (!isnan(tempC)) {[cite: 1]
    Serial.printf("Soil temp: %.1f C\n", tempC);[cite: 1]
    sendToAgriFlow(SEED_ID, USER_ID, tempC, NAN);[cite: 1]
  }
  delay(5 * 60 * 1000); // Send reading every 5 minutes[cite: 1]
}

// Generates ISO 8601 Timestamp string (e.g. "2026-10-28T12:23:00Z")
String getIsoTimestamp() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    return "";
  }
  char timeStringBuff[30];
  strftime(timeStringBuff, sizeof(timeStringBuff), "%Y-%m-%dT%H:%M:%SZ", &timeinfo);
  return String(timeStringBuff);
}

// Reads temperature from DS18B20 sensor
float readSoilTemperature() {
  sensors.requestTemperatures();[cite: 1]
  float tempC = sensors.getTempCByIndex(0);[cite: 1]
  if (tempC == DEVICE_DISCONNECTED_C) {[cite: 1]
    Serial.println("DS18B20 not found!");[cite: 1]
    return NAN;[cite: 1]
  }
  return tempC;[cite: 1]
}

// Sends temperature readings with timestamp to AgriFlow endpoint
bool sendToAgriFlow(const char* seedId, const char* userId, float temperatureC, float moisturePct) {
  if (WiFi.status() != WL_CONNECTED) return false;[cite: 1]

  HTTPClient http;
  http.begin(CONVEX_URL);[cite: 1]
  http.addHeader("Content-Type", "application/json");[cite: 1]

  StaticJsonDocument<256> doc;[cite: 1]
  doc["seedId"] = seedId;[cite: 1]
  doc["userId"] = userId;[cite: 1]
  doc["soilTemperatureC"] = temperatureC;[cite: 1]
  if (!isnan(moisturePct)) doc["soilMoisture"] = moisturePct;[cite: 1]
  doc["timestamp"] = getIsoTimestamp();[cite: 1]

  String body;
  serializeJson(doc, body);[cite: 1]

  int code = http.POST(body);[cite: 1]
  http.end();[cite: 1]

  return code == 200;[cite: 1]
}