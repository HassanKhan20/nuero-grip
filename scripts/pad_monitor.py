"""Live view of the headband (temple, IO32) and forearm (IO33) pads. Close Serial Monitor and the app first.

    .venv\\Scripts\\python scripts\\pad_monitor.py [COM3]

Sit still for the first 2 s (baseline), then clench your jaw. A good pad shows a clear, repeatable
change (10%+) when you clench and returns to ~0% when you relax. Ctrl+C to stop.
"""
import statistics
import sys
import time

import serial

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
from neurogrip.protocol import parse_sensor_line  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"


def bar(pct: float) -> str:
    n = max(0, min(30, int(abs(pct) / 2)))
    return ("#" * n).ljust(30)


def main():
    s = serial.Serial(PORT, 115200, timeout=0.5)
    print("Baseline: sit still and relaxed for 2 s...")
    base, end = [], time.time() + 2
    while time.time() < end:
        f = parse_sensor_line(s.readline().decode(errors="ignore"))
        if f:
            base.append((f.temple, f.forearm))
    if not base:
        sys.exit("No sensor data: is the NeuroGrip firmware flashed and COM port right?")
    bt = statistics.median(b[0] for b in base)
    bf = statistics.median(b[1] for b in base)
    print(f"Baseline temple={bt:.0f} forearm={bf:.0f}. Now clench / relax. Ctrl+C to stop.\n")
    peak_t = 0.0
    last = 0.0
    try:
        while True:
            f = parse_sensor_line(s.readline().decode(errors="ignore"))
            if not f or time.time() - last < 0.1:
                continue
            last = time.time()
            dt = (bt - f.temple) / bt * 100 if bt else 0
            df = (bf - f.forearm) / bf * 100 if bf else 0
            peak_t = max(peak_t, abs(dt))
            print(f"\rtemple {f.temple:5d} {dt:+6.1f}% |{bar(dt)}|  forearm {f.forearm:5d} {df:+6.1f}% "
                  f"|{bar(df)}|  temple peak {peak_t:4.1f}%", end="", flush=True)
    except KeyboardInterrupt:
        print(f"\n\nTemple peak change: {peak_t:.1f}%  ->  "
              + ("good" if peak_t >= 10 else "weak: see tips in firmware/README.md (foam layer, firmer strap)"
                 if peak_t >= 3 else "no response: check the wire is on IO32 and touches the foil"))


if __name__ == "__main__":
    main()
