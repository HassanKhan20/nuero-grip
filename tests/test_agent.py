import json
from types import SimpleNamespace

from neurogrip.agent import ToolBox, run_agent
from neurogrip.engine import Engine
from neurogrip.sources import MockSource
from neurogrip.store import MemoryStore
from neurogrip.vision import MockVision


def _call(name, args, i=0):
    return SimpleNamespace(id=f"c{i}", type="function",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _msg(content=None, calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))])


class FakeClient:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        return self.script.pop(0) if self.script else _msg(calls=[_call("get_session_metrics", {}, 99)])


def _tools():
    return ToolBox(Engine(MockSource(), MockVision(), MemoryStore()))


def test_agent_runs_tool_loop():
    tools = _tools()
    final = json.dumps({"summary": "Good session.", "next_session_plan": "Level 4."})
    client = FakeClient([
        _msg(calls=[_call("get_session_metrics", {}, 1)]),
        _msg(calls=[_call("set_difficulty", {"level": 4, "reason": "high activation"}, 2)]),
        _msg(content=final),
    ])
    out = run_agent(client, "m", tools)
    assert [t["tool"] for t in out["trace"]] == ["get_session_metrics", "set_difficulty"]
    assert tools.engine.state()["difficulty"] == 4
    assert out["summary"] == "Good session." and out["next_session_plan"] == "Level 4."
    assert client.requests[0]["tools"] == ToolBox.SCHEMAS


def test_agent_plain_text_final():
    out = run_agent(FakeClient([_msg(content="Patient improved.")]), "m", _tools())
    assert out == {"summary": "Patient improved.", "next_session_plan": "", "trace": []}


def test_agent_parses_fenced_json():
    content = "```json\n{\"summary\": \"S\", \"next_session_plan\": \"P\"}\n```"
    out = run_agent(FakeClient([_msg(content=content)]), "m", _tools())
    assert out["summary"] == "S" and out["next_session_plan"] == "P"


def test_set_difficulty_clamped():
    assert _tools().set_difficulty(9, "x")["level"] == 5


def test_unknown_tool_reported_in_trace():
    client = FakeClient([_msg(calls=[_call("rm_rf", {}, 1)]), _msg(content="done")])
    out = run_agent(client, "m", _tools())
    assert "error" in out["trace"][0]["result"]


def test_agent_stops_at_max_steps():
    out = run_agent(FakeClient([]), "m", _tools(), max_steps=6)
    assert len(out["trace"]) == 6 and "step limit" in out["summary"]


def test_trigger_feedback_sends_commands():
    tools = _tools()
    tools.trigger_feedback("correct_posture", "drop your shoulder")
    assert "B,300,400\n" in tools.engine.source.sent and "L,R\n" in tools.engine.source.sent


def test_nvidia_client_has_short_timeout(monkeypatch):
    from neurogrip.agent import make_nvidia_client
    monkeypatch.setenv("NVIDIA_API_KEY", "x")
    c = make_nvidia_client()
    assert c.timeout == 45 and c.max_retries == 1
