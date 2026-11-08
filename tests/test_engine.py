from neurogrip.engine import Engine
from neurogrip.sources import MockSource
from neurogrip.store import MemoryStore
from neurogrip.vision import MockVision


def _engine(**kw):
    return Engine(MockSource(**kw), MockVision(), MemoryStore())


def test_engine_mock_runs():
    e = _engine(tremor_hz=5)
    for _ in range(600):
        e.step()
    s = e.state()
    assert s["reps"] >= 1
    assert any(c.startswith("A,") for c in e.source.sent)
    assert abs(s["tremor_hz"] - 5) < 0.6
    for key in ["angles", "gate_open", "intent_strength", "curls", "led", "mode", "activation_rate", "events", "session_s"]:
        assert key in s


def test_led_only_sent_on_change():
    e = _engine()
    for _ in range(50):
        e.step()
    led_cmds = [c for c in e.source.sent if c.startswith("L,")]
    assert len(led_cmds) < 10


def test_set_difficulty_clamps():
    e = _engine()
    assert e.set_difficulty(9) == 5
    assert e.intent.threshold == 0.20
    assert e.set_difficulty(0) == 1
    assert e.state()["difficulty"] == 1


def test_cue_fires_after_delay():
    e = _engine()
    got = []
    e.listeners.append(got.append)
    for _ in range(10):
        e.step()
    e.cue_latency()
    assert e.state()["cue_pending"]
    for _ in range(45):  # < 1 s: too early for the cue
        e.step()
    assert not any(ev["type"] == "cue" for ev in got)
    for _ in range(120):
        e.step()
    assert any(ev["type"] == "cue" for ev in got)
    assert "B,1500,150\n" in e.source.sent


def test_cue_twice_single_trial():
    e = _engine()
    got = []
    e.listeners.append(got.append)
    e.step()
    e.cue_latency()
    e.cue_latency()
    for _ in range(200):
        e.step()
    assert sum(ev["type"] == "cue" for ev in got) == 1


def test_end_session_persists():
    e = _engine()
    for _ in range(200):
        e.step()
    e.end_session()
    hist = e.store.history("demo")
    assert len(hist) == 1 and "reps" in hist[0]
    assert e.state()["reps"] == 0


def test_store_history_newest_first():
    s = MemoryStore()
    s.save_session({"patient_id": "p", "n": 1})
    s.save_session({"patient_id": "p", "n": 2})
    s.save_session({"patient_id": "q", "n": 3})
    assert [d["n"] for d in s.history("p")] == [2, 1]


class SlowFailingStore(MemoryStore):
    def log_event(self, doc):
        import time
        time.sleep(1.0)
        raise RuntimeError("atlas unreachable")


def test_slow_failing_store_does_not_stall_engine():
    import time
    e = Engine(MockSource(), MockVision(), SlowFailingStore())
    e.step()
    e.cue_latency()
    t0 = time.monotonic()
    for _ in range(300):  # the cue fires within 1-3 s and is persisted
        e.step()
    assert time.monotonic() - t0 < 0.9
    assert any(ev["type"] == "cue" for ev in e.new_events)


def test_sensors_ok_reflects_frame_age():
    import time
    e = _engine()
    e.step()
    assert e.state()["sensors_ok"] is True
    e._last_frame_at = time.monotonic() - 2
    assert e.state()["sensors_ok"] is False


def test_make_store_falls_back_when_mongo_unreachable(monkeypatch):
    from neurogrip import store

    def boom(uri):
        raise RuntimeError("dns failure")
    monkeypatch.setenv("MONGODB_URI", "mongodb+srv://nope.example/")
    monkeypatch.setattr(store, "MongoStore", boom)
    assert isinstance(store.make_store(), MemoryStore)


def test_serial_source_reconnects(monkeypatch):
    import serial
    from neurogrip import sources

    opened = []

    class FakeSerial:
        def __init__(self, port, baud, timeout=1):
            opened.append(port)
            self.n = len(opened)

        def readline(self):
            if self.n == 1:
                raise serial.SerialException("device disconnected")
            return b"S,5,400,400,0,0,1000\n"

        def close(self):
            pass

        def write(self, b):
            pass

    monkeypatch.setattr(serial, "Serial", FakeSerial)
    monkeypatch.setattr(sources, "RECONNECT_DELAY_S", 0)
    src = sources.SerialSource("COM9")
    assert src.read().ms == 5 and len(opened) == 2


