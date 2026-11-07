"""Multi-patient AI triage: an LLM flags who needs urgent attention and why."""
import json
import re

URGENCY_ORDER = {"urgent": 0, "watch": 1, "stable": 2}

TRIAGE_PROMPT = """detailed thinking off
You triage a caseload of neuro-rehabilitation patients so no one is overlooked.
For EVERY patient decide urgency: "urgent" (needs therapist contact within 24h), "watch", or "stable".
Consider: falling gate activation trend, rising tremor frequency, slowing reaction latency, frequent compensation,
and long gaps since the last session. Give a one-sentence reason citing the numbers.
Reply with ONLY a JSON array: [{"patient_id": "...", "urgency": "...", "reason": "..."}]"""


def seed_demo_patients() -> list[dict]:
    rows = [
        ("P-101", "Avery M.", "stroke", 2, [42, 48, 55, 61, 66], 0.0, 820, 3),
        ("P-102", "Jordan K.", "parkinsons", 9, [70, 64, 55, 49, 41], 5.8, 910, 6),
        ("P-103", "Riley S.", "cp", 1, [35, 38, 40, 44, 47], 0.0, 1020, 5),
        ("P-104", "Morgan T.", "stroke", 14, [58, 51, 44, 38, 30], 0.0, 1180, 9),
        ("P-105", "Casey L.", "phantom", 3, [60, 62, 63, 65, 64], 0.0, 760, 1),
        ("P-106", "Quinn R.", "cognitive", 4, [72, 71, 70, 69, 70], 0.0, 1340, 2),
        ("P-107", "Taylor B.", "parkinsons", 2, [55, 56, 54, 57, 58], 4.6, 880, 2),
        ("P-108", "Drew P.", "stroke", 6, [50, 49, 47, 46, 44], 0.0, 990, 7),
        ("P-109", "Skyler N.", "cp", 1, [28, 33, 39, 45, 52], 0.0, 1100, 4),
        ("P-110", "Emerson H.", "cognitive", 21, [68, 66, 63, 59, 56], 0.0, 1520, 3),
    ]
    keys = ["patient_id", "name", "condition", "last_session_days_ago", "activation_rate_trend",
            "tremor_hz", "latency_ms_mean", "compensation_per_session"]
    return [dict(zip(keys, r)) for r in rows]


def _extract_json_array(text: str) -> list:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\[.*\]", text, flags=re.S)
    if not m:
        raise ValueError("model reply contained no JSON array")
    data = json.loads(m.group(0))
    if not isinstance(data, list):
        raise ValueError("model reply was not a JSON array")
    return data


def triage_patients(client, model: str, patients: list[dict]) -> list[dict]:
    resp = client.chat.completions.create(model=model, temperature=0.1, messages=[
        {"role": "system", "content": TRIAGE_PROMPT},
        {"role": "user", "content": json.dumps(patients)},
    ])
    verdicts = {}
    for v in _extract_json_array(resp.choices[0].message.content):
        if isinstance(v, dict) and v.get("urgency") in URGENCY_ORDER:
            verdicts[v.get("patient_id")] = v
    out = []
    for p in patients:
        v = verdicts.get(p["patient_id"], {"urgency": "watch", "reason": "not assessed by AI"})
        out.append({**p, "urgency": v["urgency"], "reason": str(v.get("reason", ""))})
    return sorted(out, key=lambda r: URGENCY_ORDER[r["urgency"]])
