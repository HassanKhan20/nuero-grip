"""Intent gate: the robot moves only when the patient is actively trying.

Two control modes:
- "mirror": each servo copies the matching finger of the healthy hand (camera). Needs a visible hand.
- "intent": no camera needed. Intent strength alone closes the hand in a chosen grip shape;
  relaxing opens it. Motion is rate-limited so it looks and feels smooth.
"""
from dataclasses import dataclass

from .intent import IntentState
from .protocol import FINGERS, SERVO_MAX
from .vision import VisionResult

THRESHOLDS = [0.08, 0.11, 0.14, 0.17, 0.20]  # intent threshold per difficulty level 1-5
CONTROL_MODES = ["mirror", "intent"]
GRIPS = ["fist", "pinch", "point", "wave"]
MAX_STEP_DEG = 6  # per 20 ms frame in intent mode: about 0.55 s from open to closed
FULL_CLOSE_STRENGTH = 0.75  # intent mode: fully closed at 75% focus (0.5 = trigger), not only at max effort
MIRROR_DEADBAND_DEG = 3  # mirror mode ignores tiny camera jitter so the servos don't buzz


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def grip_targets(grip: str, c: float) -> tuple[float, ...]:
    """Per-finger closure (0-1, FINGERS order) for overall closure c."""
    if grip == "pinch":
        return (0.75 * c, 0.85 * c, 0.0, 0.0, 0.0)
    if grip == "point":
        return (0.7 * c, 0.0, c, c, c)
    if grip == "wave":  # fingers close one after another, thumb first
        return tuple(_clamp01((c - 0.12 * i) / 0.52) for i in range(5))
    return (0.8 * c, c, c, c, c)  # fist


@dataclass
class GateOutput:
    open: bool
    target_set: bool
    angles: tuple[int, ...]  # one per finger, in FINGERS order
    led: str
    buzzer_hz: int
    drive: float | None = None  # intent mode: how closed the robot is driven (0-1)


class Gate:
    def __init__(self):
        self.angles: tuple[int, ...] = (0,) * len(FINGERS)
        self.control = "mirror"
        self.grip = "fist"

    def step(self, intent: IntentState, vision: VisionResult) -> GateOutput:
        buzzer = 400 + int(800 * intent.strength) if intent.active else 0
        if self.control == "intent":
            return self._step_intent(intent, buzzer)

        curls = vision.curls
        target_set = curls is not None  # an open healthy hand is a valid target: it releases the grip
        is_open = intent.active and target_set
        if intent.link_lost:  # headband gone: never leave the hand clamped on a held pose
            self.angles = (0,) * len(FINGERS)
        elif is_open:
            target = tuple(round(curls[k] * SERVO_MAX) for k in FINGERS)
            self.angles = tuple(t if abs(t - a) > MIRROR_DEADBAND_DEG or t in (0, SERVO_MAX) else a
                                for a, t in zip(self.angles, target))
        return GateOutput(is_open, target_set, self.angles, "G" if is_open else "O", buzzer)

    def _step_intent(self, intent: IntentState, buzzer: int) -> GateOutput:
        # closure starts at the trigger (strength 0.5) and is full at FULL_CLOSE_STRENGTH
        closure = _clamp01((intent.strength - 0.5) / (FULL_CLOSE_STRENGTH - 0.5)) if intent.active else 0.0
        target = tuple(round(t * SERVO_MAX) for t in grip_targets(self.grip, closure))
        self.angles = tuple(a + max(-MAX_STEP_DEG, min(MAX_STEP_DEG, t - a)) for a, t in zip(self.angles, target))
        drive = max(self.angles) / SERVO_MAX
        return GateOutput(intent.active, True, self.angles, "G" if intent.active else "O", buzzer, drive=round(drive, 3))
