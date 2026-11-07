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
    assert b"Run AI agent" in client.get("/").data
    client.get("/logout")
    _login(client, "patient")
    page = client.get("/").data
    assert b"Explain my progress" in page and b"Run AI agent" not in page
