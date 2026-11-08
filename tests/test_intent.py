from neurogrip.intent import IntentDetector
from neurogrip.protocol import SensorFrame
from neurogrip.sources import MockSource


def test_intent_needs_calibration():
    d = IntentDetector(calib_frames=10)
    assert not d.update(SensorFrame(0, 400, 400, 0, 0, 1000)).calibrated


def test_intent_dual_site_required():
    d = IntentDetector(threshold=0.14, calib_frames=10)
    for i in range(10):
        d.update(SensorFrame(i, 400, 400, 0, 0, 1000))
    assert not d.update(SensorFrame(11, 300, 400, 0, 0, 1000)).active  # temple only
    s = d.update(SensorFrame(12, 300, 300, 0, 0, 1000))
    assert s.active and 0.5 < s.strength <= 1.0


def test_intent_works_when_touch_reading_rises():
    # ESP32-S3 touch values rise on contact instead of falling
    d = IntentDetector(threshold=0.14, calib_frames=10)
    for i in range(10):
        d.update(SensorFrame(i, 400, 400, 0, 0, 1000))
    assert d.update(SensorFrame(11, 520, 520, 0, 0, 1000)).active


def test_mock_source_produces_intent():
    src, d = MockSource(seed=1), IntentDetector()
    states = [d.update(src.read()) for _ in range(500)]
    assert any(s.active for s in states)
    assert not all(s.active for s in states[100:])


def test_mock_source_records_sent_commands():
    src = MockSource()
    src.send("L,G\n")
    assert src.sent == ["L,G\n"]


def test_intent_control_drives_mock_source():
    from neurogrip.sources import IntentControl
    ctl = IntentControl()
    src, d = MockSource(control=ctl), IntentDetector()
    assert not any(d.update(src.read()).active for _ in range(400))
    ctl.held = True
    assert any(d.update(src.read()).active for _ in range(50))
    ctl.held, ctl.auto = False, True
    states = [d.update(src.read()).active for _ in range(400)]
    assert any(states) and not all(states)


def test_realtime_clock():
    import time
    src = MockSource(realtime=True)
    a = src.read().ms
    time.sleep(0.05)
    assert src.read().ms - a >= 40


def test_hold_ramps_intent_up_gradually():
    from neurogrip.sources import IntentControl
    ctl = IntentControl()
    src, d = MockSource(control=ctl), IntentDetector()
    for _ in range(150):
        d.update(src.read())
    ctl.held = True
    strengths = [d.update(src.read()).strength for _ in range(80)]
    assert strengths[0] < 0.3          # not instant: the grip builds up
    assert strengths[10] < strengths[30] < strengths[-1]
    assert strengths[-1] == 1.0


def _calibrated_detector():
    from neurogrip.intent import IntentDetector
    d = IntentDetector(calib_frames=5)
    for i in range(5):
        d.update(SensorFrame(i, 70, 70, 0, 0, 1000))
    d.set_calibration((70.0, 70.0), (0.3, 0.3))  # this person's full squeeze = 30% change
    return d


def test_calibrated_range_scales_strength():
    d = _calibrated_detector()
    assert d.range_calibrated
    assert not d.update(SensorFrame(10, 62, 62, 0, 0, 1000)).active      # 38% of range < 40% (level 3)
    full = d.update(SensorFrame(11, 49, 49, 0, 0, 1000))                 # full squeeze
    assert full.active and full.strength == 1.0
    mid = d.update(SensorFrame(12, 55, 55, 0, 0, 1000))                  # ~71% of range
    assert mid.active and 0.7 < mid.strength < 0.8


def test_calibrate_from_relaxed_and_effort():
    from neurogrip.intent import calibrate_from
    base, full = calibrate_from([(70, 72)] * 50, [(49, 50)] * 50)
    assert base == (70.0, 72.0)
    assert abs(full[0] - 0.3) < 0.01 and abs(full[1] - 22 / 72) < 0.01


def test_calibrate_from_rejects_no_change():
    import pytest
    from neurogrip.intent import calibrate_from
    with pytest.raises(ValueError, match="forearm"):
        calibrate_from([(70, 70)] * 50, [(50, 70)] * 50)


def test_realtime_mock_accel_is_uniformly_sampled():
    # the engine loop may run fast or jittery; the simulated wristband must still look like a steady 50 Hz sensor
    import math
    import numpy as np
    from neurogrip.signals import tremor_frequency
    src = MockSource(tremor_hz=5, realtime=True)
    frames = [src.read() for _ in range(256)]  # read as fast as possible: wall time barely moves
    mag = np.array([math.sqrt(f.ax ** 2 + f.ay ** 2 + f.az ** 2) for f in frames])
    assert abs(tremor_frequency(mag) - 5) < 0.4


def _baseline(d, n=10, v=(400, 400)):
    for i in range(n):
        d.update(SensorFrame(i, v[0], v[1], 0, 0, 1000))


def test_temple_only_mode_ignores_forearm():
    d = IntentDetector(threshold=0.14, calib_frames=10, sites=("temple",))
    _baseline(d)
    assert d.update(SensorFrame(11, 300, 400, 0, 0, 1000)).active  # temple alone is enough


def test_sites_from_env(monkeypatch):
    monkeypatch.setenv("NG_INTENT_SITES", "temple")
    assert IntentDetector().sites == ("temple",)
    monkeypatch.delenv("NG_INTENT_SITES")
    assert IntentDetector().sites == ("temple", "forearm")


def test_lost_headband_link_reads_as_no_intent():
    d = IntentDetector(threshold=0.14, calib_frames=10, sites=("temple",))
    _baseline(d)
    s = d.update(SensorFrame(11, 0, 400, 0, 0, 1000))  # hand board sends 0 when the headband is silent
    assert s.calibrated and not s.active and s.strength == 0.0


def test_link_lost_frames_skipped_during_baseline():
    d = IntentDetector(calib_frames=10, sites=("temple",))
    for i in range(10):
        d.update(SensorFrame(i, 0, 400, 0, 0, 1000))
    assert not d.update(SensorFrame(10, 0, 400, 0, 0, 1000)).calibrated


def test_calibration_temple_only_does_not_require_forearm():
    import pytest
    from neurogrip.intent import calibrate_from
    relaxed = [(400, 400)] * 20
    effort = [(340, 400)] * 20  # temple moves 15%, forearm flat
    base, full = calibrate_from(relaxed, effort, sites=("temple",))
    assert round(full[0], 2) == 0.15
    with pytest.raises(ValueError):
        calibrate_from(relaxed, effort, sites=("temple", "forearm"))
    d = IntentDetector(sites=("temple",))
    d.set_calibration(base, full)
    assert d.update(SensorFrame(0, 340, 400, 0, 0, 1000)).active


def test_rezero_takes_new_relaxed_baseline():
    d = IntentDetector(threshold=0.14, calib_frames=10, sites=("temple",))
    _baseline(d, v=(1300, 400))
    assert d.update(SensorFrame(20, 650, 400, 0, 0, 1000)).active  # headband put on: looks like a huge clench
    d.set_calibration((1300.0, 400.0), (0.5, 0.5))
    d.rezero()
    for i in range(10):
        s = d.update(SensorFrame(30 + i, 650, 400, 0, 0, 1000))
        assert not s.active  # re-reading the relaxed level
    s = d.update(SensorFrame(50, 650, 400, 0, 0, 1000))
    assert s.calibrated and not s.active and s.strength == 0.0
    assert not d.range_calibrated  # old full-effort range no longer applies
    assert d.update(SensorFrame(51, 540, 400, 0, 0, 1000)).active  # a real clench from the new zero
