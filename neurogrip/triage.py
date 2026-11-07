"""Multi-patient AI triage: an LLM flags who needs urgent attention and why."""
import json
import re

from .agent import NEMOTRON_KWARGS

URGENCY_ORDER = {"urgent": 0, "monitor": 1, "stable": 2}
STALE_DAYS = 3  # no session in this many days -> URGENT
TREND_DELTA = 5  # activation-rate points (first -> last session) that count as a real trend

TRIAGE_PROMPT = """You are a patient triage AI for a neuro-rehabilitation clinic, so no patient is overlooked.
You receive a JSON list of patients. Per patient: name, condition, latency_ms_mean (reaction latency),
tremor_hz (0 = none), activation_rate_trend (gate activation % over their last 5 sessions, oldest first:
the % of time their intent was strong enough to move the robotic hand),
last_session_days_ago, and trend (improving / declining / stable).

For EVERY patient:
- Assign urgency: "URGENT", "MONITOR", or "STABLE".
- Give ONE sentence explaining why, citing the numbers.
- Anyone with no session in 3+ days, or a declining trend, is URGENT.
- MONITOR patients who are not urgent but show a concern: tremor present or reaction latency above 1000 ms.

Sort by urgency (URGENT first). Reply with ONLY a JSON array:
[{"patient_id": "...", "urgency": "URGENT", "reason": "..."}]"""


def trend_of(series: list[float]) -> str:
    delta = series[-1] - series[0]
    if delta >= TREND_DELTA:
        return "improving"
    if delta <= -TREND_DELTA:
        return "declining"
    return "stable"


def seed_demo_patients() -> list[dict]:
    rows = [
        ("P-101", "Avery M.", "stroke", 2, [42, 48, 55, 61, 66], 0.0, 820),
        ("P-102", "Jordan K.", "parkinsons", 9, [70, 64, 55, 49, 41], 5.8, 910),
        ("P-103", "Riley S.", "cp", 1, [35, 38, 40, 44, 47], 0.0, 1020),
        ("P-104", "Morgan T.", "stroke", 14, [58, 51, 44, 38, 30], 0.0, 1180),
        ("P-105", "Casey L.", "phantom", 1, [60, 62, 63, 65, 64], 0.0, 760),
        ("P-106", "Quinn R.", "cognitive", 2, [72, 71, 70, 69, 70], 0.0, 1340),
        ("P-107", "Taylor B.", "parkinsons", 2, [55, 56, 54, 57, 58], 4.6, 880),
        ("P-108", "Drew P.", "stroke", 2, [50, 49, 47, 46, 44], 0.0, 990),
        ("P-109", "Skyler N.", "cp", 1, [28, 33, 39, 45, 52], 0.0, 1100),
        ("P-110", "Emerson H.", "cognitive", 21, [68, 66, 63, 59, 56], 0.0, 1520),
    ]
    keys = ["patient_id", "name", "condition", "last_session_days_ago", "activation_rate_trend",
            "tremor_hz", "latency_ms_mean"]
    patients = [dict(zip(keys, r)) for r in rows]
    for p in patients:
        p["trend"] = trend_of(p["activation_rate_trend"])
    return patients


def _rule_reason(p: dict) -> str | None:
    """The clinic's hard rule: a stale or declining patient is always URGENT, whatever the model says."""
    reasons = []
    if p.get("last_session_days_ago", 0) >= STALE_DAYS:
        reasons.append(f"no session in {p['last_session_days_ago']} days")
    trend = p.get("trend") or trend_of(p.get("activation_rate_trend") or [0])
    if trend == "declining":
        series = p["activation_rate_trend"]
        reasons.append(f"activation rate declining {series[0]}% → {series[-1]}%")
    if not reasons:
        return None
    text = " and ".join(reasons)
    return text[0].upper() + text[1:] + "."


def _extract_json_array(text: str) -> list:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\[.*\]", text, flags=re.S)
    if not m:
        raise ValueError("model reply contained no JSON array")
    data = json.loads(m.group(0))
    if not isinstance(data, list):
        raise ValueError("model reply was not a JSON array")
    return data


def _norm_urgency(u) -> str | None:
    u = str(u or "").strip().lower()
    return {"watch": "monitor"}.get(u, u) if u in URGENCY_ORDER or u == "watch" else None


def triage_patients(client, model: str, patients: list[dict]) -> list[dict]:
    patients = [{**p, "trend": p.get("trend") or trend_of(p["activation_rate_trend"])} for p in patients]
    resp = client.chat.completions.create(model=model, **NEMOTRON_KWARGS, messages=[
        {"role": "system", "content": TRIAGE_PROMPT},
        {"role": "user", "content": json.dumps(patients)},
    ])
    verdicts = {}
    for v in _extract_json_array(resp.choices[0].message.content):
        if isinstance(v, dict) and _norm_urgency(v.get("urgency")):
            verdicts[v.get("patient_id")] = {**v, "urgency": _norm_urgency(v.get("urgency"))}
    out = []
    for p in patients:
        v = verdicts.get(p["patient_id"], {"urgency": "monitor", "reason": "not assessed by AI"})
        urgency, reason = v["urgency"], str(v.get("reason", ""))
        rule = _rule_reason(p)
        if rule and urgency != "urgent":
            urgency, reason = "urgent", rule
        out.append({**p, "urgency": urgency, "reason": reason})
    return sorted(out, key=lambda r: URGENCY_ORDER[r["urgency"]])
