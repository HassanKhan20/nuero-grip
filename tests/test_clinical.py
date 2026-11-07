import numpy as np

from neurogrip.clinical import analyze_tapping, cv_tremor

FS = 30.0


def _ts(seconds):
    return np.arange(0, seconds, 1 / FS)


def test_cv_tremor_detects_5hz():
    t = _ts(5)
    rng = np.random.default_rng(0)
    xy = np.column_stack([0.5 + 0.004 * np.sin(2 * np.pi * 5 * t), 0.6 + rng.normal(0, 0.0003, len(t))])
    hz, amp = cv_tremor(t, xy)
    assert abs(hz - 5) < 0.4 and amp > 0.002


def test_cv_tremor_zero_when_still():
    t = _ts(5)
    rng = np.random.default_rng(1)
    xy = np.column_stack([0.5 + rng.normal(0, 0.0005, len(t)), 0.6 + rng.normal(0, 0.0005, len(t))])
    assert cv_tremor(t, xy)[0] == 0.0


def _taps(rate, seconds, amp_start=1.0, amp_end=1.0):
    t = _ts(seconds)
    amp = np.linspace(amp_start, amp_end, len(t))
    return t, 0.1 + 0.6 * amp * (0.5 + 0.5 * np.sin(2 * np.pi * rate * t - np.pi / 2))


def test_tapping_steady():
    r = analyze_tapping(*_taps(3, 10))
    assert 29 <= r["taps"] <= 31
    assert abs(r["rate_hz"] - 3) < 0.2
    assert abs(r["decrement_pct"]) < 10
    assert r["flag"] == "within typical range"


def test_tapping_decrement():
    r = analyze_tapping(*_taps(3, 10, 1.0, 0.4))
    assert r["decrement_pct"] > 30 and r["flag"] == "possible bradykinesia"


def test_tapping_slow_rate_flagged():
    r = analyze_tapping(*_taps(1.2, 10))
    assert r["flag"] == "possible bradykinesia"


def test_tapping_too_few_taps():
    t = _ts(10)
    r = analyze_tapping(t, np.full(len(t), 0.5))
    assert r["error"] == "too few taps"
