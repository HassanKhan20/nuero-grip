from neurogrip.incidents import AuditLog, IncidentLog
from neurogrip.store import MemoryStore


def _log(**kw):
    changes = []
    return IncidentLog(MemoryStore(), on_change=changes.append, **kw), changes


def test_raise_opens_incident_with_scope_and_timeline():
    log, changes = _log()
    inc = log.raise_incident("tremor", "Rest tremor detected", "medium", "clinical",
                             {"patient": "demo"}, "4.8 Hz for 5 s")
    assert inc["status"] == "open" and inc["severity"] == "medium" and inc["category"] == "clinical"
    assert inc["scope"] == {"patient": "demo"}
    assert inc["timeline"][0]["actor"] == "system" and "4.8 Hz" in inc["timeline"][0]["text"]
    assert inc["id"].startswith("INC-") and changes[-1]["id"] == inc["id"]


def test_same_detection_while_open_is_deduplicated_and_escalates():
    log, _ = _log()
    a = log.raise_incident("tremor", "Tremor", "medium", "clinical", {"patient": "demo"}, "first")
    b = log.raise_incident("tremor", "Tremor", "high", "clinical", {"patient": "demo"}, "again")
    assert a["id"] == b["id"] and b["count"] == 2 and b["severity"] == "high"
    assert len(log.list()) == 1


def test_detection_after_resolve_opens_a_new_incident():
    log, _ = _log()
    a = log.raise_incident("sensor_loss", "Lost", "critical", "device", {"device": "headband"}, "x")
    log.resolve(a["id"], "therapist", "re-seated pads")
    b = log.raise_incident("sensor_loss", "Lost", "critical", "device", {"device": "headband"}, "x")
    assert a["id"] != b["id"]


def test_workflow_ack_assign_note_resolve():
    log, changes = _log()
    inc = log.raise_incident("camera_loss", "Camera offline", "high", "device", {"device": "camera"}, "no frames")
    log.acknowledge(inc["id"], "therapist")
    log.assign(inc["id"], "therapist", "therapist")
    log.note(inc["id"], "therapist", "checking the USB cable")
    done = log.resolve(inc["id"], "therapist", "cable replaced")
    assert done["status"] == "resolved" and done["owner"] == "therapist"
    assert [e["kind"] for e in done["timeline"]] == ["detected", "acknowledged", "assigned", "note", "resolved"]
    assert log.counts()["open"] == 0 and len(changes) == 5


def test_auto_resolve_only_touches_open_system_incidents():
    log, _ = _log()
    log.raise_incident("sensor_loss", "Lost", "critical", "device", {"device": "headband"}, "x")
    assert log.auto_resolve("sensor_loss", {"device": "headband"}, "signal restored")["status"] == "resolved"
    assert log.auto_resolve("sensor_loss", {"device": "headband"}, "again") is None


def test_unknown_incident_raises_key_error():
    log, _ = _log()
    try:
        log.acknowledge("INC-9999", "therapist")
    except KeyError:
        return
    raise AssertionError("expected KeyError")


def test_incidents_persist_and_reload_from_store():
    store = MemoryStore()
    first = IncidentLog(store)
    first.raise_incident("tremor", "Tremor", "medium", "clinical", {"patient": "demo"}, "x")
    again = IncidentLog(store)
    assert len(again.list()) == 1
    nxt = again.raise_incident("camera_loss", "Cam", "high", "device", {"device": "camera"}, "x")
    assert nxt["id"] != again.list()[1]["id"]


def test_list_filters_by_status_newest_first():
    log, _ = _log()
    a = log.raise_incident("a", "A", "low", "clinical", {}, "x")
    log.raise_incident("b", "B", "low", "clinical", {}, "x")
    log.resolve(a["id"], "therapist", "ok")
    assert [i["kind"] for i in log.list("open")] == ["b"]
    assert [i["kind"] for i in log.list()] == ["b", "a"]


def test_audit_log_records_newest_first():
    audit = AuditLog(MemoryStore())
    audit.record("therapist", "login", "ok", "127.0.0.1")
    audit.record("patient", "denied", "/api/difficulty", "127.0.0.1")
    rows = audit.list()
    assert rows[0]["action"] == "denied" and rows[1]["actor"] == "therapist"
