// NeuroGrip ESP32 firmware
// Board: Inland ESP32 dev board (ESP32-WROOM-32E, classic ESP32). Arduino IDE board: "ESP32 Dev Module".
//
// Streams the two intent pads + accelerometer at 50 Hz and drives 5 finger servos from the laptop.
// Protocol (115200 baud, newline-terminated):
//   out: S,<ms>,<temple>,<forearm>,<ax_mg>,<ay_mg>,<az_mg>
//        # ...                                       info lines (ignored by the laptop)
//   in:  A,<thumb>,<index>,<middle>,<ring>,<pinky>   servo degrees (clamped 0-160)
//        B,<hz>,<ms>                                 buzzer tone
//        L,<G|R|O>                                   LEDs green / red / off
// Safety: no A command for 500 ms -> all servos return to 0 (open hand).

#include <Wire.h>
#include <ESP32Servo.h>

// ---- pins: every servo + pad on the LEFT header (IO13 ... IO33), outputs on the right header ----
// Avoid: SD0-SD3/CMD/CLK (flash), IO12 (boot strapping), IO34-39 (input only).
const int PIN_TOUCH_TEMPLE  = 32;   // T9, foil pad in the headband
const int PIN_TOUCH_FOREARM = 33;   // T8, foil pad on the forearm
const int SERVO_PINS[5]     = {13, 14, 27, 26, 25};  // thumb, index, middle, ring, pinky
const int PIN_BUZZER        = 18;
const int PIN_LED_GREEN     = 19;
const int PIN_LED_RED       = 23;
const int PIN_SDA = 21, PIN_SCL = 22;

const int NUM_SERVOS = 5;
const int SERVO_MAX = 160;
const unsigned long SAMPLE_MS = 20;      // 50 Hz
const unsigned long WATCHDOG_MS = 500;
const int TOUCH_SAMPLES = 4;             // average a few reads per frame to cut noise

Servo servos[NUM_SERVOS];
unsigned long lastSample = 0;
unsigned long lastServoCmd = 0;
bool servosNeutral = true;
char buf[48];
int bufLen = 0;

// ---------------- accelerometer (auto-detect Grove ADXL345 or LIS3DHTR) ----------------
enum AccelType { ACC_NONE, ACC_ADXL345, ACC_LIS3DH };
AccelType accel = ACC_NONE;
uint8_t accelAddr = 0;

bool i2cPresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

void writeReg(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

uint8_t readReg(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom((int)addr, 1);
  return Wire.available() ? Wire.read() : 0;
}

void accelBegin() {
  const uint8_t adxl[2] = {0x53, 0x1D};
  for (uint8_t a : adxl) {
    if (i2cPresent(a)) {
      accel = ACC_ADXL345; accelAddr = a;
      writeReg(a, 0x2C, 0x0A);  // BW_RATE: 100 Hz
      writeReg(a, 0x31, 0x0B);  // DATA_FORMAT: full resolution, +/-16 g (3.9 mg/LSB)
      writeReg(a, 0x2D, 0x08);  // POWER_CTL: measure
      return;
    }
  }
  const uint8_t lis[2] = {0x19, 0x18};
  for (uint8_t a : lis) {
    if (i2cPresent(a) && readReg(a, 0x0F) == 0x33) {  // WHO_AM_I
      accel = ACC_LIS3DH; accelAddr = a;
      writeReg(a, 0x20, 0x57);  // CTRL_REG1: 100 Hz, XYZ on
      writeReg(a, 0x23, 0x08);  // CTRL_REG4: high resolution, +/-2 g (1 mg/digit)
      return;
    }
  }
}

void accelRead(int &x, int &y, int &z) {
  if (accel == ACC_NONE) { x = 0; y = 0; z = 1000; return; }  // no sensor: report "still"
  Wire.beginTransmission(accelAddr);
  Wire.write(accel == ACC_ADXL345 ? 0x32 : (0x28 | 0x80));   // LIS3DH: auto-increment
  Wire.endTransmission(false);
  Wire.requestFrom((int)accelAddr, 6);
  int16_t v[3] = {0, 0, 0};
  for (int i = 0; i < 3 && Wire.available() >= 2; i++) {
    uint8_t lo = Wire.read(), hi = Wire.read();
    v[i] = (int16_t)((hi << 8) | lo);
  }
  if (accel == ACC_ADXL345) {
    x = (int)(v[0] * 3.9f); y = (int)(v[1] * 3.9f); z = (int)(v[2] * 3.9f);
  } else {
    x = v[0] >> 4; y = v[1] >> 4; z = v[2] >> 4;  // 12-bit left-justified, 1 mg/digit
  }
}

// ---------------- outputs ----------------
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

uint32_t touchAvg(int pin) {
  uint32_t sum = 0;
  for (int i = 0; i < TOUCH_SAMPLES; i++) sum += touchRead(pin);
  return sum / TOUCH_SAMPLES;
}

// ---------------- commands from the laptop ----------------
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
  accelBegin();

  for (int i = 0; i < NUM_SERVOS; i++) {
    servos[i].setPeriodHertz(50);
    servos[i].attach(SERVO_PINS[i], 500, 2400);  // SG90 pulse range
  }
  servosNeutralPosition();

  const char *accelName = accel == ACC_ADXL345 ? "ADXL345" : accel == ACC_LIS3DH ? "LIS3DHTR" : "none";
  Serial.printf("# NeuroGrip firmware 2 | ESP32-WROOM-32E | accel=%s | touch T9(IO32)=temple T8(IO33)=forearm\n",
                accelName);
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
    accelRead(ax, ay, az);
    Serial.printf("S,%lu,%lu,%lu,%d,%d,%d\n", now,
                  (unsigned long)touchAvg(PIN_TOUCH_TEMPLE), (unsigned long)touchAvg(PIN_TOUCH_FOREARM),
                  ax, ay, az);
  }
}
