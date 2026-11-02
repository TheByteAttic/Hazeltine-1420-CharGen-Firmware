// Copyright (c) 2026 by The Byte Attic B.V.
/*
 * chargen_dump.ino - dump the font of a National DM8678 or DM86S64 bipolar character
 * generator (16-pin DIP) with a 5 V Arduino (Uno / Nano / Mega).
 *
 * The chip is driven at DC speed: every internal state (address latch, line counter,
 * shift register) is static, so slow Arduino GPIO is fine.
 *
 * Wiring (chip pin -> Arduino), both chips have the same pinout except pins 11/12:
 *   1  A2 / A3        -> D4      (character code bit 2)
 *   2  A1 / A2        -> D3      (bit 1)
 *   3  A0 / A1        -> D2      (bit 0)
 *   4  ADDR LATCH CTL / STROBE -> D5   (HIGH = fall-through)
 *   5  /CLEAR         -> D6
 *   6  LINE CLOCK     -> D7
 *   7  CLOCK CONTROL  -> D8      (HIGH = line clock enabled)
 *   8  GND            -> GND
 *   9  DOT CLOCK      -> D9
 *  10  /LOAD ENABLE   -> D10
 *  11  DM8678: OUTPUT          DM86S64: /OUTPUT ENABLE
 *  12  DM8678: A7 (latched)    DM86S64: OUTPUT
 *  13  A5 / A6        -> A2     (bit 5)
 *  14  A4 / A5        -> A1     (bit 4)
 *  15  A3 / A4        -> A0     (bit 3)
 *  16  VCC            -> 5 V    (the chip draws up to 140 mA; USB supply is enough)
 *
 * Connect pin 11 -> D11 and pin 12 -> D12.  Set CHIP below.  For the DM8678 the
 * sketch drives A7 (pin 12) and reads pin 11; for the DM86S64 it drives /OE (pin 11)
 * and reads pin 12.  It first probes both polarities of the enable pin and reports
 * which one produces data.
 *
 * Output: on the serial port (115200 baud) one line per character:
 *   C 0x2A : 00 00 22 14 7F 14 22 00 00 00 00 00 00 00 00 00
 * i.e. 16 row bytes (row 0 first), bit 0 = first dot shifted out (leftmost pixel),
 * bits 0..6 = the 7 dots, bit 7 = the 8th (trailing) clock, normally 0.
 * Save the whole capture to a text file and feed it to build_eeprom.py.
 */

#define CHIP_DM8678   1
#define CHIP_DM86S64  2
#define CHIP CHIP_DM86S64        // <<< set to CHIP_DM8678 or CHIP_DM86S64

const uint8_t ADDR_PINS[6] = {2, 3, 4, A0, A1, A2};   // A0..A5 (chip pins 3,2,1,15,14,13)
const uint8_t PIN_ALC   = 5;
const uint8_t PIN_nCLR  = 6;
const uint8_t PIN_LCLK  = 7;
const uint8_t PIN_CC    = 8;
const uint8_t PIN_DCLK  = 9;
const uint8_t PIN_nLD   = 10;
const uint8_t PIN_11    = 11;
const uint8_t PIN_12    = 12;

#if CHIP == CHIP_DM8678
const uint8_t PIN_OUT = PIN_11;   // serial output
const uint8_t PIN_EN  = PIN_12;   // A7: 0 or 1 selects whether this chip drives its output
#else
const uint8_t PIN_OUT = PIN_12;
const uint8_t PIN_EN  = PIN_11;   // /OE, active low
#endif

static void pulseHigh(uint8_t pin) { digitalWrite(pin, HIGH); delayMicroseconds(2); digitalWrite(pin, LOW); delayMicroseconds(2); }
static void pulseLow(uint8_t pin)  { digitalWrite(pin, LOW);  delayMicroseconds(2); digitalWrite(pin, HIGH); delayMicroseconds(2); }

static void setAddress(uint8_t code) {
  for (uint8_t b = 0; b < 6; b++) digitalWrite(ADDR_PINS[b], (code >> b) & 1);
  // latch: fall-through while high, then hold
  digitalWrite(PIN_ALC, HIGH); delayMicroseconds(2);
  digitalWrite(PIN_ALC, LOW);  delayMicroseconds(2);
}

