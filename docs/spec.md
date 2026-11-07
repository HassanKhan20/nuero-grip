# NeuroGrip — Build Spec (hackathon cut)

## What it is
Motor-intent rehab platform. Capacitive headband (ESP32 touch, temple + forearm) + accelerometer wristband + webcam tracking the healthy hand. A gating engine drives proportional per-finger servos on the impaired hand **only when** intent is confirmed (both sites), posture is clean (no compensation), and the healthy hand has set a target. A Nemotron agent analyzes sessions and adapts difficulty. A Flask dashboard shows everything live.

Conditions (mode selector = header text + highlighted metrics only, no separate logic): stroke, parkinson's, phantom limb, pediatric CP, cognitive screening.

## Tracks
- Overall (auto)
- NVIDIA: Nemotron agent with tool calls (`get_session_metrics`, `get_patient_history`, `set_difficulty`, `trigger_feedback`). **Tool-call trace visible on the dashboard.**
- Winstead PC: dashboard as incident command center — hardcoded therapist/patient logins with different views, timestamped compensation/threshold event log, live updating. Text messaging only if time remains.
- State Farm: multi-patient triage panel where **an LLM flags urgent patients with a reason**.
- MLH: MongoDB Atlas (session storage), Vultr (static dashboard deploy), GoDaddy (domain), Gemini (plain-language patient view).

## Must-haves (agreed)
1. Mock sensor mode — one flag replays synthetic data so the full dashboard works with no hardware.
2. Separate 5V supply for servos (hardware, not code).
3. Firmware safety: no servo command for 500 ms → all servos to neutral.
4. "Bilateral symmetry" is replaced by **intent gate activation rate**: % of frames with a target set where the gate was open.
5. Cognitive latency uses a cue (buzzer beep + LED) and times until intent fires.
6. Nemotron trace box on the dashboard.
7. State Farm AI flag call.

## Out of scope
Local/cloud split, hashed passwords, per-condition logic, wiring diagrams, therapist notes, overlooked-patient alerts.
