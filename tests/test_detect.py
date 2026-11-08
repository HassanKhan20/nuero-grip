from neurogrip.detect import Detector
from neurogrip.incidents import IncidentLog


def _state(**kw):
    base = {"sensors_ok": True, "camera_ok": True, "source_kind": "camera", "tremor_hz": 0.0,
            "tremor_amp": 0.0, "steadiness": 100.0, "mode": "stroke", "patient_id": "demo"}
    return {**base, **kw}


def _det():
    log = IncidentLog()
    return Detector(log, sustain_s=5), log


def test_healthy_stream_raises_nothing():
    det, log = _det()
    for t in range(20):
        det.check(_state(), now=float(t))
    assert log.list() == []


def test_sensor_loss_opens_critical_device_incident_and_auto_resolves():
    det, log = _det()
    det.check(_state(sensors_ok=False), now=0.0)
    det.check(_state(sensors_ok=False), now=2.5)
    inc = log.list()[0]
    assert inc["kind"] == "sensor_loss" and inc["severity"] == "critical" and inc["category"] == "device"
    for t in (3.0, 4.0, 6.0):
        det.check(_state(), now=t)
    assert log.list()[0]["status"] == "resolved"


def test_brief_sensor_blip_is_ignored():
    det, log = _det()
    det.check(_state(sensors_ok=False), now=0.0)
    det.check(_state(), now=0.5)
    assert log.list() == []


def test_camera_loss_ignored_in_mock_mode():
    det, log = _det()
    for t in range(6):
        det.check(_state(camera_ok=False, source_kind="mock"), now=float(t))
    assert log.list() == []
    for t in range(6, 12):
        det.check(_state(camera_ok=False, source_kind="camera"), now=float(t))
    assert log.list()[0]["kind"] == "camera_loss"


def test_sustained_parkinsonian_tremor_is_detected_once():
    det, log = _det()
    for t in range(4):
        det.check(_state(tremor_hz=4.8), now=float(t))
    assert log.list() == []  # not yet sustained for 5 s
    for t in range(4, 30):
        det.check(_state(tremor_hz=4.8), now=float(t))
    rows = log.list()
    assert len(rows) == 1 and rows[0]["kind"] == "tremor" and "4.8 Hz" in rows[0]["title"]
    assert "4-6 Hz" in rows[0]["detail"] and rows[0]["category"] == "clinical"


def test_intermittent_tremor_never_sustains():
    det, log = _det()
    for t in range(30):
        det.check(_state(tremor_hz=4.8 if t % 2 else 0.0), now=float(t))
    assert log.list() == []


def test_slow_reactions_open_a_clinical_incident():
    det, log = _det()
    det.on_event({"type": "latency", "ms": 1400})
    assert log.list() == []
    det.on_event({"type": "latency", "ms": 1250})
    inc = log.list()[0]
    assert inc["kind"] == "slow_reaction" and "1325 ms" in inc["detail"]


def test_missed_cues_open_incident():
    det, log = _det()
    det.on_event({"type": "latency_miss"})
    det.on_event({"type": "latency_miss"})
    assert log.list()[0]["kind"] == "missed_cues"


def test_tapping_bradykinesia_flag_opens_incident():
    det, log = _det()
    det.on_event({"type": "tapping", "taps": 14, "rate_hz": 1.4, "decrement_pct": 31.0,
                  "flag": "possible bradykinesia"})
    inc = log.list()[0]
    assert inc["kind"] == "bradykinesia" and "1.4 taps/s" in inc["detail"]
    det.on_event({"type": "tapping", "taps": 30, "rate_hz": 3.1, "decrement_pct": 4, "flag": "within typical range"})
    assert len(log.list()) == 1


def test_one_sustained_episode_counts_once_and_a_new_episode_counts_again():
    det, log = _det()
    for t in range(30):
        det.check(_state(tremor_hz=4.8), now=float(t))
    assert log.list()[0]["count"] == 1
    det.check(_state(tremor_hz=0.0), now=30.0)
    for t in range(31, 40):
        det.check(_state(tremor_hz=4.8), now=float(t))
    assert len(log.list()) == 1 and log.list()[0]["count"] == 2


def test_sensor_loss_raised_once_per_outage():
    changes = []
    log = IncidentLog(on_change=changes.append)
    det = Detector(log, sustain_s=5)
    for t in range(20):
        det.check(_state(sensors_ok=False), now=float(t))
    assert len(changes) == 1
