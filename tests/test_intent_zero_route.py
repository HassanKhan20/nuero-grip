import pytest

from app import create_app
from neurogrip.engine import Engine
from neurogrip.sources import MockSource
from neurogrip.store import MemoryStore
from neurogrip.vision import MockVision


@pytest.fixture
def client():
    engine = Engine(MockSource(), MockVision(), MemoryStore())
    app, _ = create_app(engine, start=False)
    app.config["TESTING"] = True
    return app.test_client(), engine


def test_zero_requires_login(client):
    c, _ = client
    assert c.post("/api/intent/zero").status_code in (302, 401)


def test_zero_rebaselines_intent(client):
    c, engine = client
    c.post("/login", data={"username": "patient", "password": "patient"})
    r = c.post("/api/intent/zero")
    assert r.status_code == 200 and r.get_json()["ok"]
    assert engine.intent._rezero_pending