static void setRow(uint8_t row) {
  pulseLow(PIN_nCLR);                       // counter := 0
  for (uint8_t i = 0; i < row; i++) pulseHigh(PIN_LCLK);   // low-to-high advances the counter
}

// Load the addressed row into the shift register and clock out 8 bits.
static uint8_t readRow(uint8_t code, uint8_t row) {
  setRow(row);
  setAddress(code);
  digitalWrite(PIN_nLD, LOW); delayMicroseconds(2);
  pulseHigh(PIN_DCLK);                      // load; first bit now at the output
  digitalWrite(PIN_nLD, HIGH); delayMicroseconds(2);
  uint8_t v = 0;
  for (uint8_t b = 0; b < 8; b++) {
    if (digitalRead(PIN_OUT)) v |= (1 << b);
    pulseHigh(PIN_DCLK);                    // shift next bit
  }
  return v;
}

static uint16_t probe(uint8_t enLevel) {
  digitalWrite(PIN_EN, enLevel);
  uint16_t ones = 0;
  for (uint8_t c = 0; c < 64; c++)
    for (uint8_t r = 0; r < 12; r++) {
      uint8_t v = readRow(c, r);
      for (uint8_t b = 0; b < 7; b++) ones += (v >> b) & 1;
    }
  return ones;
}

void setup() {
  Serial.begin(115200);
  for (uint8_t b = 0; b < 6; b++) pinMode(ADDR_PINS[b], OUTPUT);
  pinMode(PIN_ALC, OUTPUT);  pinMode(PIN_nCLR, OUTPUT); pinMode(PIN_LCLK, OUTPUT);
  pinMode(PIN_CC, OUTPUT);   pinMode(PIN_DCLK, OUTPUT); pinMode(PIN_nLD, OUTPUT);
  pinMode(PIN_EN, OUTPUT);   pinMode(PIN_OUT, INPUT);
  digitalWrite(PIN_CC, HIGH); digitalWrite(PIN_nCLR, HIGH); digitalWrite(PIN_LCLK, LOW);
  digitalWrite(PIN_DCLK, LOW); digitalWrite(PIN_nLD, HIGH); digitalWrite(PIN_ALC, HIGH);
  delay(200);

  Serial.println(F("# DM8678/DM86S64 font dump"));
#if CHIP == CHIP_DM8678
  Serial.println(F("# chip: DM8678 (pin 11 = output, pin 12 = A7/enable)"));
#else
  Serial.println(F("# chip: DM86S64 (pin 12 = output, pin 11 = /OE)"));
#endif
  uint16_t onesLow = probe(LOW);
  uint16_t onesHigh = probe(HIGH);
  Serial.print(F("# lit dots with enable pin LOW: ")); Serial.print(onesLow);
  Serial.print(F("  HIGH: ")); Serial.println(onesHigh);
  uint8_t en = (onesLow >= onesHigh) ? LOW : HIGH;
  Serial.print(F("# using enable level ")); Serial.println(en == LOW ? F("LOW") : F("HIGH"));
  digitalWrite(PIN_EN, en);

  for (uint8_t c = 0; c < 64; c++) {
    Serial.print(F("C 0x")); if (c < 16) Serial.print('0'); Serial.print(c, HEX); Serial.print(F(" :"));
    for (uint8_t r = 0; r < 16; r++) {
      uint8_t v = readRow(c, r);
      Serial.print(' '); if (v < 16) Serial.print('0'); Serial.print(v, HEX);
    }
    Serial.println();
  }
  Serial.println(F("# done"));
  // second pass as an ASCII-art preview (rows 0..11)
  for (uint8_t c = 0; c < 64; c++) {
    Serial.print(F("# char 0x")); Serial.println(c, HEX);
    for (uint8_t r = 0; r < 12; r++) {
      uint8_t v = readRow(c, r);
      Serial.print(F("#   "));
      for (uint8_t b = 0; b < 7; b++) Serial.print((v >> b) & 1 ? '#' : '.');
      Serial.println();
    }
  }
  Serial.println(F("# end"));
}

void loop() {}
