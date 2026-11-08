// EMG sensor check. Upload, then open Tools > Serial Plotter at 115200 baud.
// Relax the forearm, then squeeze a fist: the "smooth" line should rise clearly and fall back.
// Wiring: sensor signal (MyoWare 2.0: ENV) -> IO34, sensor + -> 3V3 (NOT 5V), sensor - -> GND.

const int EMG_PIN = 34;  // ADC1, input-only: safe analog pin on the classic ESP32

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);  // 0-4095 for 0-3.3 V
}

void loop() {
  static float smooth = 0;
  int raw = analogRead(EMG_PIN);
  smooth = smooth * 0.9f + raw * 0.1f;
  Serial.printf("raw:%d smooth:%d\n", raw, (int)smooth);
  delay(10);  // ~100 readings per second
}
