"""Dual-site capacitive intent detection (temple + forearm).

Each site is a foil pad on an ESP32 touch pin. Muscle effort presses the skin closer to the pad, which
changes the touch reading. We compare against a relaxed baseline:

- Uncalibrated: "trying" = both sites changed by at least `threshold` (fraction of baseline).
- Range-calibrated (relax, then squeeze as hard as you can): each site's change is scaled to that
  person's own full-effort change, so the same difficulty level works for any wearer and pad fit.
Sites: NG_INTENT_SITES=temple uses the headband pad alone (default: both pads must agree).
A reading of 0 on a used site means "no signal" (the hand board sends 0 when the wireless headband
goes silent), which counts as not trying, so a dropped link opens the hand instead of freezing it.
"""
import os
from dataclasses import dataclass

import numpy as np

from .protocol import SensorFrame

CAL_FRACTIONS = [0.2, 0.3, 0.4, 0.5, 0.6]  # share of personal range needed to count as trying, per level
MIN_RANGE = 0.02                           # a site that changes less than 2% at full effort isn't usable
SITE_NAMES = ("temple", "forearm")


def sites_from_env() -> tuple[str, ...]:
    raw = os.environ.get("NG_INTENT_SITES", "temple,forearm")
    sites = tuple(s for s in (x.strip().lower() for x in raw.split(",")) if s in SITE_NAMES)
    return sites or SITE_NAMES


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


def calibrate_from(relaxed: list[tuple[int, int]], effort: list[tuple[int, int]],
                   sites: tuple[str, ...] | None = None
                   ) -> tuple[tuple[float, float], tuple[float, float]]:
    """Baseline from the relaxed phase, full-effort change (90th percentile) from the squeeze phase."""
    sites = sites or sites_from_env()
    r, e = np.asarray(relaxed, float), np.asarray(effort, float)
    base = (float(np.median(r[:, 0])), float(np.median(r[:, 1])))
    full = tuple(float(np.percentile(np.abs(base[i] - e[:, i]) / base[i], 90)) if base[i] else 0.0
                 for i in (0, 1))
    weak = [name for name, f in zip(SITE_NAMES, full) if name in sites and f < MIN_RANGE]
    if weak:
        raise ValueError(f"no clear change on the {' and '.join(weak)} pad: check contact and squeeze harder")
    return base, full


class IntentDetector:
    def __init__(self, threshold: float = 0.14, calib_frames: int = 100, sites: tuple[str, ...] | None = None):
        self.sites = tuple(sites) if sites else sites_from_env()
        self._idx = [SITE_NAMES.index(s) for s in self.sites]
        self.threshold = threshold
        self.fraction = CAL_FRACTIONS[2]
        self.calib_frames = calib_frames
        self.full: tuple[float, float] | None = None
        self._calib: list[tuple[int, int]] = []
        self._baseline: tuple[float, float] | None = None

    @property
    def range_calibrated(self) -> bool:
        return self.full is not None

    def set_calibration(self, baseline: tuple[float, float], full: tuple[float, float]) -> None:
        self._baseline, self.full = baseline, full

    def update(self, f: SensorFrame) -> IntentState:
        raw = (f.temple, f.forearm)
        if any(raw[i] <= 0 for i in self._idx):  # no signal (wireless headband silent)
            return IntentState(self._baseline is not None, False, 0.0, 0.0, 0.0)
        if self._baseline is None:
            self._calib.append(raw)
            if len(self._calib) >= self.calib_frames:
                arr = np.array(self._calib, dtype=float)
                self._baseline = (float(np.median(arr[:, 0])), float(np.median(arr[:, 1])))
            return IntentState(False, False, 0.0, 0.0, 0.0)
        t = _drop(self._baseline[0], f.temple)
        fa = _drop(self._baseline[1], f.forearm)
        drops = (t, fa)
        if self.full is not None:
            n = min(drops[i] / self.full[i] for i in self._idx)
            fr = self.fraction
            active = n >= fr
            # 0.5 exactly at the threshold, 1.0 at this person's full effort
            strength = 0.5 * n / fr if n < fr else 0.5 + 0.5 * min(1.0, (n - fr) / (1 - fr))
        else:
            active = all(drops[i] >= self.threshold for i in self._idx)
            strength = min(drops[i] for i in self._idx) / (2 * self.threshold)
        return IntentState(True, active, round(max(0.0, min(1.0, strength)), 3), round(t, 3), round(fa, 3))
