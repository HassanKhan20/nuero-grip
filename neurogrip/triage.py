"""Multi-patient AI triage: an LLM flags who needs urgent attention and why."""
import json
import random
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


# --- Population triage: a surge of thousands of patients, scored by rule so no one is overlooked -----------------

REGIONS = ["North County", "Riverside", "Harbor District", "East Valley", "Old Town"]
# The surge is uneven: the hardest-hit districts have more patients and more of them cut off from care.
REGION_WEIGHTS = [16, 24, 30, 18, 12]
REGION_STALE = {"North County": 0.10, "Riverside": 0.20, "Harbor District": 0.28, "East Valley": 0.12,
                "Old Town": 0.07}  # chance a patient has missed 3+ days of sessions
CONDITION_WEIGHTS = {"stroke": 45, "parkinsons": 20, "cp": 10, "phantom": 10, "cognitive": 15}
FIRST = ["Alex", "Sam", "Jamie", "Rowan", "Noor", "Mateo", "Priya", "Kai", "Lena", "Omar", "Hana", "Luis",
         "Grace", "Wei", "Amara", "Theo", "Zara", "Ivan", "Mina", "Jonah"]
DEFAULT_THERAPISTS = {"Dr. Patel": 45, "Dr. Okafor": 45, "Dr. Nguyen": 45, "Dr. Silva": 45, "Dr. Romero": 45}
URGENT_SCORE, MONITOR_SCORE = 55, 20


def seed_population(n: int = 1200, seed: int = 7) -> list[dict]:
    """A deterministic synthetic caseload (e.g. a regional stroke surge after a disaster)."""
    rng = random.Random(seed)
    conds, weights = list(CONDITION_WEIGHTS), list(CONDITION_WEIGHTS.values())
    out = []
    for i in range(n):
        cond = rng.choices(conds, weights)[0]
        region = rng.choices(REGIONS, REGION_WEIGHTS)[0]
        stale = REGION_STALE[region]
        r = rng.random()
        days = rng.randint(0, 2) if r >= stale else rng.randint(3, 7) if r < stale * 0.65 else rng.randint(8, 21)
        start = rng.randint(25, 75)
        t = rng.random()
        drift = rng.uniform(2, 4) if t < 0.45 else rng.uniform(-0.5, 0.5) if t < 0.88 else rng.uniform(-5, -2)
        series = [max(0, min(100, round(start + drift * k + rng.uniform(-1.5, 1.5)))) for k in range(5)]
        tremor = round(rng.uniform(4.0, 6.5), 1) if cond == "parkinsons" and rng.random() < 0.8 else 0.0
        latency = max(450, int(rng.gauss(880 + (260 if cond == "cognitive" else 0), 170)))
        out.append({"patient_id": f"P-{2001 + i}", "name": f"{rng.choice(FIRST)} {chr(65 + rng.randrange(26))}.",
                    "condition": cond, "region": region, "last_session_days_ago": days,
                    "activation_rate_trend": series, "tremor_hz": tremor, "latency_ms_mean": latency,
                    "trend": trend_of(series)})
    return out


def risk_score(p: dict) -> tuple[int, list[str]]:
    """0-100 explainable risk: missed care, decline, low activation, tremor, slow reactions."""
    parts: list[tuple[float, str]] = []
    days = int(p.get("last_session_days_ago", 0))
    series = p.get("activation_rate_trend") or [0]
    if days >= STALE_DAYS:
        parts.append((min(days, 14) / 14 * 35, f"no session in {days} days"))
    else:
        parts.append((days * 2, ""))
    delta = series[-1] - series[0]
    if delta < 0:
        label = f"activation declining {series[0]}% → {series[-1]}%" if delta <= -TREND_DELTA else ""
        parts.append((min(-delta, 30) / 30 * 25, label))
    if series[-1] < 40:
        parts.append(((40 - series[-1]) / 40 * 15, f"low activation {series[-1]}%"))
    if p.get("tremor_hz"):
        parts.append((10, f"tremor {p['tremor_hz']} Hz"))
    lat = p.get("latency_ms_mean") or 0
    if lat > 1000:
        parts.append((min((lat - 1000) / 600, 1) * 15, f"slow reactions {lat} ms"))
    score = int(round(min(100, sum(w for w, _ in parts))))
    factors = [label for w, label in sorted(parts, key=lambda x: -x[0]) if label]
    return score, factors


