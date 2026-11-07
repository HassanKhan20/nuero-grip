from neurogrip.gate import GateOutput
from neurogrip.intent import IntentState
from neurogrip.metrics import SessionMetrics
from neurogrip.vision import VisionResult

ACTIVE = IntentState(True, True, 0.5, 0.2, 0.2)
IDLE = IntentState(True, False, 0.0, 0.0, 0.0)


def _v(curl, comp=()):
    return VisionResult({"thumb": curl, "index": curl, "rest": curl}, list(comp))


def _g(open_, target=True):
    return GateOutput(open=open_, target_set=target, angles=(0, 0, 0), led="O", buzzer_hz=0)


def test_rep_counted_with_hysteresis():
    m = SessionMetrics()
    for i, c in enumerate([0.0, 0.7, 0.2]):
        m.update(i * 20, ACTIVE, _v(c), _g(True))
    assert m.snapshot()["reps"] == 1
    for i, c in enumerate([0.7, 0.5, 0.7]):
        m.update(100 + i * 20, ACTIVE, _v(c), _g(True))
    assert m.snapshot()["reps"] == 1


def test_rep_not_counted_when_gate_closed():
    m = SessionMetrics()
    for i, c in enumerate([0.0, 0.7, 0.2]):
        m.update(i * 20, IDLE, _v(c), _g(False))
    assert m.snapshot()["reps"] == 0


def test_activation_rate():
    m = SessionMetrics()
    for i, o in enumerate([True, True, True, False]):
        m.update(i * 20, ACTIVE, _v(0.5), _g(o))
    m.update(100, ACTIVE, VisionResult(None, []), _g(False, target=False))  # no target: not counted
    assert m.snapshot()["activation_rate"] == 75.0


def test_latency_trial():
    m = SessionMetrics()
    m.start_latency_trial(1000)
    m.update(1200, IDLE, _v(0), _g(False))
    events = m.update(1350, ACTIVE, _v(0), _g(False))
    assert {"t": 1350, "type": "latency", "ms": 350} in events
    assert m.snapshot()["latency_ms_mean"] == 350


def test_latency_miss_after_3s():
    m = SessionMetrics()
    m.start_latency_trial(1000)
    events = m.update(4100, IDLE, _v(0), _g(False))
    assert events == [{"t": 4100, "type": "latency_miss"}]


def test_compensation_event_on_rising_edge_only():
    m = SessionMetrics()
    events = []
    for i in range(5):
        events += m.update(i * 20, ACTIVE, _v(0.3, ["shoulder_hike"]), _g(False))
    assert events == [{"t": 0, "type": "shoulder_hike"}]
    assert m.snapshot()["compensation_count"] == 1


def test_grip_latency_response():
    m = SessionMetrics(latency_response="grip")
    m.start_latency_trial(1000)
    assert m.trial_active
    assert m.update(1100, ACTIVE, _v(0.2), _g(False)) == []  # intent alone doesn't count
    ev = m.update(1400, IDLE, _v(0.8), _g(False))
    assert {"t": 1400, "type": "latency", "ms": 400} in ev
    assert m.snapshot()["latencies"] == [400] and not m.trial_active
