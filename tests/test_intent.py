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
    assert d.update(src.read()).active
    ctl.held, ctl.auto = False, True
    states = [d.update(src.read()).active for _ in range(400)]
    assert any(states) and not all(states)


def test_realtime_clock():
    import time
    src = MockSource(realtime=True)
    a = src.read().ms
    time.sleep(0.05)
    assert src.read().ms - a >= 40
