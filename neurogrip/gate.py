"""Intent gate: the robot moves only when intent + clean posture + a target are all present."""
from dataclasses import dataclass

from .intent import IntentState
from .protocol import SERVO_MAX
from .vision import VisionResult

THRESHOLDS = [0.08, 0.11, 0.14, 0.17, 0.20]  # intent threshold per difficulty level 1-5
MIN_TARGET_CURL = 0.1


@dataclass
class GateOutput:
    open: bool
    target_set: bool
    angles: tuple[int, int, int]
    led: str
    buzzer_hz: int


class Gate:
    def __init__(self):
        self.angles: tuple[int, int, int] = (0, 0, 0)

    def step(self, intent: IntentState, vision: VisionResult) -> GateOutput:
        curls = vision.curls
        target_set = curls is not None and max(curls.values()) >= MIN_TARGET_CURL
        compensating = bool(vision.compensation)
        is_open = intent.active and not compensating and target_set
        if is_open:
            self.angles = tuple(round(curls[k] * SERVO_MAX) for k in ("thumb", "index", "rest"))
        led = "R" if compensating else "G" if is_open else "O"
        buzzer = 400 + int(800 * intent.strength) if intent.active else 0
        return GateOutput(is_open, target_set, self.angles, led, buzzer)