def _tier(p: dict, score: int) -> str:
    if _rule_reason(p) or score >= URGENT_SCORE:
        return "urgent"
    if score >= MONITOR_SCORE or p.get("tremor_hz") or (p.get("latency_ms_mean") or 0) > 1000:
        return "monitor"
    return "stable"


def triage_population(patients: list[dict], therapists: dict[str, int]) -> dict:
    """Score and tier every patient, then give therapists to the most at-risk first, up to capacity."""
    rows = []
    for p in patients:
        p = {**p, "trend": p.get("trend") or trend_of(p["activation_rate_trend"])}
        score, factors = risk_score(p)
        urgency = _tier(p, score)
        if factors:
            reason = "; ".join(factors[:2])
            reason = reason[0].upper() + reason[1:] + "."
        else:
            reason = f"On track: activation {p['activation_rate_trend'][-1]}%, seen {p['last_session_days_ago']} d ago."
        rows.append({**p, "risk": score, "factors": factors, "urgency": urgency, "reason": reason,
                     "assigned_to": None})
    rows.sort(key=lambda r: (URGENCY_ORDER[r["urgency"]], -r["risk"], r["patient_id"]))

    order = list(therapists)
    load = {name: 0 for name in therapists}
    for r in rows:
        if r["urgency"] == "stable":
            continue
        free = [n for n in order if load[n] < therapists[n]]
        if not free:
            break
        name = min(free, key=lambda n: (load[n] / max(1, therapists[n]), order.index(n)))
        r["assigned_to"] = name
        load[name] += 1
    for r in rows:
        r["care"] = "therapist" if r["assigned_to"] else ("home program" if r["urgency"] == "stable" else "waitlist")

    count = {u: sum(1 for r in rows if r["urgency"] == u) for u in URGENCY_ORDER}
    by_region: dict[str, dict] = {}
    for r in rows:
        reg = by_region.setdefault(r.get("region", "Unknown"), {"total": 0, "urgent": 0, "waitlist": 0})
        reg["total"] += 1
        reg["urgent"] += r["urgency"] == "urgent"
        reg["waitlist"] += r["care"] == "waitlist"
    unassigned_urgent = sum(1 for r in rows if r["urgency"] == "urgent" and not r["assigned_to"])
    summary = {"total": len(rows), **count, "assigned": sum(load.values()),
               "capacity": sum(therapists.values()), "unassigned_urgent": unassigned_urgent,
               "unassigned_monitor": sum(1 for r in rows if r["urgency"] == "monitor" and not r["assigned_to"]),
               "urgent_coverage_pct": round(100 * (count["urgent"] - unassigned_urgent) / count["urgent"], 1)
               if count["urgent"] else 100.0,
               "by_region": by_region}
    return {"summary": summary, "patients": rows,
            "therapists": [{"name": n, "capacity": c, "assigned": load[n]} for n, c in therapists.items()]}


BRIEF_PROMPT = """You are the coordination AI for a neuro-rehabilitation network during a patient surge.
Every patient has already been scored by rule; you see the totals, therapist capacity and the highest-risk patients.
Reply with ONLY a JSON object:
{"brief": "<3-4 sentences for the clinical lead: how big the gap is, which regions need help, and a concrete plan
 for patients on the waitlist (tele-rehab check-ins, group sessions, home-kit pushes). Cite numbers.>",
 "reasons": {"<patient_id>": "<one sentence why this patient is at the top, citing their numbers>"}}
Never diagnose; flag concerns for clinicians."""


def ai_brief(client, model: str, result: dict, top: int = 12) -> dict:
    """Nemotron reads the summary plus the top slice and writes the coordination plan."""
    keep = ("patient_id", "name", "condition", "region", "last_session_days_ago", "activation_rate_trend",
            "tremor_hz", "latency_ms_mean", "risk", "factors", "urgency", "care")
    head = [{k: r[k] for k in keep if k in r} for r in result["patients"][:top]]
    payload = {"summary": result["summary"], "therapists": result["therapists"], "top_patients": head}
    resp = client.chat.completions.create(model=model, **NEMOTRON_KWARGS, messages=[
        {"role": "system", "content": BRIEF_PROMPT},
        {"role": "user", "content": json.dumps(payload)},
    ])
    text = re.sub(r"<think>.*?</think>", "", resp.choices[0].message.content or "", flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    ids = {r["patient_id"] for r in head}
    reasons = {k: str(v) for k, v in (data.get("reasons") or {}).items() if k in ids}
    return {"brief": str(data.get("brief") or text.strip())[:1200], "reasons": reasons}
