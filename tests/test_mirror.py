"""Camera mirroring on the robot hand: smoothing, jitter deadband and headband-loss safety."""
from neurogrip.engine import make_engine
from neurogrip.gate import MIRROR_DEADBAND_DEG, Gate
from neurogrip.intent import IntentDetector, IntentState
from neurogrip.protocol import SensorFrame as Frame
from neurogrip.vision import VisionResult, smooth_curls

ACTIVE = IntentState(True, True, 0.8, 0.2, 0.2)
LOST = IntentState(True, False, 0.0, 0.0, 0.0, link_lost=True)


def _all(v):
    return dict.fromkeys(("thumb", "index", "middle", "ring", "pinky"), v)


def test_mirror_opens_hand_when_headband_link_lost():
    g = Gate()
    g.step(ACTIVE, VisionResult(_all(1)))
    out = g.step(LOST, VisionResult(_all(1)))
    assert out.angles == (0,) * 5 and not out.open


def test_mirror_ignores_tiny_camera_jitter():
    g = Gate()
    g.step(ACTIVE, VisionResult(_all(0.5)))  # 80 deg
    jitter = (MIRROR_DEADBAND_DEG - 1) / 160
    assert g.step(ACTIVE, VisionResult(_all(0.5 + jitter))).angles == (80,) * 5
    assert g.step(ACTIVE, VisionResult(_all(0.6))).angles == (96,) * 5


def test_smooth_curls_blends_but_not_on_first_frame():
    assert smooth_curls(None, {"index": 1.0}) == {"index": 1.0}
    assert smooth_curls({"index": 0.0}, {"index": 1.0}, alpha=0.5) == {"index": 0.5}


def test_silent_headband_reports_link_lost():
    det = IntentDetector(calib_frames=2, sites=("temple",))
    assert det.update(Frame(0, 0, 0, 0, 0, 1000)).link_lost


def test_ng_level_sets_starting_difficulty(monkeypatch):
    monkeypatch.setenv("NG_MOCK", "1")
    monkeypatch.setenv("NG_LEVEL", "1")
    assert make_engine().metrics.difficulty == 1
