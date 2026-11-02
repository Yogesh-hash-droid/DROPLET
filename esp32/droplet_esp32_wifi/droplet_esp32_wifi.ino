/*
 * ============================================================================
 * DROPLET — Smart Water Quality Monitoring System
 * Firmware for Arduino Uno (TDS on A0 + Turbidity on A1)
 * ============================================================================
 * Educational prototype. Not certified water-safety equipment.
 *
 * ⚠️ Important:
 * The Arduino Uno does NOT have onboard Wi-Fi. It streams sensor telemetry
 * over USB Serial (9600 baud) to the DROPLET Python gateway (`arduino/gateway.py`),
 * which forwards readings directly to the cloud backend and web dashboard.
 *
 * AUTHORITATIVE WIRING (Your Setup):
 *   --------------------------------------------------------------------------
 *   Sensor Wire         Arduino Uno Pin    Notes
 *   --------------------------------------------------------------------------
 *   TDS Red (+)         Uno 5V             Continuous 5V rail power
 *   TDS Black (-)       Uno GND            Common Ground
 *   TDS Yellow (Signal) Uno A0             Analog TDS input
 *
 *   Turbidity V         Uno 5V             Continuous 5V rail power
 *   Turbidity G         Uno GND            Common Ground
 *   Turbidity Signal    Uno A1             Analog Turbidity input
 *                       * Set the blue adapter board slide switch to 'A' (Analog)!
 *   --------------------------------------------------------------------------
 *
 * ARDUINO IDE SETUP:
 *   - Board       : "Arduino Uno"
 *   - Port        : Select the COM port where your Uno is plugged in
 *   - Serial Baud : 9600 (Line ending: "Newline")
 *   - Libraries   : None needed! Standard Arduino core libraries only.
 *
 * SERIAL MONITOR CALIBRATION COMMANDS (9600 baud, Newline):
 *   tds <ppm>   -> Place probe in standard solution (e.g. `tds 500`) -> saves TDS factor
 *   clear       -> Place turbidity probe in clean water -> saves 0 NTU clear-point
 *   turb <ntu>  -> Place turbidity probe in known NTU solution (e.g. `turb 100`) -> saves span
 *   show        -> Display current calibration stored in EEPROM
 *   reset       -> Erase saved calibration back to factory defaults
 * ============================================================================
 */

#include <Arduino.h>
#include <EEPROM.h>

const char* DEVICE_ID = "UNO-001";
const uint8_t PIN_TDS     = A0;
const uint8_t PIN_TURB    = A1;
const uint8_t PIN_TDS_PWR = 7;     // D7 (optional power gating pin; harmless when Red is on 5V)

const int SAMPLES = 30;
const unsigned long INTERVAL_MS = 2000; // Measure & stream every 2 seconds

struct Cal {
  uint16_t magic;
  float tdsK;
  float vClear;
  float vKnown;
  float ntuKnown;
  bool  turbOk;
};
Cal cal;
const uint16_t CAL_MAGIC = 0xA55A;

float lastTdsRaw = 0.0f;   // uncalibrated ppm from the last reading
float lastVTurb  = 0.0f;   // volts from the last turbidity reading

void loadCal() {
  EEPROM.get(0, cal);
  if (cal.magic != CAL_MAGIC) {
    cal.magic = CAL_MAGIC;
    cal.tdsK = 1.0f;
    cal.vClear = 2.5f;     // Default nominal clean water voltage (~2.5V - 3.0V)
    cal.vKnown = 1.0f;
    cal.ntuKnown = 500.0f;
    cal.turbOk = false;
  }
}

void saveCal() {
  EEPROM.put(0, cal);
}

// Measure the real 5V rail (mV) internally using the ATmega328P 1.1V bandgap reference
long readVccMv() {
  ADMUX = _BV(REFS0) | _BV(MUX3) | _BV(MUX2) | _BV(MUX1);
  delay(3);
  long sum = 0;
  for (int i = 0; i < 8; i++) {
    ADCSRA |= _BV(ADSC);
    while (bit_is_set(ADCSRA, ADSC));
    sum += ADC;
  }
  return 1125300L / (sum / 8);
}

