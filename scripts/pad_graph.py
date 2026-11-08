"""Live graph of the headband (temple, IO32) and forearm (IO33) pads. Close Serial Monitor and the app first.

    .venv\\Scripts\\python scripts\\pad_graph.py [COM3]

Sit still for the first 2 s (baseline). Then clench your jaw: the temple line should jump above the
dashed 10% line and fall back to ~0 when you relax. Close the window to stop.
"""
import collections
import statistics
import sys
import threading
import time

import matplotlib.pyplot as plt
import serial
from matplotlib.animation import FuncAnimation

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
from neurogrip.protocol import parse_sensor_line  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"
WINDOW_S = 10
GOOD_PCT = 10

data = collections.deque(maxlen=WINDOW_S * 50)  # (t, temple, forearm) at ~50 Hz
state = {"base": None, "peak": 0.0}


def reader(s: serial.Serial) -> None:
    calib, t0 = [], time.time()
    while True:
        f = parse_sensor_line(s.readline().decode(errors="ignore"))
        if not f:
            continue
        t = time.time() - t0
        if state["base"] is None:
            calib.append((f.temple, f.forearm))
            if t >= 2 and calib:
                state["base"] = (statistics.median(c[0] for c in calib), statistics.median(c[1] for c in calib))
            continue
        bt, bf = state["base"]
        dt = (bt - f.temple) / bt * 100 if bt else 0.0
        df = (bf - f.forearm) / bf * 100 if bf else 0.0
        state["peak"] = max(state["peak"], dt)
        data.append((t, dt, df))


def main():
    s = serial.Serial(PORT, 115200, timeout=0.5)
    threading.Thread(target=reader, args=(s,), daemon=True).start()

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.canvas.manager.set_window_title("NeuroGrip pad check")
    (lt,) = ax.plot([], [], lw=2.5, color="#5562D6", label="Temple pad (headband, IO32)")
    (lf,) = ax.plot([], [], lw=1.5, color="#5FB3B3", alpha=0.8, label="Forearm pad (IO33)")
    ax.axhline(GOOD_PCT, ls="--", color="#B7791F", lw=1)
    ax.text(0.01, GOOD_PCT + 0.6, f"{GOOD_PCT}% = good clench", transform=ax.get_yaxis_transform(), color="#B7791F")
    ax.axhline(0, color="#999", lw=0.8)
    ax.set_xlabel("seconds")
    ax.set_ylabel("change from relaxed (%)")
    ax.legend(loc="upper right")
    title = ax.set_title("Measuring baseline: sit still and relaxed...", fontsize=14)

    def update(_):
        if state["base"] is None:
            return lt, lf, title
        if data:
            ts, dts, dfs = zip(*data)
            lt.set_data(ts, dts)
            lf.set_data(ts, dfs)
            ax.set_xlim(max(0, ts[-1] - WINDOW_S), max(WINDOW_S, ts[-1]))
            top = max(25, max(dts) + 5, max(dfs) + 5)
            ax.set_ylim(min(-5, min(dts) - 2, min(dfs) - 2), top)
            now, peak = dts[-1], state["peak"]
            verdict = "GOOD" if peak >= GOOD_PCT else "weak: firmer strap / thinner foam" if peak >= 3 else "no response yet"
            title.set_text(f"Temple now {now:+.1f}%   ·   peak {peak:.1f}%  ({verdict})   ·   clench your jaw")
            title.set_color("#2E7D5B" if peak >= GOOD_PCT else "#1B2233")
        return lt, lf, title

    _anim = FuncAnimation(fig, update, interval=100, cache_frame_data=False)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
