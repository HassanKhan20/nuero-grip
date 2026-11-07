// NeuroGrip ESP32 firmware
// Streams touch + accelerometer at 50 Hz, accepts servo/buzzer/LED commands.
// Protocol (115200 baud, newline-terminated):
//   out: S,<ms>,<temple>,<forearm>,<ax_mg>,<ay_mg>,<az_mg>
//   in:  A,<thumb>,<index>,<middle>,<ring>,<pinky>   servo degrees (clamped 0-160)
//        B,<hz>,<ms>                                 buzzer tone
//        L,<G|R|O>                                   LEDs green / red / off
// Safety: no A command for 500 ms -> all servos return to 0 (open hand).

#include <Wire.h>
#include <ESP32Servo.h>

// ---- pins (classic ESP32 DevKit; edit to match your wiring) ----
const int PIN_TOUCH_TEMPLE  = T0;   // GPIO4
const int PIN_TOUCH_FOREARM = T3;   // GPIO15
// One servo per finger. Avoids strapping pins (0, 2, 5, 12, 15), flash pins (6-11),
// input-only pins (34-39), touch pins in use (4, 15) and I2C (21, 22).
const int PIN_SERVO_THUMB   = 13;
const int PIN_SERVO_INDEX   = 18;
const int PIN_SERVO_MIDDLE  = 19;
const int PIN_SERVO_RING    = 23;
const int PIN_SERVO_PINKY   = 33;
const int PIN_BUZZER        = 25;
const int PIN_LED_GREEN     = 26;
const int PIN_LED_RED       = 27;
const int PIN_SDA = 21, PIN_SCL = 22;

const uint8_t ADXL345_ADDR = 0x53;
const int SERVO_MAX = 160;
const unsigned long SAMPLE_MS = 20;      // 50 Hz
const unsigned long WATCHDOG_MS = 500;

const int NUM_SERVOS = 5;
Servo servos[NUM_SERVOS];
const int servoPins[NUM_SERVOS] = {PIN_SERVO_THUMB, PIN_SERVO_INDEX, PIN_SERVO_MIDDLE,
                                   PIN_SERVO_RING, PIN_SERVO_PINKY};

unsigned long lastSample = 0;
unsigned long lastServoCmd = 0;
bool servosNeutral = true;
char buf[48];
int bufLen = 0;

void adxlWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

void adxlRead(int &x, int &y, int &z) {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(0x32);
  Wire.endTransmission(false);
  Wire.requestFrom((int)ADXL345_ADDR, 6);
  int16_t v[3] = {0, 0, 0};
  for (int i = 0; i < 3 && Wire.available() >= 2; i++) {
    uint8_t lo = Wire.read(), hi = Wire.read();
    v[i] = (int16_t)((hi << 8) | lo);
  }
  // full-resolution mode: 3.9 mg per LSB
  x = (int)(v[0] * 3.9f);
  y = (int)(v[1] * 3.9f);
  z = (int)(v[2] * 3.9f);
}

void setServos(const int *vals) {
  for (int i = 0; i < NUM_SERVOS; i++) servos[i].write(constrain(vals[i], 0, SERVO_MAX));
}

void servosNeutralPosition() {
  const int zeros[NUM_SERVOS] = {0, 0, 0, 0, 0};
  setServos(zeros);
}

void setLeds(char s) {
  digitalWrite(PIN_LED_GREEN, s == 'G' ? HIGH : LOW);
  digitalWrite(PIN_LED_RED,   s == 'R' ? HIGH : LOW);
}

void handleLine(char *line) {
  if (line[0] == 'A') {
    int v[NUM_SERVOS];
    if (sscanf(line, "A,%d,%d,%d,%d,%d", &v[0], &v[1], &v[2], &v[3], &v[4]) == NUM_SERVOS) {
      setServos(v);
      lastServoCmd = millis();
      servosNeutral = false;
    }
  } else if (line[0] == 'B') {
    int hz, ms;
    if (sscanf(line, "B,%d,%d", &hz, &ms) == 2 && hz > 0 && ms > 0) tone(PIN_BUZZER, hz, ms);
  } else if (line[0] == 'L' && line[1] == ',') {
    setLeds(line[2]);
  }
}

void readCommands() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (bufLen > 0) {
        buf[bufLen] = '\0';
        handleLine(buf);
        bufLen = 0;
      }
    } else if (bufLen < (int)sizeof(buf) - 1) {
      buf[bufLen++] = ch;
    } else {
      bufLen = 0;  // overflow: drop the line
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  setLeds('O');

  Wire.begin(PIN_SDA, PIN_SCL);
  adxlWrite(0x2C, 0x0A);  // BW_RATE: 100 Hz output
  adxlWrite(0x31, 0x0B);  // DATA_FORMAT: full resolution, +/-16 g
  adxlWrite(0x2D, 0x08);  // POWER_CTL: measure

  for (int i = 0; i < NUM_SERVOS; i++) {
    servos[i].setPeriodHertz(50);
    servos[i].attach(servoPins[i], 500, 2400);
  }
  servosNeutralPosition();
}

void loop() {
  readCommands();

  unsigned long now = millis();
  if (!servosNeutral && now - lastServoCmd > WATCHDOG_MS) {
    servosNeutralPosition();
    setLeds('O');
    servosNeutral = true;
  }

  if (now - lastSample >= SAMPLE_MS) {
    lastSample = now;
    int ax, ay, az;
    adxlRead(ax, ay, az);
    Serial.printf("S,%lu,%u,%u,%d,%d,%d\n", now,
                  touchRead(PIN_TOUCH_TEMPLE), touchRead(PIN_TOUCH_FOREARM), ax, ay, az);
  }
}
