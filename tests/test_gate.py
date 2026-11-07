from neurogrip.gate import THRESHOLDS, Gate
from neurogrip.intent import IntentState
from neurogrip.vision import VisionResult

ACTIVE = IntentState(calibrated=True, active=True, strength=0.5, temple_drop=0.2, forearm_drop=0.2)
IDLE = IntentState(calibrated=True, active=False, strength=0.0, temple_drop=0.0, forearm_drop=0.0)


def test_thresholds():
    assert THRESHOLDS == [0.08, 0.11, 0.14, 0.17, 0.20]


def test_gate_closed_without_hand():
    out = Gate().step(ACTIVE, VisionResult(None, []))
    assert not out.open and not out.target_set and out.angles == (0, 0, 0)


def test_gate_open_proportional():
    out = Gate().step(ACTIVE, VisionResult({"thumb": 0.5, "index": 1.0, "rest": 0.25}, []))
    assert out.open and out.angles == (80, 160, 40) and out.led == "G"
    assert out.buzzer_hz == 800


def test_gate_closed_without_intent_holds_angles():
    g = Gate()
    g.step(ACTIVE, VisionResult({"thumb": 0.5, "index": 0.5, "rest": 0.5}, []))
    out = g.step(IDLE, VisionResult({"thumb": 1, "index": 1, "rest": 1}, []))
    assert not out.open and out.angles == (80, 80, 80) and out.led == "O" and out.buzzer_hz == 0


def test_gate_blocked_by_compensation_holds_angles():
    g = Gate()
    g.step(ACTIVE, VisionResult({"thumb": 0.5, "index": 0.5, "rest": 0.5}, []))
    out = g.step(ACTIVE, VisionResult({"thumb": 1, "index": 1, "rest": 1}, ["trunk_lean"]))
    assert not out.open and out.angles == (80, 80, 80) and out.led == "R"


def test_open_hand_releases_servos():
    g = Gate()
    g.step(ACTIVE, VisionResult({"thumb": 1, "index": 1, "rest": 1}, []))
    out = g.step(ACTIVE, VisionResult({"thumb": 0, "index": 0, "rest": 0}, []))
    assert out.open and out.target_set and out.angles == (0, 0, 0)
