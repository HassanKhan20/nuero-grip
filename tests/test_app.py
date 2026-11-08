import pytest

from app import create_app
from neurogrip.engine import Engine
from neurogrip.sources import MockSource
from neurogrip.store import MemoryStore
from neurogrip.vision import MockVision


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    app, _ = create_app(Engine(MockSource(), MockVision(), MemoryStore()), start=False)
    app.config["TESTING"] = True
    return app.test_client()


def _login(c, user, pw=None):
    return c.post("/login", data={"username": user, "password": pw or user})


def test_dashboard_requires_login(client):
    assert client.get("/").status_code == 302


def test_wrong_password_stays_on_login(client):
    r = _login(client, "therapist", "nope")
    assert r.status_code == 200 and b"Invalid" in r.data


def test_patient_forbidden_from_agent(client):
    _login(client, "patient")
    assert client.post("/api/agent").status_code == 403


def test_agent_endpoint_without_key(client):
    _login(client, "therapist")
    r = client.post("/api/agent")
    assert r.status_code == 503 and "error" in r.get_json()


def test_patient_view_without_key(client):
    _login(client, "patient")
    r = client.post("/api/patient_view")
    assert r.status_code == 503 and "error" in r.get_json()


def test_therapist_sets_difficulty_and_mode(client):
    _login(client, "therapist")
    assert client.post("/api/difficulty", json={"level": 4}).get_json()["level"] == 4
    assert client.post("/api/mode", json={"mode": "parkinsons"}).get_json()["mode"] == "parkinsons"
    assert client.post("/api/mode", json={"mode": "bogus"}).status_code == 400


def test_dashboard_renders_for_both_roles(client):
    _login(client, "therapist")
    assert b"Review session" in client.get("/").data
    client.get("/logout")
    _login(client, "patient")
    page = client.get("/").data
    assert b"Explain my progress" in page and b"Review session" not in page


def test_intent_hold_sets_control(client):
    _login(client, "patient")
    assert client.post("/api/intent", json={"held": True}).get_json()["held"] is True
    assert client.post("/api/intent/auto", json={"auto": True}).get_json()["auto"] is True
    s = client.get("/api/state").get_json()
    assert s["intent_held"] and s["intent_auto"]


def test_video_feed_404_without_camera(client):
    _login(client, "patient")
    assert client.get("/video_feed").status_code == 404


def test_tapping_requires_therapist(client):
    _login(client, "patient")
    assert client.post("/api/tapping").status_code == 403
    client.get("/logout")
    _login(client, "therapist")
    assert client.post("/api/tapping", json={"seconds": 5}).get_json()["ok"] is True


def test_state_has_source_kind(client):
    _login(client, "therapist")
    assert client.get("/api/state").get_json()["source_kind"] == "mock"


def test_control_endpoint(client):
    _login(client, "patient")
    r = client.post("/api/control", json={"mode": "intent", "grip": "pinch"})
    assert r.status_code == 200 and r.get_json() == {"control_mode": "intent", "grip": "pinch"}
    assert client.post("/api/control", json={"mode": "nope"}).status_code == 400


def test_calibrate_endpoint(client):
    _login(client, "patient")
    assert client.post("/api/calibrate").get_json() == {"ok": True}
    assert client.get("/api/state").get_json()["calibration_phase"] == "relax"


def test_secret_key_survives_restarts(tmp_path, monkeypatch):
    # a restart must not invalidate everyone's login (open tabs would hang on "Connecting")
    from app import load_secret
    monkeypatch.delenv("NG_SECRET", raising=False)
    path = tmp_path / ".ng_secret"
    first = load_secret(path)
    assert path.exists() and len(first) >= 32
    assert load_secret(path) == first
    monkeypatch.setenv("NG_SECRET", "from-env")
    assert load_secret(path) == "from-env"


def test_incident_board_is_therapist_only(client):
    _login(client, "patient")
    assert client.get("/api/incidents").status_code == 403
    assert client.get("/api/audit").status_code == 403


def test_denied_request_is_audited_and_opens_security_incident(client):
    _login(client, "patient")
    client.post("/api/difficulty", json={"level": 5})
    client.get("/logout")
    _login(client, "therapist")
    incs = client.get("/api/incidents").get_json()["incidents"]
    sec = [i for i in incs if i["category"] == "security"]
    assert sec and "/api/difficulty" in sec[0]["detail"]
    actions = [r["action"] for r in client.get("/api/audit").get_json()["audit"]]
    assert "denied" in actions and "login" in actions


def test_failed_logins_lock_out_and_raise_incident(client):
    for _ in range(5):
        _login(client, "therapist", "wrong")
    r = _login(client, "therapist")
    assert r.status_code == 429 and b"Too many" in r.data


def test_three_failed_logins_open_security_incident(client):
    for _ in range(3):
        _login(client, "therapist", "wrong")
    # lockout not reached yet: the right password still works
    assert _login(client, "therapist").status_code == 302
    incs = client.get("/api/incidents").get_json()["incidents"]
    assert any(i["kind"] == "failed_logins" for i in incs)


def test_incident_workflow_over_http(client):
    _login(client, "therapist")
    inc = client.post("/api/incidents", json={"title": "Pad came loose", "severity": "high",
                                              "category": "device", "detail": "left temple"}).get_json()
    iid = inc["id"]
    assert client.post(f"/api/incidents/{iid}/ack").get_json()["status"] == "acknowledged"
    assert client.post(f"/api/incidents/{iid}/note", json={"text": "re-taped"}).status_code == 200
    assert client.post(f"/api/incidents/{iid}/note", json={"text": "  "}).status_code == 400
    done = client.post(f"/api/incidents/{iid}/resolve", json={"text": "fixed"}).get_json()
    assert done["status"] == "resolved" and done["timeline"][-1]["text"] == "fixed"
    assert client.post("/api/incidents/INC-1/ack").status_code == 404
    assert client.post("/api/incidents", json={"title": "x", "severity": "apocalyptic"}).status_code == 400
    counts = client.get("/api/incidents").get_json()["counts"]
    assert counts["resolved"] >= 1


def test_population_triage_covers_everyone(client):
    _login(client, "therapist")
    body = client.get("/api/triage/population?limit=50").get_json()
    assert body["summary"]["total"] == 1200 and len(body["patients"]) == 50
    assert body["patients"][0]["urgency"] == "urgent"
    if body["summary"]["unassigned_urgent"]:
        incs = client.get("/api/incidents").get_json()["incidents"]
        assert any(i["category"] == "caseload" for i in incs)


def test_population_brief_needs_key(client):
    _login(client, "therapist")
    assert client.post("/api/triage/brief").status_code == 503


def test_security_headers(client):
    r = client.get("/login")
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"
