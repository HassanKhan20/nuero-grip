from neurogrip.gate import GRIPS, MAX_STEP_DEG, THRESHOLDS, Gate, grip_targets
from neurogrip.intent import IntentState
from neurogrip.vision import VisionResult


def _all(v):
    return dict.fromkeys(("thumb", "index", "middle", "ring", "pinky"), v)

ACTIVE = IntentState(calibrated=True, active=True, strength=0.5, temple_drop=0.2, forearm_drop=0.2)
IDLE = IntentState(calibrated=True, active=False, strength=0.0, temple_drop=0.0, forearm_drop=0.0)


def test_thresholds():
    assert THRESHOLDS == [0.08, 0.11, 0.14, 0.17, 0.20]


def test_gate_closed_without_hand():
    out = Gate().step(ACTIVE, VisionResult(None))
    assert not out.open and not out.target_set and out.angles == (0, 0, 0, 0, 0)


def test_gate_open_proportional():
    out = Gate().step(ACTIVE, VisionResult({"thumb": 0.5, "index": 1.0, "middle": 0.25, "ring": 0.5, "pinky": 0.0}))
    assert out.open and out.angles == (80, 160, 40, 80, 0) and out.led == "G"
    assert out.buzzer_hz == 800


def test_gate_closed_without_intent_holds_angles():
    g = Gate()
    g.step(ACTIVE, VisionResult(_all(0.5)))
    out = g.step(IDLE, VisionResult(_all(1)))
    assert not out.open and out.angles == (80,) * 5 and out.led == "O" and out.buzzer_hz == 0


def test_open_hand_releases_servos():
    g = Gate()
    g.step(ACTIVE, VisionResult(_all(1)))
    out = g.step(ACTIVE, VisionResult(_all(0)))
    assert out.open and out.target_set and out.angles == (0, 0, 0, 0, 0)


STRONG = IntentState(True, True, 1.0, 0.4, 0.4)


def _intent_gate(grip="fist"):
    g = Gate()
    g.control, g.grip = "intent", grip
    return g


def test_intent_mode_needs_no_hand_and_ramps_smoothly():
    g = _intent_gate()
    first = g.step(STRONG, VisionResult(None))
    assert first.open and first.target_set
    assert 0 < max(first.angles) <= MAX_STEP_DEG
    for _ in range(60):
        out = g.step(STRONG, VisionResult(None))
    assert out.angles == (128, 160, 160, 160, 160) and out.drive == 1.0


def test_intent_mode_relaxing_opens_hand():
    g = _intent_gate()
    for _ in range(60):
        g.step(STRONG, VisionResult(None))
    for _ in range(60):
        out = g.step(IDLE, VisionResult(None))
    assert out.angles == (0, 0, 0, 0, 0) and not out.open


def test_intent_mode_pinch_pattern():
    g = _intent_gate("pinch")
    for _ in range(60):
        out = g.step(STRONG, VisionResult(None))
    assert out.angles[0] > 0 and out.angles[1] > 0 and out.angles[2:] == (0, 0, 0)


def test_wave_grip_closes_thumb_before_pinky():
    half = IntentState(True, True, 0.625, 0.2, 0.2)  # closure 0.5
    g = _intent_gate("wave")
    for _ in range(60):
        out = g.step(half, VisionResult(None))
    assert out.angles[0] > out.angles[2] > out.angles[4]


def test_grip_targets_known_patterns():
    for name in GRIPS:
        assert len(grip_targets(name, 1.0)) == 5
        assert grip_targets(name, 0.0) == (0, 0, 0, 0, 0)


def test_gate_has_no_posture_block():
    out = Gate().step(ACTIVE, VisionResult(_all(1)))
    assert out.open and out.led == "G"
