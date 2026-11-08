// NeuroGrip HAND firmware (ESP32-S3). Plugged into the laptop by USB; drives the 5 finger servos.
// Receives the wireless headband (firmware/headband_esp32) over ESP-NOW and forwards its readings to the
// laptop in the same "S,..." format the app already reads, so the app needs no changes.
//
// Protocol (115200 baud, newline-terminated):
//   out: S,<ms>,<temple>,<forearm>,<ax_mg>,<ay_mg>,<az_mg>   temple/forearm = 0 when the headband is silent
//        # ...                                               info lines (ignored by the laptop)
//   in:  A,<thumb>,<index>,<middle>,<ring>,<pinky>   app angles 0-160, scaled to 0-SERVO_OUT_MAX here
//        B,<hz>,<ms>  buzzer (if PIN_BUZZER set)      L,<G|R|O>  LEDs (if LED pins set)
// Safety: no A command for 500 ms -> hand opens. Headband silent for 300 ms -> reports 0 -> app opens hand.

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <ESP32Servo.h>

// ---- pins (from the team's servo test sketch) ----
const int SERVO_PINS[5] = {13, 12, 11, 10, 9};  // thumb, index, middle, ring, pinky
const int PIN_BUZZER    = -1;                     // set a GPIO to enable, e.g. 4
const int PIN_LED_GREEN = -1;                     // e.g. 5
const int PIN_LED_RED   = -1;                     // e.g. 6

const int NUM_SERVOS = 5;
const int APP_MAX = 160;          // the app sends 0..160
const int SERVO_OUT_MAX = 180;    // this hand closes fully at 180 (from the test sketch)
const unsigned long SAMPLE_MS = 20;        // 50 Hz to the laptop
const unsigned long WATCHDOG_MS = 500;
const unsigned long HEADBAND_STALE_MS = 300;
const uint8_t ESPNOW_CHANNEL = 1;          // must match the headband

const uint32_t PAD_MAGIC = 0x4E475042;     // "NGPB"
struct __attribute__((packed)) PadPacket {
  uint32_t magic;
  uint32_t seq;
  uint32_t ms;
  uint16_t temple;
  uint16_t forearm;
};

Servo servos[NUM_SERVOS];
volatile uint16_t rxTemple = 0, rxForearm = 0;
volatile unsigned long rxAt = 0;
volatile uint32_t rxCount = 0;
unsigned long lastSample = 0, lastServoCmd = 0;
bool servosNeutral = true, linkUp = false;
char buf[48];
int bufLen = 0;

void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len != (int)sizeof(PadPacket)) return;
  PadPacket p;
  memcpy(&p, data, sizeof(p));
  if (p.magic != PAD_MAGIC) return;
  rxTemple = p.temple;
  rxForearm = p.forearm;
  rxAt = millis();
  rxCount++;
}

void setServos(const int *vals) {
  for (int i = 0; i < NUM_SERVOS; i++) {
    int v = constrain(vals[i], 0, APP_MAX);
    servos[i].write(map(v, 0, APP_MAX, 0, SERVO_OUT_MAX));
  }
}

void openHand() {
  const int zeros[NUM_SERVOS] = {0, 0, 0, 0, 0};
  setServos(zeros);
}

void setLeds(char s) {
  if (PIN_LED_GREEN >= 0) digitalWrite(PIN_LED_GREEN, s == 'G' ? HIGH : LOW);
  if (PIN_LED_RED >= 0) digitalWrite(PIN_LED_RED, s == 'R' ? HIGH : LOW);
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
    if (PIN_BUZZER >= 0 && sscanf(line, "B,%d,%d", &hz, &ms) == 2 && hz > 0 && ms > 0) tone(PIN_BUZZER, hz, ms);
  } else if (line[0] == 'L' && line[1] == ',') {
    setLeds(line[2]);
  }
}

void readCommands() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (bufLen > 0) { buf[bufLen] = '\0'; handleLine(buf); bufLen = 0; }
    } else if (bufLen < (int)sizeof(buf) - 1) {
      buf[bufLen++] = ch;
    } else {
      bufLen = 0;
    }
  }
}

void setup() {
  Serial.begin(115200);
  if (PIN_LED_GREEN >= 0) pinMode(PIN_LED_GREEN, OUTPUT);
  if (PIN_LED_RED >= 0) pinMode(PIN_LED_RED, OUTPUT);
  setLeds('O');

  for (int i = 0; i < NUM_SERVOS; i++) {
    servos[i].setPeriodHertz(50);
    servos[i].attach(SERVO_PINS[i], 500, 2400);
  }
  openHand();

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  bool ok = esp_now_init() == ESP_OK && esp_now_register_recv_cb(onRecv) == ESP_OK;
  Serial.printf("# NeuroGrip hand firmware | ESP32-S3 | servos 13,12,11,10,9 | ESP-NOW %s ch%d | waiting for headband\n",
                ok ? "ready" : "FAILED", ESPNOW_CHANNEL);
}

void loop() {
  readCommands();
  unsigned long now = millis();

  if (!servosNeutral && now - lastServoCmd > WATCHDOG_MS) {
    openHand();
    setLeds('O');
    servosNeutral = true;
  }

  bool fresh = rxAt != 0 && now - rxAt <= HEADBAND_STALE_MS;
  if (fresh != linkUp) {
    linkUp = fresh;
    Serial.printf("# headband link %s (%lu packets)\n", linkUp ? "UP" : "LOST", (unsigned long)rxCount);
  }

  if (now - lastSample >= SAMPLE_MS) {
    lastSample = now;
    unsigned int t = fresh ? rxTemple : 0, f = fresh ? rxForearm : 0;
    Serial.printf("S,%lu,%u,%u,0,0,1000\n", now, t, f);
  }
}
