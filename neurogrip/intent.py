"""Dual-site capacitive intent detection (temple + forearm)."""
from dataclasses import dataclass

import numpy as np

from .protocol import SensorFrame


@dataclass
class IntentState:
    calibrated: bool
    active: bool
    strength: float
    temple_drop: float
    forearm_drop: float


def _drop(baseline: float, value: float) -> float:
    # abs(): classic ESP32 touch readings fall on contact, ESP32-S3 readings rise
    return abs(baseline - value) / baseline if baseline else 0.0


class IntentDetector:
    def __init__(self, threshold: float = 0.14, calib_frames: int = 100):
        self.threshold = threshold
        self.calib_frames = calib_frames
        self._calib: list[tuple[int, int]] = []
        self._baseline: tuple[float, float] | None = None

    def update(self, f: SensorFrame) -> IntentState:
        if self._baseline is None:
            self._calib.append((f.temple, f.forearm))
            if len(self._calib) >= self.calib_frames:
                arr = np.array(self._calib, dtype=float)
                self._baseline = (float(np.median(arr[:, 0])), float(np.median(arr[:, 1])))
            return IntentState(False, False, 0.0, 0.0, 0.0)
        t = _drop(self._baseline[0], f.temple)
        fa = _drop(self._baseline[1], f.forearm)
        active = t >= self.threshold and fa >= self.threshold
        strength = max(0.0, min(1.0, min(t, fa) / (2 * self.threshold)))
        return IntentState(True, active, strength, round(t, 3), round(fa, 3))
