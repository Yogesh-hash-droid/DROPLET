/*
  Water Quality Monitor - Arduino Uno + TDS + Turbidity (no ADS1115)
  Educational prototype. Not certified water-safety equipment.

  WIRING
    TDS:       red (+) -> Uno D7 (powered only while reading), black (-) -> GND,
               yellow (A) -> Uno A0
    Turbidity: V -> Uno 5V, G -> GND, signal -> Uno A1

  ARDUINO IDE: Board "Arduino Uno". No extra library needed.
  Serial Monitor: 9600 baud, line ending set to "Newline".

  WHAT THIS VERSION FIXES
    - Measures the real 5V rail automatically (no need to type VREF).
    - Averages many samples (middle half of sorted values) to reduce noise.
    - Powers the TDS module only while reading, so the TDS probe does not
      disturb the turbidity reading or sit energised in the water.
    - Calibrate from the Serial Monitor with commands. Values are saved in
      EEPROM and survive power-off. No re-uploading.

  CALIBRATION COMMANDS (type in Serial Monitor, press Enter)
    tds 500    probe in a standard solution of 500 ppm -> saves TDS factor
    clear      probe in clear water -> saves 0 NTU point
    turb 100   probe in water of known 100 NTU -> saves second point
    show       print saved calibration
    reset      erase saved calibration

  TEMPERATURE: there is no temperature sensor in this project, so TDS is not
  temperature compensated. Calibrate and measure at about 25 C.
*/

#include <Arduino.h>
#include <EEPROM.h>

const char* DEVICE_ID = "UNO-001";
const uint8_t PIN_TDS_PWR = 7;     // D7 powers the TDS module (check module current < 20 mA)
const uint8_t PIN_TDS     = A0;
const uint8_t PIN_TURB    = A1;

const int SAMPLES = 30;
const unsigned long INTERVAL_MS = 3000;

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

float lastTdsRaw = 0;   // uncalibrated ppm from the last reading
float lastVTurb  = 0;   // volts from the last turbidity reading

void loadCal() {
  EEPROM.get(0, cal);
  if (cal.magic != CAL_MAGIC) {
    cal.magic = CAL_MAGIC; cal.tdsK = 1.0f;
    cal.vClear = 0; cal.vKnown = 0; cal.ntuKnown = 0; cal.turbOk = false;
  }
}
void saveCal() { EEPROM.put(0, cal); }

// Measure the real 5V rail (mV) using the internal 1.1 V reference
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
  analogRead(pin);                      // discard first reading after switching pin
  delay(10);
  int s[SAMPLES];
  for (int i = 0; i < SAMPLES; i++) { s[i] = analogRead(pin); delay(5); }
  for (int i = 1; i < SAMPLES; i++) {   // insertion sort
    int k = s[i], j = i - 1;
    while (j >= 0 && s[j] > k) { s[j + 1] = s[j]; j--; }
    s[j + 1] = k;
  }
  long sum = 0;
  int from = SAMPLES / 4, to = SAMPLES - SAMPLES / 4;
  for (int i = from; i < to; i++) sum += s[i];
  return ((float)sum / (to - from)) * vcc / 1023.0f;
}

// TDS in ppm before calibration factor (assumes about 25 C)
float tdsRawPpm(float v) {
  float ppm = (133.42f * v * v * v - 255.86f * v * v + 857.39f * v) * 0.5f;
  return ppm < 0 ? 0 : ppm;
}

float turbidityNtu(float v) {
  float span = cal.vClear - cal.vKnown;
  float ntu = (cal.vClear - v) * (cal.ntuKnown / span);
  return ntu < 0 ? 0 : ntu;
}

void showCal() {
  Serial.print(F("TDS factor K: "));   Serial.println(cal.tdsK, 4);
  Serial.print(F("Clear-water V: "));  Serial.println(cal.vClear, 3);
  Serial.print(F("Known point V: "));  Serial.print(cal.vKnown, 3);
  Serial.print(F(" = "));              Serial.print(cal.ntuKnown, 1); Serial.println(F(" NTU"));
  Serial.println(cal.turbOk ? F("Turbidity calibrated: YES") : F("Turbidity calibrated: NO"));
}

