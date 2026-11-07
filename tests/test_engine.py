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
