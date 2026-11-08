"""Live graph of the headband (temple, IO32) and forearm (IO33) pads. Close Serial Monitor and the app first.

    .venv\\Scripts\\python scripts\\pad_graph.py [COM3]

Put the pad ON, sit relaxed, press B to take the baseline while wearing it. Then focus:
the temple line should rise clearly and fall back to ~0 when you relax. The y-axis zooms to the signal,
so even a few % is visible. Press B again any time to re-baseline. Close the window to stop.
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
state = {"base": None, "peak": 0.0, "rebase": False}


def reader(s: serial.Serial) -> None:
    calib, t0 = [], time.time()
    while True:
        f = parse_sensor_line(s.readline().decode(errors="ignore"))
        if not f:
            continue
        t = time.time() - t0
        if state["rebase"]:
            state.update(base=None, peak=0.0, rebase=False)
            calib, t0 = [], time.time()
            data.clear()
            continue
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
    ax.text(0.01, GOOD_PCT + 0.6, f"{GOOD_PCT}% = good focus", transform=ax.get_yaxis_transform(), color="#B7791F")
    ax.axhline(0, color="#999", lw=0.8)
    ax.set_xlabel("seconds")
    ax.set_ylabel("change from relaxed (%)")
    ax.legend(loc="upper right")
    title = ax.set_title("Measuring baseline: sit still and relaxed...", fontsize=14)
    fig.text(0.01, 0.01, "Press B to re-baseline (do it while WEARING the pad, relaxed)", color="#5B6478")

    def on_key(ev):
        if ev.key in ("b", "B", " "):
            state["rebase"] = True
            title.set_text("Measuring baseline: sit still and relaxed...")
    fig.canvas.mpl_connect("key_press_event", on_key)

    def update(_):
        if state["base"] is None:
            return lt, lf, title
        if data:
            ts, dts, dfs = zip(*data)
            lt.set_data(ts, dts)
            lf.set_data(ts, dfs)
            ax.set_xlim(max(0, ts[-1] - WINDOW_S), max(WINDOW_S, ts[-1]))
            lo, hi = min(min(dts), min(dfs)), max(max(dts), max(dfs))
            pad = max(1.0, (hi - lo) * 0.15)
            ax.set_ylim(min(-2, lo - pad), max(GOOD_PCT + 2 if hi > GOOD_PCT / 2 else 5, hi + pad))
            now, peak = dts[-1], state["peak"]
            verdict = ("strong" if peak >= GOOD_PCT else "usable: the app's calibration scales this up" if peak >= 2
                       else "too small: move the pad / tighten strap")
            title.set_text(f"Temple now {now:+.1f}%   ·   peak {peak:.1f}%  ({verdict})")
            title.set_color("#2E7D5B" if peak >= 2 else "#1B2233")
        return lt, lf, title

    _anim = FuncAnimation(fig, update, interval=100, cache_frame_data=False)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
