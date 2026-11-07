"""Gemini: plain-language progress explanation for the patient."""
import json
import os

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def explain_for_patient(metrics: dict, clinical_summary: str) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    from google import genai

    keep = ("reps", "activation_rate", "compensation_count", "latency_ms_mean", "tremor_hz", "steadiness", "difficulty", "mode")
    prompt = (
        "You are encouraging a rehabilitation patient. In at most 80 words, at an 8th-grade reading level, "
        "explain how today's hand-therapy session went and one thing to focus on next. "
        "'activation_rate' is the % of attempts where their effort was strong enough to move the robotic hand. "
        "No medical jargon, no diagnosis.\n"
        f"Session numbers: {json.dumps({k: metrics.get(k) for k in keep})}\n"
        f"Therapist notes: {clinical_summary or 'none yet'}"
    )
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(model=os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL), contents=prompt)
    return (resp.text or "").strip()
