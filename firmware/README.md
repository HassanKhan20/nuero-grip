# ESP32 firmware

**Board:** Inland ESP32 dev board with an **ESP32-WROOM-32E** (classic ESP32, not an S3).
**Arduino IDE:**
- Board: **"ESP32 Dev Module"** (Boards Manager → *esp32 by Espressif*, version 3.x)
- Library: **ESP32Servo** ≥ 3.0 (Library Manager)

## Wiring

All five servos and both pads go on the **left header** (the side labelled IO13 … IO33). The buzzer, LEDs and accelerometer go on the **right header**.

| Part | Pin (silkscreen label) | Notes |
|---|---|---|
| Servo 1: **thumb** (signal) | **IO13** | |
| Servo 2: **index** (signal) | **IO14** | may twitch once at power-on, harmless |
| Servo 3: **middle** (signal) | **IO27** | |
| Servo 4: **ring** (signal) | **IO26** | |
| Servo 5: **pinky** (signal) | **IO25** | |
| **Temple** foil pad | **IO32** | touch channel T9 |
| **Forearm** foil pad | **IO33** | touch channel T8 |
| Grove buzzer (SIG) | IO18 | |
| Grove LED green / red (SIG) | IO19 / IO23 | |
| Grove accelerometer SDA / SCL | IO21 / IO22 | ADXL345 *or* LIS3DHTR, auto-detected |
| Grove modules VCC / GND | 3V3 / GND | |

**Never connect anything to:**
- **SD0–SD3, CMD, CLK** (top-left pins). They're wired to the flash chip, and the board will crash.
- **IO12.** It's a boot strapping pin: if something pulls it high at power-on, the board won't boot.
- **IO34–IO39 / SVP / SVN** for outputs. They're input-only.

### Servo power (SG90 × 5, 4×AA pack)

```
4xAA (+) ──────────────► all 5 servo red (+) wires
4xAA (−) ──┬───────────► all 5 servo brown (−) wires
           └───────────► ESP32 GND           ← shared ground, required
470–1000 µF capacitor across the pack (+/−), close to the servos
ESP32 is powered by the laptop USB cable, NOT the AA pack
```

- **Current:** SG90s draw about 250 mA while moving but about **650 mA each when stalled** (gripping something). Five gripping at once can pull about 3 A and sag the batteries. The capacitor smooths the spikes. If servos jitter or the ESP32 resets, use fresh batteries or a 5V/3A supply.
- **Voltage:** fresh alkalines give about 6.4 V, slightly over the SG90's 6 V rating. That's fine for a demo. 4× NiMH rechargeables (4.8 V) are gentler.

### Foil pads (the intent sensors)

1. Cut foil about 3 × 3 cm and press a jumper wire's bare end onto it. Tape it so it stays put.
2. Put a **thin soft layer** (foam, felt, or folded cloth) between the foil and the skin, then strap it on firmly. Muscle effort squeezes that layer, the skin gets closer to the foil, and the reading changes **gradually**. Bare foil on skin reads "touched" all the time and barely changes.
3. **Temple pad:** inside the headband, over the jaw muscle at the temple (it tightens when you clench). **Forearm pad:** on the inner forearm, over the grip muscles.
4. Keep pad wires **short**, taped down, and **away from the servo wires**. Long or loose wires act like antennas.

## Flash and test

1. Plug in USB, choose the port, and click Upload. If it hangs on "Connecting…", hold **BOOT** until it starts.
2. Open Serial Monitor at **115200**. The first line tells you which accelerometer was found:
   ```
   # NeuroGrip firmware 2 | ESP32-WROOM-32E | accel=ADXL345 | touch T9(IO32)=temple T8(IO33)=forearm
   S,1234,71,68,4,-12,1002
   ```
   In the `S,...` lines, the 2nd and 3rd numbers are the temple and forearm pads.
3. **Pad test:** clench or squeeze through the foam. The pad numbers should **drop** (classic ESP32 readings fall on touch). Touching the bare foil drops them a lot.
4. **Servo test:** send `A,90,90,90,90,90`. All five servos move, then return to 0 within 0.5 s. That's the safety watchdog, which opens the hand whenever the laptop stops talking.
5. **Buzzer test:** send `B,1000,300`. **LED test:** send `L,G`, `L,R`, `L,O`.
6. **Buzzer and servo together:** keep sending `A,90,90,90,90,90` while sending `B,1000,200`. No servo should twitch. If one does, update the esp32 board package to 3.x.

**Close Serial Monitor before running `app.py`.** Only one program can use the COM port.

## Run with the app

```powershell
$env:NG_MODE = "hardware"
$env:NG_SERIAL_PORT = "COM5"     # Device Manager → Ports (COM & LPT)
.venv\Scripts\python app.py
```

Hardware mode starts in **Intent only** control: the headband alone moves the fingers. Then:
1. Click **Calibrate** on the Motor intent tile.
2. **Relax** for 2 s.
3. **Clench your jaw and squeeze** as hard as you can for 3 s.
4. From then on, intent is scaled to *your* pads: relaxed = open hand, full squeeze = full grip.
