import json
from types import SimpleNamespace

from neurogrip.triage import seed_demo_patients, triage_patients


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        msg = SimpleNamespace(content=self.content, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_seed_has_ten_patients_with_deteriorating_ones():
    ps = seed_demo_patients()
    assert len(ps) == 10 and len({p["patient_id"] for p in ps}) == 10
    worsening = [p for p in ps if p["activation_rate_trend"][-1] < p["activation_rate_trend"][0] - 15]
    assert len(worsening) >= 2


def test_triage_parses_and_sorts():
    ps = seed_demo_patients()
    reply = [
        {"patient_id": ps[0]["patient_id"], "urgency": "stable", "reason": "ok"},
        {"patient_id": ps[1]["patient_id"], "urgency": "urgent", "reason": "declining"},
        {"patient_id": ps[2]["patient_id"], "urgency": "watch", "reason": "tremor up"},
        {"patient_id": "ghost", "urgency": "urgent", "reason": "not real"},
    ]
    out = triage_patients(FakeClient("```json\n" + json.dumps(reply) + "\n```"), "m", ps[:3])
    assert [r["urgency"] for r in out] == ["urgent", "watch", "stable"]
    assert out[0]["patient_id"] == ps[1]["patient_id"] and out[0]["reason"] == "declining"
    assert "name" in out[0]


def test_triage_fills_missing_patients():
    ps = seed_demo_patients()
    reply = [{"patient_id": ps[0]["patient_id"], "urgency": "urgent", "reason": "x"}]
    out = triage_patients(FakeClient(json.dumps(reply)), "m", ps)
    assert len(out) == 10
    assert sum(r["reason"] == "not assessed by AI" for r in out) == 9
