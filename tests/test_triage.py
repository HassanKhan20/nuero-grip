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
    ps = [p for p in seed_demo_patients() if p["patient_id"] in ("P-101", "P-103", "P-105")]
    reply = [
        {"patient_id": ps[0]["patient_id"], "urgency": "stable", "reason": "ok"},
        {"patient_id": ps[1]["patient_id"], "urgency": "urgent", "reason": "declining"},
        {"patient_id": ps[2]["patient_id"], "urgency": "MONITOR", "reason": "tremor up"},
        {"patient_id": "ghost", "urgency": "urgent", "reason": "not real"},
    ]
    out = triage_patients(FakeClient("```json\n" + json.dumps(reply) + "\n```"), "m", ps[:3])
    assert [r["urgency"] for r in out] == ["urgent", "monitor", "stable"]
    assert out[0]["patient_id"] == ps[1]["patient_id"] and out[0]["reason"] == "declining"
    assert "name" in out[0]


def test_triage_fills_missing_patients():
    ps = seed_demo_patients()
    reply = [{"patient_id": ps[0]["patient_id"], "urgency": "urgent", "reason": "x"}]
    out = triage_patients(FakeClient(json.dumps(reply)), "m", ps)
    assert len(out) == 10
    unassessed = [r for r in out if r["reason"] == "not assessed by AI"]
    assert unassessed and all(r["urgency"] == "monitor" for r in unassessed)


def test_seed_trends_and_urgent_spread():
    ps = {p["patient_id"]: p for p in seed_demo_patients()}
    assert ps["P-101"]["trend"] == "improving" and ps["P-104"]["trend"] == "declining"
    assert ps["P-106"]["trend"] == "stable"
    urgent = [p for p in ps.values() if p["last_session_days_ago"] >= 3 or p["trend"] == "declining"]
    assert 3 <= len(urgent) <= 5  # a triage list that isn't all red


def test_stale_or_declining_patient_forced_urgent():
    ps = seed_demo_patients()
    reply = [{"patient_id": p["patient_id"], "urgency": "STABLE", "reason": "fine"} for p in ps]
    out = {r["patient_id"]: r for r in triage_patients(FakeClient(json.dumps(reply)), "m", ps)}
    assert out["P-110"]["urgency"] == "urgent" and "21 days" in out["P-110"]["reason"]
    assert out["P-108"]["urgency"] == "urgent" and "declining" in out["P-108"]["reason"]
    assert out["P-101"]["urgency"] == "stable" and out["P-101"]["reason"] == "fine"
    order = [r["urgency"] for r in triage_patients(FakeClient(json.dumps(reply)), "m", ps)]
    assert order == sorted(order, key=["urgent", "monitor", "stable"].index)
