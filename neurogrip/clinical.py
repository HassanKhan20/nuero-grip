"""Camera-based clinical screening: hand tremor and finger-tapping (bradykinesia).

These are screening indicators for a therapist, not diagnoses.
"""
import numpy as np

CV_TREMOR_MIN_AMP = 0.0015   # normalized image units; below this is camera jitter
TAP_HI, TAP_LO = 0.30, 0.15  # hysteresis thresholds as a fraction of the pinch range
MIN_TAP_RANGE = 0.05


def _detrend(x: np.ndarray) -> np.ndarray:
    n = np.arange(len(x))
    slope, intercept = np.polyfit(n, x, 1)
    return x - (slope * n + intercept)


def cv_tremor(ts: np.ndarray, xy: np.ndarray, fs: float = 30.0) -> tuple[float, float]:
    """Dominant 3-12 Hz oscillation of a tracked landmark. Returns (hz, rms amplitude)."""
    ts, xy = np.asarray(ts, float), np.asarray(xy, float)
    if len(ts) < 30 or ts[-1] - ts[0] < 1.0:
        return 0.0, 0.0
    tu = np.arange(ts[0], ts[-1], 1 / fs)
    cols = [_detrend(np.interp(tu, ts, xy[:, i])) for i in range(2)]
    m = np.column_stack(cols)
    u, s, _ = np.linalg.svd(m - m.mean(axis=0), full_matrices=False)
    principal = u[:, 0] * s[0]
    amp = float(np.sqrt(np.mean(principal ** 2)))
    if amp < CV_TREMOR_MIN_AMP:
        return 0.0, round(amp, 4)
    spec = np.abs(np.fft.rfft(principal * np.hanning(len(principal))))
    freqs = np.fft.rfftfreq(len(principal), 1 / fs)
    band = (freqs >= 3) & (freqs <= 12)
    return round(float(freqs[band][np.argmax(spec[band])]), 2), round(amp, 4)


def analyze_tapping(ts: np.ndarray, pinch: np.ndarray) -> dict:
    """Thumb-index tapping test (MDS-UPDRS 3.4 style): count, rate, amplitude decrement, rhythm."""
    ts, pinch = np.asarray(ts, float), np.asarray(pinch, float)
    if len(ts) < 2:
        return {"error": "too few taps", "taps": 0}
    lo, rng = float(pinch.min()), float(np.ptp(pinch))
    if rng < MIN_TAP_RANGE:
        return {"error": "too few taps", "taps": 0}
    hi_thr, lo_thr = lo + TAP_HI * rng, lo + TAP_LO * rng

    starts, amps = [], []
    above, peak = False, 0.0
    for t, p in zip(ts, pinch):
        if not above and p > hi_thr:
            above, peak = True, p
            starts.append(t)
        elif above:
            peak = max(peak, p)
            if p < lo_thr:
                above = False
                amps.append(peak - lo)
    if above:
        amps.append(peak - lo)

    n = len(starts)
    if n < 3:
        return {"error": "too few taps", "taps": n}
    duration = ts[-1] - ts[0]
    rate = n / duration
    third = max(1, n // 3)
    first, last = np.mean(amps[:third]), np.mean(amps[-third:])
    decrement = (first - last) / first * 100 if first else 0.0
    intervals = np.diff(starts)
    rhythm_cv = float(np.std(intervals) / np.mean(intervals)) if len(intervals) > 1 else 0.0
    flag = "possible bradykinesia" if rate < 2.0 or decrement > 25 else "within typical range"
    return {
        "taps": n,
        "rate_hz": round(rate, 2),
        "mean_amplitude": round(float(np.mean(amps)), 3),
        "decrement_pct": round(float(decrement), 1),
        "rhythm_cv": round(rhythm_cv, 3),
        "flag": flag,
    }
