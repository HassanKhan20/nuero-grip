# ESP32 firmware

Board: classic ESP32 DevKit ("ESP32 Dev Module" in Arduino IDE). Library: **ESP32Servo** (Library Manager).

| Part | ESP32 pin |
|---|---|
| Temple touch electrode | GPIO4 (T0) |
| Forearm touch electrode | GPIO15 (T3) |
| Servo thumb / index / rest (signal) | GPIO13 / GPIO12 / GPIO14 |
| Grove buzzer | GPIO25 |
| Grove LED green / red | GPIO26 / GPIO27 |
| Grove 3-axis accelerometer (ADXL345, ±16g) SDA / SCL | GPIO21 / GPIO22 |

**Servo power:** run the servos from a separate 5V supply (USB battery pack or bench supply). Connect its ground to the ESP32 GND. Don't power the servos from the ESP32. Three servos will brown it out and reset the board.

**Different parts?**
- On an ESP32-S3, touch pins and readings differ. Change `PIN_TOUCH_*`. The Python side handles readings that rise on touch as well as ones that fall.
- With a different accelerometer (e.g. the LIS3DHTR Grove module), replace `adxlRead`. It must return milli-g.

**Check after flashing:** open Serial Monitor at 115200. `S,...` lines should stream at about 50 per second. Send `A,90,90,90` and the servos should move, then go back to 0 within 0.5 s because no further `A` commands arrive. That's the safety watchdog.

Close Serial Monitor before running `app.py`, because only one program can hold the COM port.
