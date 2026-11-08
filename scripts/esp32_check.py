"""Guided ESP32 bench test: run with the board plugged in and the app NOT running in hardware mode.

    .venv\\Scripts\\python scripts\\esp32_check.py [COM3]

Checks the sensor stream, each touch pad, the accelerometer, LEDs, buzzer and every finger servo.
"""
import math
import statistics
import sys
import threading
import time

import serial

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
from neurogrip.protocol import FINGERS, fmt_buzzer, fmt_led, fmt_servo, parse_sensor_line  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"
results: list[tuple[str, bool | None, str]] = []


def record(name, ok, note=""):
    results.append((name, ok, note))
    mark = {True: "PASS", False: "FAIL", None: "SKIP"}[ok]
    print(f"  [{mark}] {name}{' - ' + note if note else ''}")


def ask(q: str) -> bool | None:
    a = input(f"  {q} [y/n/s=skip] ").strip().lower()
    return True if a.startswith("y") else None if a.startswith("s") else False


class Board:
    def __init__(self, port):
        self.s = serial.Serial(port, 115200, timeout=0.2)
        self.banner, self.latest, self.frames = [], None, 0
        self._stop = False
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while not self._stop:
            line = self.s.readline().decode(errors="ignore").strip()
            if line.startswith("#"):
                self.banner.append(line)
            f = parse_sensor_line(line)
            if f:
                self.latest, self.frames = f, self.frames + 1

    def send(self, cmd):
        self.s.write(cmd.encode())

    def sample(self, seconds, key):
        vals, end = [], time.time() + seconds
        while time.time() < end:
            if self.latest:
                vals.append(key(self.latest))
            time.sleep(0.02)
        return vals

    def hold_servos(self, angles, seconds):
        """Keep re-sending: the firmware opens the hand after 500 ms without a command (watchdog)."""
        end = time.time() + seconds
        while time.time() < end:
            self.send(fmt_servo(*angles))
            time.sleep(0.1)


def main():
    print(f"Opening {PORT} ... (close Arduino Serial Monitor and the app if they are using it)")
    b = Board(PORT)
    b.s.setRTS(True); time.sleep(0.1); b.s.setRTS(False)  # reset to catch the startup banner
    time.sleep(3)

    print("\n1) Firmware and sensor stream")
    banner = next((l for l in b.banner if "firmware" in l), "")
    record("firmware banner", bool(banner), banner or "no banner; is this the NeuroGrip firmware?")
    n0 = b.frames; time.sleep(2); rate = (b.frames - n0) / 2
    record("sensor stream ~50 Hz", 40 <= rate <= 60, f"{rate:.0f} frames/s")

    print("\n2) Accelerometer")
    if "accel=none" in banner:
        record("accelerometer detected", False, "not found: check VCC->3V3, GND, SDA->IO21, SCL->IO22 (swap SDA/SCL first)")
    else:
        still = b.sample(2, lambda f: math.sqrt(f.ax ** 2 + f.ay ** 2 + f.az ** 2))
        record("accelerometer at rest ~1000 mg", 700 < statistics.median(still) < 1300, f"{statistics.median(still):.0f} mg")
        input("  Now SHAKE the accelerometer for 2 s, press Enter to start...")
        shake = b.sample(2, lambda f: math.sqrt(f.ax ** 2 + f.ay ** 2 + f.az ** 2))
        record("accelerometer responds to shaking", max(shake) - min(shake) > 300, f"range {max(shake) - min(shake):.0f} mg")

    print("\n3) Touch pads (classic ESP32: readings DROP on touch)")
    for name, key in (("temple (IO32)", lambda f: f.temple), ("forearm (IO33)", lambda f: f.forearm)):
        input(f"  Don't touch the {name} pad/wire. Press Enter...")
        rest = statistics.median(b.sample(1.5, key))
        input(f"  Now TOUCH (or squeeze through the foam on) the {name} pad and hold it. Press Enter...")
        touch = statistics.median(b.sample(1.5, key))
        drop = (rest - touch) / rest * 100 if rest else 0
        record(f"{name} responds", drop > 5, f"rest {rest:.0f} -> touched {touch:.0f} ({drop:.0f}% drop)")

    print("\n4) LEDs and buzzer")
    b.send(fmt_led("G")); time.sleep(0.2)
    record("green LED", ask("Is the GREEN LED on?"))
    b.send(fmt_led("R")); time.sleep(0.2)
    record("red LED", ask("Is the RED LED on?"))
    b.send(fmt_led("O"))
    b.send(fmt_buzzer(1000, 400)); time.sleep(0.5)
    record("buzzer", ask("Did the buzzer beep?"))

    print("\n5) Servos (needs the AA pack connected, with its - tied to ESP32 GND)")
    for i, finger in enumerate(FINGERS):
        angles = [0] * 5
        angles[i] = 90
        print(f"  Moving {finger} to 90 degrees for 1.5 s...")
        b.hold_servos(angles, 1.5)
        b.hold_servos([0] * 5, 0.5)
        record(f"servo {finger}", ask(f"Did ONLY the {finger} servo move and come back?"))
    print("  All five to 90 degrees while the buzzer sounds (checks power + no twitching)...")
    b.send(fmt_buzzer(1000, 1200))
    b.hold_servos([90] * 5, 1.5)
    record("all servos under load, no twitch", ask("Did all five move smoothly without the board resetting?"))
    print("  Stopping commands: the watchdog should open the hand within 0.5 s...")
    b.hold_servos([90] * 5, 0.5)
    time.sleep(1.0)
    record("safety watchdog", ask("Did all fingers return to open on their own?"))

    b._stop = True
    fails = [r for r in results if r[1] is False]
    print(f"\nDone: {sum(r[1] is True for r in results)} passed, {len(fails)} failed, "
          f"{sum(r[1] is None for r in results)} skipped.")
    for name, _, note in fails:
        print(f"  FAIL {name}: {note}")


if __name__ == "__main__":
    main()
