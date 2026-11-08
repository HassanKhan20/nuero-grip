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
# After calibration (the capacitive pad is noisy: pressure, head movement, a hand on the power bank all move it):
ARTIFACT_RATIO = 2.5    # a change > 2.5x this person's full clench isn't a clench: the pad moved / contact changed
ARTIFACT_REZERO = 100   # ~2 s of continuous artifact = new resting level (headband re-seated): re-zero to it
DEBOUNCE_FRAMES = 4     # ~80 ms over the threshold before the hand moves (ignores one-frame blips)
DRIFT_ALPHA = 0.004     # while clearly relaxed, the baseline follows slow drift (~5 s time constant at 50 Hz)


class SiteRange(tuple):
    """Full-effort change per site (temple, forearm), plus which way each reading moves on effort:
    +1 = falls (classic ESP32 touch), -1 = rises (ESP32-S3 touch). Learned during calibration."""

    def __new__(cls, values, directions=(1, 1)):
        obj = super().__new__(cls, values)
        obj.directions = tuple(directions)
        return obj


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
    artifact: bool = False  # reading jumped far beyond a clench (pad moved), so it was ignored


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
    directions = tuple(1 if float(np.median(base[i] - e[:, i])) >= 0 else -1 for i in (0, 1))
    full = SiteRange(full, directions)
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
        self._baseline, self.full = tuple(baseline), full
        self._dir = getattr(full, "directions", (1, 1))
        self._above = self._artifact_frames = 0

    def rezero(self) -> None:
        """Take a fresh relaxed baseline from the next frames (e.g. after putting the headband on).
        Applied on the next update() so it is safe to call from another thread."""
        self._rezero_pending = True

    def update(self, f: SensorFrame) -> IntentState:
        if getattr(self, "_rezero_pending", False):
            self._rezero_pending = False
            self._baseline, self.full, self._calib = None, None, []
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
            return self._calibrated_update(raw, t, fa)
        else:
            active = all(drops[i] >= self.threshold for i in self._idx)
            strength = min(drops[i] for i in self._idx) / (2 * self.threshold)
        return IntentState(True, active, round(max(0.0, min(1.0, strength)), 3), round(t, 3), round(fa, 3))

    def _calibrated_update(self, raw: tuple[int, int], t: float, fa: float) -> IntentState:
        base, fr = self._baseline, self.fraction
        dirs = getattr(self, "_dir", (1, 1))
        # signed change: only movement in this person's effort direction counts
        signed = [dirs[i] * (base[i] - raw[i]) / base[i] if base[i] else 0.0 for i in (0, 1)]
        if any(abs(signed[i]) > ARTIFACT_RATIO * self.full[i] for i in self._idx):
            self._above = 0
            self._artifact_frames = getattr(self, "_artifact_frames", 0) + 1
            if self._artifact_frames >= ARTIFACT_REZERO:  # it stayed there: that's the new resting level
                self._baseline = tuple(float(raw[i]) if i in self._idx else base[i] for i in (0, 1))
                self._artifact_frames = 0
            return IntentState(True, False, 0.0, round(t, 3), round(fa, 3), artifact=True)
        self._artifact_frames = 0
        n = min(max(0.0, signed[i]) / self.full[i] for i in self._idx)
        self._above = getattr(self, "_above", 0) + 1 if n >= fr else 0
        active = self._above >= DEBOUNCE_FRAMES
        # 0.5 exactly at the threshold, 1.0 at this person's full effort
        strength = 0.5 * n / fr if n < fr else 0.5 + 0.5 * min(1.0, (n - fr) / (1 - fr))
        if n < fr * 0.5:  # clearly relaxed: let the baseline follow slow drift
            self._baseline = tuple(base[i] + DRIFT_ALPHA * (raw[i] - base[i]) if i in self._idx else base[i]
                                   for i in (0, 1))
        return IntentState(True, active, round(max(0.0, min(1.0, strength)), 3), round(t, 3), round(fa, 3))