// Median-style average of analogRead samples, returned in volts
float readVolts(uint8_t pin, float vcc) {
  analogRead(pin); // discard first reading after switching pin
  delay(10);
  int s[SAMPLES];
  for (int i = 0; i < SAMPLES; i++) {
    s[i] = analogRead(pin);
    delay(5);
  }
  // Insertion sort
  for (int i = 1; i < SAMPLES; i++) {
    int k = s[i], j = i - 1;
    while (j >= 0 && s[j] > k) {
      s[j + 1] = s[j];
      j--;
    }
    s[j + 1] = k;
  }
  // Interquartile mean (middle 50% of samples)
  long sum = 0;
  int from = SAMPLES / 4, to = SAMPLES - SAMPLES / 4;
  for (int i = from; i < to; i++) {
    sum += s[i];
  }
  return ((float)sum / (to - from)) * vcc / 1023.0f;
}

// TDS in ppm before calibration factor (assumes ambient ~25 C)
float tdsRawPpm(float v) {
  float ppm = (133.42f * v * v * v - 255.86f * v * v + 857.39f * v) * 0.5f;
  return ppm < 0.0f ? 0.0f : ppm;
}

// Turbidity in NTU (2-point span if calibrated, or standard curve fallback)
float turbidityNtu(float v) {
  if (cal.turbOk) {
    float span = cal.vClear - cal.vKnown;
    if (fabs(span) > 0.05f) {
      float ntu = (cal.vClear - v) * (cal.ntuKnown / span);
      return ntu < 0.0f ? 0.0f : ntu;
    }
  }
  // Standard Gravity turbidity response curve fallback (uncalibrated)
  if (v >= 2.5f) return 0.0f;
  if (v <= 0.5f) return 3000.0f;
  float ntu = -1120.4f * v * v + 5742.3f * v - 4352.9f;
  if (ntu < 0.0f) ntu = 0.0f;
  if (ntu > 3000.0f) ntu = 3000.0f;
  return ntu;
}

void showCal() {
  Serial.println(F("\n--- CURRENT CALIBRATION ---"));
  Serial.print(F("TDS factor K     : ")); Serial.println(cal.tdsK, 4);
  Serial.print(F("Clear-water V    : ")); Serial.print(cal.vClear, 3); Serial.println(F(" V"));
  Serial.print(F("Known-point V    : ")); Serial.print(cal.vKnown, 3);
  Serial.print(F(" V = "));              Serial.print(cal.ntuKnown, 1); Serial.println(F(" NTU"));
  Serial.print(F("Turbidity Ready  : ")); Serial.println(cal.turbOk ? F("YES (2-Point Active)") : F("NO (Using Standard Curve)"));
  Serial.println(F("---------------------------\n"));
}