def test_cv_tremor_from_mock_vision():
    e = Engine(MockSource(), MockVision(tremor_hz=5), MemoryStore(), kind="camera")
    for _ in range(400):
        e.step()
    s = e.state()
    assert abs(s["cv_tremor_hz"] - 5) < 0.6 and s["tremor_hz"] == s["cv_tremor_hz"]
    assert s["source_kind"] == "camera" and s["tremor_amp"] > 0.002


def test_tapping_test_completes():
    e = Engine(MockSource(), MockVision(), MemoryStore(), kind="camera")
    got = []
    e.listeners.append(got.append)
    e.step()
    e.start_tapping_test(3.0)
    assert e.state()["tapping_active"]
    for _ in range(200):
        e.step()
    s = e.state()
    assert not s["tapping_active"] and s["tapping"]["taps"] >= 3
    assert any(ev["type"] == "tapping" for ev in got)


def test_listener_exception_does_not_break_step():
    e = _engine()

    def bad(ev):
        raise RuntimeError("socket gone")
    e.listeners.append(bad)
    e.step()
    e.cue_latency()
    for _ in range(300):
        e.step()
    assert len(e.new_events) > 0


def test_set_control_validates_and_reports():
    import pytest
    e = _engine()
    e.set_control("intent", "wave")
    s = e.state()
    assert s["control_mode"] == "intent" and s["grip"] == "wave"
    with pytest.raises(ValueError):
        e.set_control("telepathy")
    with pytest.raises(ValueError):
        e.set_control("intent", "jazz-hands")


def test_intent_only_moves_hand_without_vision():
    from neurogrip.vision import VisionResult

    class NoVision(MockVision):
        def latest(self, t_ms=None):
            return VisionResult(None)
    e = Engine(MockSource(), NoVision(), MemoryStore())
    e.set_control("intent", "fist")
    for _ in range(400):
        e.step()
    assert max(max(a) for a in [e.state()["angles"]]) >= 0  # state ok
    closes = [c for c in e.source.sent if c.startswith("A,") and c != "A,0,0,0,0,0\n"]
    assert closes, "robot never moved with intent only"


def _cal_engine():
    from neurogrip.sources import IntentControl
    ctl = IntentControl()
    e = Engine(MockSource(control=ctl), MockVision(), MemoryStore(), kind="camera")
    for _ in range(120):
        e.step()
    return e, ctl


def test_calibration_flow():
    e, ctl = _cal_engine()
    got = []
    e.listeners.append(got.append)
    e.start_calibration()
    assert e.state()["calibration_phase"] == "relax"
    for _ in range(101):
        e.step()
    assert e.state()["calibration_phase"] == "squeeze"
    ctl.held = True
    for _ in range(151 + 4):  # +4: intent must be held ~80 ms (debounce) before it counts
        e.step()
    s = e.state()
    assert s["calibration_phase"] is None and s["range_calibrated"]
    assert any(ev["type"] == "calibrated" for ev in got)
    assert s["intent_active"] and s["intent_strength"] > 0.9


def test_calibration_fails_without_squeeze():
    e, _ = _cal_engine()
    got = []
    e.listeners.append(got.append)
    e.start_calibration()
    for _ in range(260):
        e.step()
    assert any(ev["type"] == "calibration_failed" for ev in got)
    assert not e.state()["range_calibrated"]


def test_state_shows_raw_touch_readings():
    e = _engine()
    e.step()
    t = e.state()["touch"]
    assert set(t) == {"temple", "forearm", "temple_drop", "forearm_drop"} and t["temple"] > 0


def test_hardware_defaults_to_intent_control():
    from neurogrip.engine import default_control
    assert default_control("hardware") == "intent"
    assert default_control("camera") == "mirror"


def test_state_has_no_posture_keys():
    e = _engine()
    e.step()
    s = e.state()
    assert "compensation" not in s and "compensation_count" not in s
