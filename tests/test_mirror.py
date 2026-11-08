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


def test_calibration_accepts_small_clean_signal():
    """A 2% focus bump on a quiet pad (0.2% jitter) is usable: the bar is relative to the noise."""
    import pytest
    from neurogrip.intent import calibrate_from
    relaxed = [(1093 + (i % 3) - 1, 1900) for i in range(100)]   # ~0.1% jitter
    base, full = calibrate_from(relaxed, [(1071, 1900)] * 150, sites=("temple",))  # 2% drop
    assert abs(full[0] - 0.02) < 0.002
    noisy = [(1093 + (30 if i % 2 else -30), 1900) for i in range(100)]  # ~2.7% jitter
    with pytest.raises(ValueError):
        calibrate_from(noisy, [(1071, 1900)] * 150, sites=("temple",))


def test_trigger_stays_above_relaxed_jitter():
    """Lowest level wants 20% of full focus; on a small signal that would sit in the noise, so it's raised."""
    from neurogrip.intent import IntentDetector, SiteRange
    d = IntentDetector(calib_frames=1, sites=("temple",))
    d.fraction = 0.2
    d.set_calibration((1000.0, 1000.0), SiteRange((0.02, 0.02), (1, 1), (0.003, 0.0)))  # trigger -> 0.375 of full
    states = [d.update(Frame(i, 995, 1000, 0, 0, 1000)) for i in range(10)]  # 0.5% wobble = 25% of full
    assert not any(s.active for s in states)
    states = [d.update(Frame(20 + i, 990, 1000, 0, 0, 1000)) for i in range(10)]  # 1% = half of full focus
    assert states[-1].active


def test_zero_keeps_calibrated_range():
    from neurogrip.intent import IntentDetector, SiteRange
    d = IntentDetector(calib_frames=2, sites=("temple",))
    d.set_calibration((1000.0, 1000.0), SiteRange((0.02, 0.02)))
    d.rezero()
    for i in range(3):
        d.update(Frame(i, 1100, 1000, 0, 0, 1000))  # new resting level after re-seating the headband
    assert d.range_calibrated
    states = [d.update(Frame(10 + i, 1078, 1000, 0, 0, 1000)) for i in range(6)]  # 2% focus from the new zero
    assert states[-1].active and states[-1].strength == 1.0


def test_calibration_survives_restart(tmp_path):
    from neurogrip.engine import Engine
    from neurogrip.intent import SiteRange
    from neurogrip.sources import MockSource
    from neurogrip.store import MemoryStore
    from neurogrip.vision import MockVision
    path = str(tmp_path / "cal.json")
    a = Engine(MockSource(), MockVision(), MemoryStore(), kind="hardware")
    a.load_range(path)
    a._save_range(SiteRange((0.022, 0.5), (1, -1), (0.002, 0.0)))
    b = Engine(MockSource(), MockVision(), MemoryStore(), kind="hardware")
    assert b.load_range(path) and b.intent.range_calibrated
    assert b.intent.full.directions == (1, -1) and b.intent.full.noise == (0.002, 0.0)


def test_normal_focus_closes_fist_fully():
    g = Gate()
    g.control, g.grip = "intent", "fist"
    for _ in range(60):
        out = g.step(IntentState(True, True, 0.75, 0.2, 0.2), VisionResult(None))
    assert out.angles == (128, 160, 160, 160, 160)


def test_engine_smooths_pad_jitter_and_passes_link_loss():
    from neurogrip.engine import Engine
    from neurogrip.sources import MockSource
    from neurogrip.store import MemoryStore
    from neurogrip.vision import MockVision
    e = Engine(MockSource(), MockVision(), MemoryStore(), kind="hardware")
    e.smooth_frames = 4
    from collections import deque
    e._pad_hist = deque(maxlen=4)
    vals = [e._smooth(Frame(i, v, 1900, 0, 0, 1000)).temple for i, v in enumerate([1176, 1180, 1176, 1180])]
    assert vals[-1] == 1178.0
    assert e._smooth(Frame(9, 0, 0, 0, 0, 1000)).temple == 0
    assert e._smooth(Frame(10, 1190, 1900, 0, 0, 1000)).temple == 1190.0  # window restarted after the dropout


def test_held_opposite_change_does_not_fire_on_release():
    """Reading moves the 'wrong' way for 3 s, then returns: the baseline must not sink far enough to trigger."""
    from neurogrip.intent import IntentDetector, SiteRange
    d = IntentDetector(calib_frames=1, sites=("temple",))
    d.fraction = 0.2  # level 1
    d.set_calibration((1000.0, 1000.0), SiteRange((0.01, 0.01), (-1, -1)))  # effort = reading rises 1%
    for i in range(150):
        d.update(Frame(i, 990, 1000, 0, 0, 1000))  # held 1% fall (opposite) for 3 s
    states = [d.update(Frame(200 + i, 1000, 1000, 0, 0, 1000)) for i in range(10)]  # let go
    assert not any(s.active for s in states)
