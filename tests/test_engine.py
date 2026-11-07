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
    for key in ["angles", "gate_open", "intent_strength", "curls", "led", "mode", "activation_rate", "events"]:
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


def test_cue_latency_sends_cue():
    e = _engine()
    e.cue_latency()
    assert "B,1500,150\n" in e.source.sent


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
    e.metrics._prev_comp = set()
    t0 = time.monotonic()
    for _ in range(600):  # mock vision emits a shoulder_hike event at ~10 s
        e.step()
    assert time.monotonic() - t0 < 0.9
    assert any(ev["type"] == "shoulder_hike" for ev in e.new_events)


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
