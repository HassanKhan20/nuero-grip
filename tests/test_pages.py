"""Each track is its own full page (not a pop-up): session, AI reasoning, command center, surge response."""
import pytest

import app as app_module
from app import create_app
from neurogrip.engine import Engine
from neurogrip.sources import MockSource
from neurogrip.store import MemoryStore
from neurogrip.vision import MockVision

PAGES = {"/reasoning": b"AI reasoning", "/command": b"Command center", "/surge": b"Surge response"}


@pytest.fixture
def made(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NG_ISOLATED", raising=False)
    app, _ = create_app(Engine(MockSource(), MockVision(), MemoryStore()), start=False)
    app.config["TESTING"] = True
    return app, app.test_client()


def _login(c, user):
    return c.post("/login", data={"username": user, "password": user})


@pytest.mark.parametrize("path,heading", PAGES.items())
def test_therapist_opens_each_system_page(made, path, heading):
    _, c = made
    _login(c, "therapist")
    r = c.get(path)
    assert r.status_code == 200 and heading in r.data


def test_every_page_carries_the_system_nav(made):
    _, c = made
    _login(c, "therapist")
    for path in ["/", *PAGES]:
        html = c.get(path).data
        for link in (b'href="/"', b'href="/reasoning"', b'href="/command"', b'href="/surge"'):
            assert link in html, (path, link)


def test_pages_require_login(made):
    _, c = made
    for path in PAGES:
        assert c.get(path).status_code == 302


def test_patient_opening_a_therapist_page_is_blocked_logged_and_raised(made):
    app, c = made
    _login(c, "patient")
    r = c.get("/command")
    assert r.status_code == 403 and b"Access denied" in r.data
    ng = app.extensions["ng"]
    assert ng["audit"].list()[0]["action"] == "denied"
    inc = ng["incidents"].list()[0]
    assert inc["kind"] == "access_denied" and inc["scope"]["endpoint"] == "/command"


def test_agent_runs_are_kept_for_the_reasoning_page(made, monkeypatch):
    _, c = made
    _login(c, "therapist")
    assert c.get("/api/agent/runs").get_json()["runs"] == []
    monkeypatch.setattr(app_module, "make_nvidia_client", lambda: object())
    monkeypatch.setattr(app_module, "run_agent", lambda client, model, tools: {
        "summary": "Good session.", "next_session_plan": "Raise to level 4.",
        "trace": [{"step": 1, "tool": "get_session_metrics", "args": {}, "result": {"reps": 3}, "reasoning": "look"}]})
    r = c.post("/api/agent").get_json()
    assert r["id"] == 1 and r["summary"] == "Good session." and r["at"] > 0
    assert r["context"]["mode"] == "stroke"
    runs = c.get("/api/agent/runs").get_json()["runs"]
    assert len(runs) == 1 and runs[0]["trace"][0]["tool"] == "get_session_metrics"


def test_patient_cannot_read_agent_runs(made):
    _, c = made
    _login(c, "patient")
    assert c.get("/api/agent/runs").status_code == 403


def test_mind_control_page_is_open_to_both_roles_but_needs_login(made):
    _, c = made
    assert c.get("/mind").status_code == 302
    _login(c, "patient")
    r = c.get("/mind")
    assert r.status_code == 200 and b"Mind Control" in r.data
    assert b'href="/mind"' in c.get("/").data


def test_session_page_has_zero_button_wired_to_the_endpoint(made):
    app, c = made
    _login(c, "patient")
    assert b'id="btn-zero"' in c.get("/").data
    assert c.post("/api/intent/zero").get_json()["ok"] is True
    assert app.extensions["ng"]["audit"].list()[0]["action"] == "intent_zero"


def test_end_session_review_covers_the_session_just_finished(monkeypatch):
    """End session -> AI reasoning must review the reps just done, then save and reset (not review an empty session)."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    store = MemoryStore()
    eng = Engine(MockSource(), MockVision(), store)
    app, _ = create_app(eng, start=False)
    app.config["TESTING"] = True
    c = app.test_client()
    _login(c, "therapist")
    eng.metrics.reps = 4
    seen = {}

    def fake_agent(client, model, tools):
        seen["reps"] = eng.metrics.reps
        return {"summary": "ok", "next_session_plan": "", "trace": []}

    monkeypatch.setattr(app_module, "make_nvidia_client", lambda: object())
    monkeypatch.setattr(app_module, "run_agent", fake_agent)
    r = c.post("/api/agent", json={"end_session": True})
    assert r.status_code == 200
    assert seen["reps"] == 4                      # reviewed the finished session
    assert eng.metrics.reps == 0                  # then a fresh one started
    assert store.history("demo")[0]["reps"] == 4  # and the finished one was saved


def test_end_session_still_saves_when_the_ai_is_unavailable(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    store = MemoryStore()
    eng = Engine(MockSource(), MockVision(), store)
    app, _ = create_app(eng, start=False)
    app.config["TESTING"] = True
    c = app.test_client()
    _login(c, "therapist")
    eng.metrics.reps = 3
    monkeypatch.setattr(app_module, "make_nvidia_client", lambda: None)
    assert c.post("/api/agent", json={"end_session": True}).status_code >= 400
    assert eng.metrics.reps == 0 and store.history("demo")[0]["reps"] == 3
