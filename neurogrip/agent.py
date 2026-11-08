"""Nemotron session agent: tool-calling loop that reviews a session and adapts difficulty."""
import json
import os
import re

from .protocol import fmt_buzzer, fmt_led

# Free endpoint on build.nvidia.com (tool calling + reasoning). Fallback: NEMOTRON_MODEL=nvidia/nemotron-3-super-120b-a12b
DEFAULT_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
# Model-card settings: temperature 1.0 / top_p 0.95 for all tasks; reasoning on, low effort (fast enough for a live
# demo). The reasoning trace comes back in message.reasoning_content and is shown in the dashboard tool trace.
NEMOTRON_KWARGS = {"temperature": 1.0, "top_p": 0.95,
                   "extra_body": {"chat_template_kwargs": {"enable_thinking": True, "low_effort": True}}}
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"

SYSTEM_PROMPT = """You are NeuroGrip's neurorehabilitation AI agent, working alongside a licensed therapist.
You have six tools:
1. get_session_metrics: current session reps, reaction latency ms, tremor Hz, gate activation rate %
   (the % of time the patient's intent was strong enough to move the robotic hand), session time.
2. get_patient_history: the patient's previous sessions from the database.
3. set_difficulty: sets the intent-detection threshold level (1 = easiest, 5 = hardest) for the next set.
4. trigger_feedback: sends an alert to the therapist dashboard and the patient's buzzer/LEDs.
5. get_open_incidents: what the live detection rules flagged (tremor, slow or missed reactions,
   finger-tap slowdown, sensor or camera faults) that is not resolved yet.
6. open_incident: escalate a concern to the clinic's incident board so a therapist owns it.

After each set of reps:
- Call get_session_metrics to see how the patient did.
- Call get_patient_history to compare against past sessions.
- Call get_open_incidents and take the live detections into account (mention them in the summary).
- Decide whether to make it harder, easier, or keep it the same, and call set_difficulty with your decision.
  Raise it when activation rate is above 80%; lower it when activation is below 40%; otherwise keep the same level.
- If any metric is declining versus past sessions (activation rate falling, latency or tremor rising),
  call trigger_feedback with kind "warning" and a short message naming the metric.
  Use "celebrate" for a clear improvement.
- If you find a real concern that is not already an open incident, call open_incident
  (severity "high" for a sharp decline, otherwise "medium").

Before EVERY tool call, write one short sentence explaining your reasoning.
Finish with ONLY a JSON object:
{"summary": "<exactly 3 sentences for the therapist: what happened, what changed, what to do next>",
 "next_session_plan": "<1 sentence>"}
Cite concrete numbers. Never diagnose; flag concerns for the therapist."""


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


FEEDBACK = {  # kind -> (buzzer Hz, buzzer ms, LED)
    "warning": (500, 600, "R"),
    "celebrate": (1200, 300, "G"),
}


class ToolBox:
    SCHEMAS = [
        _fn("get_session_metrics", "Live metrics for the current session: reps, gate activation rate %, "
            "session time, reaction latency, tremor Hz, steadiness, difficulty, mode."),
        _fn("get_patient_history", "Summaries of the patient's previous sessions, newest first.",
            {"limit": {"type": "integer", "minimum": 1, "maximum": 10}}),
        _fn("set_difficulty", "Set the intent-gate difficulty level for upcoming reps.",
            {"level": {"type": "integer", "minimum": 1, "maximum": 5}, "reason": {"type": "string"}},
            ["level", "reason"]),
        _fn("trigger_feedback", "Send an alert to the therapist dashboard and cue the patient through the buzzer and LEDs.",
            {"kind": {"type": "string", "enum": list(FEEDBACK)}, "message": {"type": "string"}},
            ["kind", "message"]),
        _fn("get_open_incidents", "Unresolved incidents from the live detection rules and responders, newest first."),
        _fn("open_incident", "Escalate a concern to the clinic incident board for a therapist to own.",
            {"title": {"type": "string"}, "severity": {"type": "string", "enum": ["low", "medium", "high"]},
             "detail": {"type": "string"}}, ["title", "severity", "detail"]),
    ]

    def __init__(self, engine, incidents=None):
        self.engine = engine
        self.incidents = incidents

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
        if kind not in FEEDBACK:
            return {"error": f"unknown feedback kind {kind}"}
        hz, ms, led = FEEDBACK[kind]
        self.engine.send(fmt_buzzer(hz, ms))
        self.engine.send(fmt_led(led))
        self.engine.post_event({"type": "agent_alert", "kind": kind, "message": message})
        return {"sent": kind, "message": message, "dashboard": True}

    def get_open_incidents(self) -> list[dict]:
        if self.incidents is None:
            return []
        rows = [i for i in self.incidents.list() if i["status"] != "resolved"][:10]
        keep = ("id", "title", "severity", "category", "status", "detail", "count", "scope")
        return [{k: i[k] for k in keep} for i in rows]

    def open_incident(self, title: str, severity: str = "medium", detail: str = "") -> dict:
        if self.incidents is None:
            return {"error": "incident board not connected"}
        if severity not in ("low", "medium", "high"):
            severity = "medium"
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40] or "flag"
        inc = self.incidents.raise_incident(f"agent:{slug}", str(title)[:120], severity, "clinical",
                                            {"patient": self.engine.patient_id}, str(detail)[:500],
                                            actor="Nemotron agent")
        return {"id": inc["id"], "status": inc["status"], "severity": inc["severity"]}

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


def _reasoning(msg) -> str:
    """The model's explanation before a tool call: its visible text, else its reasoning trace."""
    content = getattr(msg, "content", None) or ""
    visible = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    if visible:
        return visible
    trace = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
    if not trace:
        m = re.search(r"<think>(.*?)</think>", content, flags=re.S)
        trace = m.group(1) if m else ""
    trace = str(trace).strip()
    return trace if len(trace) <= 400 else trace[:400].rsplit(" ", 1)[0] + "..."


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


def run_agent(client, model: str, tools: ToolBox, max_steps: int = 8) -> dict:
    eng = tools.engine
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Patient {eng.patient_id}, condition mode: {eng.mode}. "
                                    "Review this session and plan the next one."},
    ]
    trace: list[dict] = []
    for _ in range(max_steps):
        resp = client.chat.completions.create(model=model, messages=messages, tools=ToolBox.SCHEMAS,
                                              tool_choice="auto", **NEMOTRON_KWARGS)
        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        if not calls:
            return {**_parse_final(msg.content), "trace": trace}
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
            for c in calls]})
        reasoning = _reasoning(msg)
        for i, c in enumerate(calls):
            args, result = tools.call(c.function.name, c.function.arguments)
            trace.append({"step": len(trace) + 1, "reasoning": reasoning if i == 0 else "",
                          "tool": c.function.name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, default=str)})
    return {"summary": f"Agent stopped at the step limit ({max_steps}) before writing a summary.",
            "next_session_plan": "", "trace": trace}
