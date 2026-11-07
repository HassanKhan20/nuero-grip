# ESP32 firmware

Board: classic ESP32 DevKit ("ESP32 Dev Module" in Arduino IDE). **Use the Arduino-ESP32 core 3.x** (Boards Manager → esp32 by Espressif ≥ 3.0) and **ESP32Servo ≥ 3.0** (Library Manager). On core 2.x, `tone()` can take the same PWM channel as the thumb servo and break it.

Five servos, one per finger. Don't move a servo onto GPIO 0, 2, 5, 12 or 15. Those are boot strapping pins, and the board can fail to boot if one is pulled high.

| Part | ESP32 pin |
|---|---|
| Temple touch electrode | GPIO4 (T0) |
| Forearm touch electrode | GPIO15 (T3) |
| Servo thumb / index / middle / ring / pinky (signal) | GPIO13 / GPIO18 / GPIO19 / GPIO23 / GPIO33 |
| Grove buzzer | GPIO25 |
| Grove LED green / red | GPIO26 / GPIO27 |
| Grove 3-axis accelerometer (ADXL345, ±16g) SDA / SCL | GPIO21 / GPIO22 |

**Servo power:** run the servos from a separate 5V supply (USB battery pack or bench supply). Connect its ground to the ESP32 GND. Don't power the servos from the ESP32. Five servos will brown it out and reset the board. Size the supply for at least **3 A at 5V**, because five servos stalling on a grip can each draw 0.5–1 A.

**Different parts?**
- On an ESP32-S3, touch pins and readings differ. Change `PIN_TOUCH_*`. The Python side handles readings that rise on touch as well as ones that fall.
- With a different accelerometer (e.g. the LIS3DHTR Grove module), replace `adxlRead`. It must return milli-g.

**Check after flashing:** open Serial Monitor at 115200. `S,...` lines should stream at about 50 per second. Send `A,90,90,90,90,90` and all five servos should move, then go back to 0 within 0.5 s because no further `A` commands arrive. That's the safety watchdog.

**Buzzer + servo bench test:** keep sending `A,90,90,90,90,90` while sending `B,1000,200`. If the thumb servo twitches or goes limp, the buzzer and the servo are sharing a PWM channel. Check the core version.

Close Serial Monitor before running `app.py`, because only one program can hold the COM port.
