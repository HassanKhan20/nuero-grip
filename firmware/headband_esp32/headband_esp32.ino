// NeuroGrip HEADBAND firmware (classic ESP32, e.g. Inland ESP32-WROOM-32E). Runs on a power bank.
// Reads the temple foil pad (and optional forearm pad) at 50 Hz and broadcasts it over ESP-NOW to the
// hand board, which forwards it to the laptop. No router, no pairing: both boards just use channel 1.
//
// Also prints the same "S,..." line on USB serial, so scripts/pad_graph.py works when it's plugged in.
// Built-in LED (GPIO2) blinks while sending.

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

const int PIN_TOUCH_TEMPLE  = 32;   // T9: foil pad in the headband
const int PIN_TOUCH_FOREARM = 33;   // T8: optional second pad (reads ~constant if unused)
const int PIN_LED = 2;              // on-board blue LED on most classic ESP32 dev boards
const uint8_t ESPNOW_CHANNEL = 1;   // must match the hand firmware
const unsigned long SAMPLE_MS = 20; // 50 Hz
const int TOUCH_SAMPLES = 4;

const uint32_t PAD_MAGIC = 0x4E475042;  // "NGPB": lets the hand board ignore any other ESP-NOW traffic
struct __attribute__((packed)) PadPacket {
  uint32_t magic;
  uint32_t seq;
  uint32_t ms;
  uint16_t temple;
  uint16_t forearm;
};

uint8_t BROADCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
uint32_t seq = 0;
uint32_t sendErrors = 0;
unsigned long lastSample = 0;

uint32_t touchAvg(int pin) {
  uint32_t sum = 0;
  for (int i = 0; i < TOUCH_SAMPLES; i++) sum += touchRead(pin);
  return sum / TOUCH_SAMPLES;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  bool ok = esp_now_init() == ESP_OK;
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BROADCAST, 6);
  peer.channel = ESPNOW_CHANNEL;
  peer.encrypt = false;
  ok = ok && esp_now_add_peer(&peer) == ESP_OK;

  Serial.printf("# NeuroGrip headband | ESP-NOW %s ch%d | touch T9(IO32)=temple T8(IO33)=forearm\n",
                ok ? "ready" : "FAILED", ESPNOW_CHANNEL);
}

void loop() {
  unsigned long now = millis();
  if (now - lastSample < SAMPLE_MS) return;
  lastSample = now;

  PadPacket p = {PAD_MAGIC, seq++, (uint32_t)now,
                 (uint16_t)touchAvg(PIN_TOUCH_TEMPLE), (uint16_t)touchAvg(PIN_TOUCH_FOREARM)};
  if (esp_now_send(BROADCAST, (const uint8_t *)&p, sizeof(p)) != ESP_OK) sendErrors++;

  digitalWrite(PIN_LED, (seq / 10) % 2);  // ~2.5 Hz blink = sending
  Serial.printf("S,%lu,%u,%u,0,0,1000\n", now, p.temple, p.forearm);
  if (seq % 500 == 0) Serial.printf("# sent %lu packets, %lu send errors\n", (unsigned long)seq, (unsigned long)sendErrors);
}
