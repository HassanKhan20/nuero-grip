import json
from types import SimpleNamespace

from neurogrip.triage import (DEFAULT_THERAPISTS, ai_brief, risk_score, seed_population,
                              triage_population)


class FakeClient:
    def __init__(self, content):
        self.content, self.calls = content, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        msg = SimpleNamespace(content=self.content, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_population_is_large_deterministic_and_unique():
    a, b = seed_population(1200, seed=7), seed_population(1200, seed=7)
    assert len(a) == 1200 and a == b
    assert len({p["patient_id"] for p in a}) == 1200
    assert {"region", "condition", "last_session_days_ago", "activation_rate_trend"} <= set(a[0])


def test_risk_score_ranks_a_stale_declining_patient_above_a_healthy_one():
    healthy = {"last_session_days_ago": 1, "activation_rate_trend": [60, 62, 64, 66, 70],
               "tremor_hz": 0.0, "latency_ms_mean": 700}
    bad = {"last_session_days_ago": 12, "activation_rate_trend": [60, 52, 45, 38, 30],
           "tremor_hz": 5.2, "latency_ms_mean": 1400}
    (hs, _), (bs, factors) = risk_score(healthy), risk_score(bad)
    assert 0 <= hs < 20 and 70 <= bs <= 100
    assert any("12 days" in f for f in factors) and any("declining" in f for f in factors)


def test_every_patient_is_triaged_and_hard_rule_holds_for_all():
    pop = seed_population(1200, seed=7)
    res = triage_population(pop, DEFAULT_THERAPISTS)
    rows = res["patients"]
    assert len(rows) == 1200 and res["summary"]["total"] == 1200
    assert all(r["urgency"] in ("urgent", "monitor", "stable") for r in rows)
    for r in rows:
        if r["last_session_days_ago"] >= 3 or r["trend"] == "declining":
            assert r["urgency"] == "urgent", r
    s = res["summary"]
    assert s["urgent"] + s["monitor"] + s["stable"] == 1200
    assert 0.08 * 1200 < s["urgent"] < 0.35 * 1200  # a real triage, not all red


def test_assignment_fills_urgent_first_and_respects_capacity():
    pop = seed_population(1200, seed=7)
    res = triage_population(pop, {"Dr. A": 50, "Dr. B": 50})
    rows = res["patients"]
    for t in res["therapists"]:
        assert t["assigned"] <= t["capacity"]
    urgent = [r for r in rows if r["urgency"] == "urgent"]
    assigned_urgent = [r for r in urgent if r["assigned_to"]]
    assert len(assigned_urgent) == min(100, len(urgent))
    if len(urgent) >= 100:
        assert not any(r["assigned_to"] for r in rows if r["urgency"] != "urgent")
    s = res["summary"]
    assert s["unassigned_urgent"] == len(urgent) - len(assigned_urgent)
    # the most at-risk urgent patients get a therapist before the less at-risk ones
    scores_in = [r["risk"] for r in assigned_urgent]
    scores_out = [r["risk"] for r in urgent if not r["assigned_to"]]
    if scores_out:
        assert min(scores_in) >= max(scores_out)


def test_rows_sorted_urgent_first_then_by_risk():
    res = triage_population(seed_population(300, seed=3), DEFAULT_THERAPISTS)
    order = ["urgent", "monitor", "stable"]
    keys = [(order.index(r["urgency"]), -r["risk"]) for r in res["patients"]]
    assert keys == sorted(keys)


def test_by_region_counts_add_up():
    res = triage_population(seed_population(500, seed=1), DEFAULT_THERAPISTS)
    assert sum(v["urgent"] for v in res["summary"]["by_region"].values()) == res["summary"]["urgent"]


def test_ai_brief_reads_only_the_top_slice_and_returns_plan_and_reasons():
    res = triage_population(seed_population(1200, seed=7), DEFAULT_THERAPISTS)
    top = res["patients"][0]
    reply = {"brief": "Send the overflow to tele-rehab.", "reasons": {top["patient_id"]: "Worst decline."}}
    client = FakeClient("<think>x</think>" + json.dumps(reply))
    out = ai_brief(client, "m", res, top=12)
    assert out["brief"].startswith("Send") and out["reasons"][top["patient_id"]] == "Worst decline."
    sent = json.loads(client.calls[0]["messages"][1]["content"])
    assert len(sent["top_patients"]) == 12 and sent["summary"]["total"] == 1200
    assert "extra_body" in client.calls[0]


def test_ai_brief_ignores_reasons_for_unknown_ids():
    res = triage_population(seed_population(100, seed=2), DEFAULT_THERAPISTS)
    client = FakeClient(json.dumps({"brief": "ok", "reasons": {"ghost": "x"}}))
    assert ai_brief(client, "m", res, top=5)["reasons"] == {}
