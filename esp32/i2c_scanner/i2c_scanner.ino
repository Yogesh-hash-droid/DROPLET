/*
 * DROPLET - Standalone I2C Hardware Bus Scanner for NodeMCU ESP8266
 * 
 * Tests every I2C address from 0x01 to 0x7F on:
 *   SDA = GPIO 4 (NodeMCU D2)
 *   SCL = GPIO 5 (NodeMCU D1)
 *
 * Pin Order Confirmation: Wire.begin(int sda, int scl) -> Wire.begin(4, 5)
 *
 * Auto-identifies ADS1115 address and ADDR pin connection:
 *   0x48 -> ADDR connected to GND (Standard default)
 *   0x49 -> ADDR connected to VDD (3.3V)
 *   0x4A -> ADDR connected to SDA
 *   0x4B -> ADDR connected to SCL
 */

#include <Arduino.h>
#include <Wire.h>

#define I2C_SDA_PIN 4  // GPIO 4 = NodeMCU D2
#define I2C_SCL_PIN 5  // GPIO 5 = NodeMCU D1

void setup() {
  Serial.begin(115200);
  delay(1500);

  Serial.println(F("\n========================================================"));
  Serial.println(F("    DROPLET Standalone I2C Bus Diagnostic Scanner       "));
  Serial.println(F("========================================================"));
  Serial.printf("[Config] SDA Pin: GPIO %d (NodeMCU D2)\n", I2C_SDA_PIN);
  Serial.printf("[Config] SCL Pin: GPIO %d (NodeMCU D1)\n", I2C_SCL_PIN);
  Serial.println(F("[Config] Clock  : 100 kHz standard, stretch limit: 1500 us\n"));

  // Explicit pin order: Wire.begin(sda, scl)
  pinMode(I2C_SDA_PIN, INPUT_PULLUP);
  pinMode(I2C_SCL_PIN, INPUT_PULLUP);
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(100000);
  Wire.setClockStretchLimit(1500);
}

void scanI2CBus() {
  Serial.println(F("Scanning I2C bus (0x01 to 0x7F)..."));

  int nDevices = 0;
  uint8_t adsAddress = 0;

  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    byte error = Wire.endTransmission();

    if (error == 0) {
      Serial.printf("  -> [FOUND] I2C device detected at address 0x%02X (%d decimal)", address, address);
      
      // ADS1115 address decoder
      if (address == 0x48) {
        Serial.print(F(" <-- ADS1115 ADC (ADDR connected to GND)"));
        adsAddress = address;
      } else if (address == 0x49) {
        Serial.print(F(" <-- ADS1115 ADC (ADDR connected to VDD / 3.3V)"));
        adsAddress = address;
      } else if (address == 0x4A) {
        Serial.print(F(" <-- ADS1115 ADC (ADDR connected to SDA)"));
        adsAddress = address;
      } else if (address == 0x4B) {
        Serial.print(F(" <-- ADS1115 ADC (ADDR connected to SCL)"));
        adsAddress = address;
      }
      Serial.println();
      nDevices++;
    } else if (error == 4) {
      Serial.printf("  -> [ERROR] Bus/line error at address 0x%02X\n", address);
    }
  }

  Serial.println(F("--------------------------------------------------------"));
  if (nDevices == 0) {
    Serial.println(F("[RESULT] NO I2C DEVICES FOUND! Check physical hardware:"));
    Serial.println(F("   1. ADDR Pin: Must not be floating! Connect firmly to ESP G (GND)."));
    Serial.println(F("   2. Header Pins: Must be SOLDERED to the ADS1115 board (loose pins fail)."));
    Serial.println(F("   3. Power Voltage: Measure 3.3V between ADS VDD and GND with a multimeter."));
    Serial.println(F("   4. Pin Order: SDA is NodeMCU D2 (GPIO 4), SCL is NodeMCU D1 (GPIO 5)."));
    Serial.println(F("   5. Jumper Wires: Replace jumper wires (breadboard jumpers often have breaks)."));
    Serial.println(F("   6. Module Health: If 3.3V and GND are good but no ACK, module may be defective."));
  } else {
    Serial.printf("[RESULT] Scan complete: %d device(s) found.\n", nDevices);
    if (adsAddress != 0) {
      Serial.printf("[STATUS] ADS1115 is READY on address 0x%02X!\n", adsAddress);
    } else {
      Serial.println(F("[WARNING] Devices responded, but NONE match ADS1115 (0x48-0x4B)."));
    }
  }
  Serial.println(F("========================================================\n"));
}

void loop() {
  scanI2CBus();
  delay(3000); // Re-scan every 3 seconds
}
