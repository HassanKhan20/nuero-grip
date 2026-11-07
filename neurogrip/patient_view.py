"""Gemini: plain-language progress explanation for the patient (separate from Nemotron's clinical output)."""
import json
import os

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
KEEP = ("reps", "activation_rate", "compensation_count", "latency_ms_mean", "tremor_hz", "steadiness", "difficulty", "mode")

PROMPT = """You are a friendly rehab assistant explaining a patient's progress in simple language.
Explain in 2-3 sentences what they did today, whether they improved compared with last time, and one encouraging
thing to focus on next time. No medical jargon, no diagnosis, no numbers they wouldn't understand.
Talk like a supportive coach, speaking directly to them ("you").

What the numbers mean: reps = hand movements completed; activation_rate = % of the time their own effort was strong
enough to move the robotic hand (higher is better); compensation_count = times they leaned or lifted a shoulder
instead of using the hand (lower is better); latency_ms_mean = reaction time (lower is better);
steadiness = 0-100 (higher is steadier); difficulty = level 1-5.

Today's session: {today}
Last session: {previous}"""


def build_prompt(metrics: dict, previous: dict | None = None) -> str:
    today = {k: metrics.get(k) for k in KEEP}
    prev = {k: previous.get(k) for k in KEEP} if previous else "none (this is their first session)"
    return PROMPT.format(today=json.dumps(today), previous=json.dumps(prev) if previous else prev)


def explain_for_patient(metrics: dict, previous: dict | None = None) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    from google import genai

    client = genai.Client(api_key=key)
    resp = client.models.generate_content(model=os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
                                          contents=build_prompt(metrics, previous))
    return (resp.text or "").strip()