void handleCommand(String cmd) {
  cmd.trim();
  cmd.toLowerCase();
  if (cmd.length() == 0) return;

  if (cmd.startsWith("tds ")) {
    float ref = cmd.substring(4).toFloat();
    if (ref > 0.0f && lastTdsRaw > 1.0f) {
      cal.tdsK = ref / lastTdsRaw;
      saveCal();
      Serial.print(F("Saved. TDS factor K = "));
      Serial.println(cal.tdsK, 4);
    } else {
      Serial.println(F("Need a reference ppm and a probe in solution (reading above 1 ppm)."));
    }
  } else if (cmd == "clear") {
    cal.vClear = lastVTurb;
    cal.turbOk = (cal.vClear - cal.vKnown) > 0.1f && cal.ntuKnown > 0.0f;
    saveCal();
    Serial.print(F("Saved clear-water V = "));
    Serial.println(cal.vClear, 3);
  } else if (cmd.startsWith("turb ")) {
    float ntu = cmd.substring(5).toFloat();
    if (ntu > 0.0f) {
      cal.vKnown = lastVTurb;
      cal.ntuKnown = ntu;
      cal.turbOk = (cal.vClear - cal.vKnown) > 0.1f;
      saveCal();
      Serial.print(F("Saved known point: "));
      Serial.print(cal.vKnown, 3);
      Serial.print(F(" V = "));
      Serial.print(ntu, 1);
      Serial.println(F(" NTU"));
      if (!cal.turbOk) {
        Serial.println(F("Set 'clear' first (clear water must read higher than the turbid point)."));
      }
    } else {
      Serial.println(F("Usage: turb <known_ntu>  (e.g., turb 100)"));
    }
  } else if (cmd == "show") {
    showCal();
  } else if (cmd == "reset") {
    cal.magic = 0;
    loadCal();
    saveCal();
    Serial.println(F("Calibration erased. Reset to factory defaults."));
  } else {
    Serial.println(F("Commands: tds <ppm> | clear | turb <ntu> | show | reset"));
  }
}

unsigned long lastRun = 0;

void setup() {
  Serial.begin(9600);
  pinMode(PIN_TDS_PWR, OUTPUT);
  digitalWrite(PIN_TDS_PWR, LOW);
  loadCal();

  Serial.println(F("\n========================================================"));
  Serial.println(F("  DROPLET Water Quality Telemetry — Arduino Uno        "));
  Serial.println(F("========================================================"));
  Serial.println(F("Wiring: TDS on A0 (5V), Turbidity on A1 (5V)"));
  Serial.println(F("Commands: tds <ppm> | clear | turb <ntu> | show | reset"));
  showCal();
  delay(2000); // Sensor stabilization delay
}

void loop() {
  // 1. Process Serial Monitor commands
  if (Serial.available()) {
    handleCommand(Serial.readStringUntil('\n'));
  }

  // 2. Measure and stream at fixed cadence
  if (millis() - lastRun < INTERVAL_MS) return;
  lastRun = millis();

  float vcc = readVccMv() / 1000.0f;

  // Turbidity first
  float vTurb = readVolts(PIN_TURB, vcc);

  // TDS reading
  digitalWrite(PIN_TDS_PWR, HIGH);
  delay(350);
  float vTds = readVolts(PIN_TDS, vcc);
  digitalWrite(PIN_TDS_PWR, LOW);

  lastVTurb  = vTurb;
  lastTdsRaw = tdsRawPpm(vTds);
  float tds  = lastTdsRaw * cal.tdsK;
  float ntu  = turbidityNtu(vTurb);

  // Diagnostic prints
  Serial.print(F("5V Rail: "));        Serial.print(vcc, 2);
  Serial.print(F(" V | TDS: "));       Serial.print(tds, 1);
  Serial.print(F(" ppm ("));           Serial.print(vTds, 3);
  Serial.print(F("V) | Turbidity: ")); Serial.print(ntu, 1);
  Serial.print(F(" NTU ("));           Serial.print(vTurb, 3);
  Serial.println(F("V)"));

  if (vTds < 0.02f) {
    Serial.println(F("   -> [TDS TIP] Probe in air reads 0 ppm. Submerge in water to measure!"));
  }
  if (vTurb < 0.05f) {
    Serial.println(F("   -> [TURB TIP] 0.00V detected. Check wiring and ensure switch is set to 'A' (Analog)!"));
  }

  // 3. Emit clean JSON line for gateway ingestion
  Serial.print(F("{\"device_id\":\"")); Serial.print(DEVICE_ID);
  Serial.print(F("\",\"tds\":"));       Serial.print(tds, 1);
  Serial.print(F(",\"turbidity\":"));   Serial.print(ntu, 1);
  Serial.println(F(",\"source\":\"ARDUINO_UNO\"}"));
  Serial.println(F("--------------------------------------------------"));
}