void handleCommand(String cmd) {
  cmd.trim(); cmd.toLowerCase();
  if (cmd.length() == 0) return;

  if (cmd.startsWith("tds ")) {
    float ref = cmd.substring(4).toFloat();
    if (ref > 0 && lastTdsRaw > 1) {
      cal.tdsK = ref / lastTdsRaw; saveCal();
      Serial.print(F("Saved. TDS factor K = ")); Serial.println(cal.tdsK, 4);
    } else Serial.println(F("Need a reference ppm and a probe in solution (reading above 1 ppm)."));
  } else if (cmd == "clear") {
    cal.vClear = lastVTurb;
    cal.turbOk = (cal.vClear - cal.vKnown) > 0.1f && cal.ntuKnown > 0;
    saveCal();
    Serial.print(F("Saved clear-water V = ")); Serial.println(cal.vClear, 3);
  } else if (cmd.startsWith("turb ")) {
    float ntu = cmd.substring(5).toFloat();
    if (ntu > 0) {
      cal.vKnown = lastVTurb; cal.ntuKnown = ntu;
      cal.turbOk = (cal.vClear - cal.vKnown) > 0.1f;
      saveCal();
      Serial.print(F("Saved known point: ")); Serial.print(cal.vKnown, 3);
      Serial.print(F(" V = ")); Serial.print(ntu, 1); Serial.println(F(" NTU"));
      if (!cal.turbOk) Serial.println(F("Set 'clear' first (clear water must read higher than the turbid point)."));
    } else Serial.println(F("Usage: turb 100"));
  } else if (cmd == "show") {
    showCal();
  } else if (cmd == "reset") {
    cal.magic = 0; loadCal(); saveCal();
    Serial.println(F("Calibration erased."));
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
  Serial.println(F("=== Water Quality Monitor (Arduino Uno) ==="));
  Serial.println(F("Commands: tds <ppm> | clear | turb <ntu> | show | reset"));
  showCal();
  delay(3000);                          // turbidity sensor warm-up
}

void loop() {
  if (Serial.available()) handleCommand(Serial.readStringUntil('\n'));

  if (millis() - lastRun < INTERVAL_MS) return;
  lastRun = millis();

  float vcc = readVccMv() / 1000.0f;

  // Turbidity first (TDS module is still off)
  float vTurb = readVolts(PIN_TURB, vcc);

  // TDS: power on, let it settle, read, power off
  digitalWrite(PIN_TDS_PWR, HIGH);
  delay(400);
  float vTds = readVolts(PIN_TDS, vcc);
  digitalWrite(PIN_TDS_PWR, LOW);

  lastVTurb = vTurb;
  lastTdsRaw = tdsRawPpm(vTds);
  float tds = lastTdsRaw * cal.tdsK;

  Serial.print(F("5V rail: "));          Serial.print(vcc, 2);
  Serial.print(F(" V | TDS V: "));       Serial.print(vTds, 3);
  Serial.print(F(" | Turbidity V: "));   Serial.println(vTurb, 3);

  if (vTds < 0.02f) Serial.println(F("TDS: no signal (dry probe or wiring problem)"));
  if (vTurb < 0.02f) Serial.println(F("Turbidity: no signal (check wiring)"));

  Serial.print(F("TDS: ")); Serial.print(tds, 1); Serial.println(F(" ppm"));

  if (!cal.turbOk) {
    Serial.println(F("Turbidity: not calibrated (use commands: clear, turb <ntu>)"));
  } else {
    float ntu = turbidityNtu(vTurb);
    Serial.print(F("Turbidity: ")); Serial.print(ntu, 1); Serial.println(F(" NTU"));

    // JSON line (only when both values are valid)
    Serial.print(F("{\"device_id\":\"")); Serial.print(DEVICE_ID);
    Serial.print(F("\",\"tds\":"));       Serial.print(tds, 1);
    Serial.print(F(",\"turbidity\":"));   Serial.print(ntu, 1);
    Serial.println(F(",\"source\":\"ARDUINO_UNO\"}"));
  }
  Serial.println(F("--------------------------------"));
}
