"""Intent gate: the robot moves only when intent + clean posture + a target are all present."""
from dataclasses import dataclass

from .intent import IntentState
from .protocol import FINGERS, SERVO_MAX
from .vision import VisionResult

THRESHOLDS = [0.08, 0.11, 0.14, 0.17, 0.20]  # intent threshold per difficulty level 1-5


@dataclass
class GateOutput:
    open: bool
    target_set: bool
    angles: tuple[int, ...]  # one per finger, in FINGERS order
    led: str
    buzzer_hz: int


class Gate:
    def __init__(self):
        self.angles: tuple[int, ...] = (0,) * len(FINGERS)

    def step(self, intent: IntentState, vision: VisionResult) -> GateOutput:
        curls = vision.curls
        target_set = curls is not None  # an open healthy hand is a valid target: it releases the grip
        compensating = bool(vision.compensation)
        is_open = intent.active and not compensating and target_set
        if is_open:
            self.angles = tuple(round(curls[k] * SERVO_MAX) for k in FINGERS)
        led = "R" if compensating else "G" if is_open else "O"
        buzzer = 400 + int(800 * intent.strength) if intent.active else 0
        return GateOutput(is_open, target_set, self.angles, led, buzzer)
