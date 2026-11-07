"""Nemotron session agent: tool-calling loop that reviews a session and adapts difficulty."""
import json
import os
import re

from .protocol import fmt_buzzer, fmt_led

DEFAULT_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"

SYSTEM_PROMPT = """detailed thinking off
You are NeuroGrip's rehabilitation session agent working alongside a licensed therapist.
Work in steps using the tools:
1. Call get_session_metrics to read the current session.
2. Call get_patient_history to compare against earlier sessions.
3. Decide the next difficulty level (1 = easiest intent threshold, 5 = hardest) and call set_difficulty with a short reason.
   Raise difficulty when gate activation rate is high (>80%) with few compensation events; lower it when activation is low (<40%) or compensation is frequent.
4. Optionally call trigger_feedback ("celebrate" or "correct_posture") to cue the patient.
5. Finish with ONLY a JSON object: {"summary": "<3-4 sentence clinical summary for the therapist>", "next_session_plan": "<1-2 sentences>"}.
Reference concrete numbers. Do not diagnose; flag concerns for the therapist."""


def make_nvidia_client():
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        return None
    from openai import OpenAI

    return OpenAI(base_url=os.environ.get("NVIDIA_BASE_URL", DEFAULT_BASE_URL), api_key=key,
                  timeout=45, max_retries=1)


def nemotron_model() -> str:
    return os.environ.get("NEMOTRON_MODEL", DEFAULT_MODEL)


def _fn(name, description, props=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


class ToolBox:
    SCHEMAS = [
        _fn("get_session_metrics", "Live metrics for the current session: reps, gate activation rate %, "
            "compensation events, reaction latency, tremor Hz, steadiness, difficulty, mode."),
        _fn("get_patient_history", "Summaries of the patient's previous sessions, newest first.",
            {"limit": {"type": "integer", "minimum": 1, "maximum": 10}}),
        _fn("set_difficulty", "Set the intent-gate difficulty level for upcoming reps.",
            {"level": {"type": "integer", "minimum": 1, "maximum": 5}, "reason": {"type": "string"}},
            ["level", "reason"]),
        _fn("trigger_feedback", "Cue the patient through the buzzer and LEDs.",
            {"kind": {"type": "string", "enum": ["celebrate", "correct_posture"]}, "message": {"type": "string"}},
            ["kind"]),
    ]

    def __init__(self, engine):
        self.engine = engine

    def get_session_metrics(self) -> dict:
        s = self.engine.state()
        s["events"] = s["events"][-10:]
        return s

    def get_patient_history(self, limit: int = 5) -> list[dict]:
        hist = self.engine.store.history(self.engine.patient_id, max(1, min(10, int(limit))))
        return [{k: v for k, v in h.items() if k not in ("events", "_id")} for h in hist]

    def set_difficulty(self, level: int, reason: str = "") -> dict:
        level = self.engine.set_difficulty(level)
        return {"level": level, "threshold": self.engine.intent.threshold, "reason": reason}

    def trigger_feedback(self, kind: str, message: str = "") -> dict:
        if kind == "celebrate":
            cmds = [fmt_buzzer(1200, 300), fmt_led("G")]
        elif kind == "correct_posture":
            cmds = [fmt_buzzer(300, 400), fmt_led("R")]
        else:
            return {"error": f"unknown feedback kind {kind}"}
        for c in cmds:
            self.engine.send(c)
        return {"sent": kind, "message": message}

    def call(self, name: str, arguments: str) -> tuple[dict, object]:
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError:
            args = {}
        if name not in {s["function"]["name"] for s in self.SCHEMAS}:
            return args, {"error": f"unknown tool {name}"}
        try:
            return args, getattr(self, name)(**args)
        except Exception as e:  # report tool failures back to the model instead of crashing the loop
            return args, {"error": f"{type(e).__name__}: {e}"}


def _parse_final(content: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S).strip()
    unfenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        data = json.loads(unfenced)
        if isinstance(data, dict) and "summary" in data:
            return {"summary": str(data["summary"]), "next_session_plan": str(data.get("next_session_plan", ""))}
    except json.JSONDecodeError:
        pass
    return {"summary": text, "next_session_plan": ""}


def run_agent(client, model: str, tools: ToolBox, max_steps: int = 6) -> dict:
    eng = tools.engine
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Patient {eng.patient_id}, condition mode: {eng.mode}. "
                                    "Review this session and plan the next one."},
    ]
    trace: list[dict] = []
    for _ in range(max_steps):
        resp = client.chat.completions.create(model=model, messages=messages, tools=ToolBox.SCHEMAS,
                                              tool_choice="auto", temperature=0.2)
        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        if not calls:
            return {**_parse_final(msg.content), "trace": trace}
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
            for c in calls]})
        for c in calls:
            args, result = tools.call(c.function.name, c.function.arguments)
            trace.append({"step": len(trace) + 1, "tool": c.function.name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, default=str)})
    return {"summary": f"Agent stopped at the step limit ({max_steps}) before writing a summary.",
            "next_session_plan": "", "trace": trace}
