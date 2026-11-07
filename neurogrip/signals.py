"""Accelerometer signal analysis: tremor frequency and steadiness."""
import numpy as np

MIN_TREMOR_RMS_MG = 15.0


def _detrend(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    n = np.arange(len(x))
    slope, intercept = np.polyfit(n, x, 1)
    return x - (slope * n + intercept)


def tremor_frequency(mag_mg: np.ndarray, fs: float = 50.0) -> float:
    x = _detrend(mag_mg)
    if np.sqrt(np.mean(x ** 2)) < MIN_TREMOR_RMS_MG:
        return 0.0
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / fs)
    band = (freqs >= 3) & (freqs <= 12)
    return round(float(freqs[band][np.argmax(spec[band])]), 2)


def steadiness(mag_mg: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(_detrend(mag_mg) ** 2)))
    return round(max(0.0, 100.0 - rms / 2), 1)
