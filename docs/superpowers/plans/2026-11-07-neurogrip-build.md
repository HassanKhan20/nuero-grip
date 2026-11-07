# NeuroGrip Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working demo: ESP32 firmware + Python gating engine (real or mock sensors) + live Flask dashboard with Nemotron agent trace, AI triage, Gemini patient view, MongoDB storage.

**Architecture:** Everything runs on one laptop. A background engine thread reads sensor frames (serial or mock) at 50 Hz, combines them with the latest vision result (MediaPipe or mock), runs the gate, sends servo/LED/buzzer commands, and updates session metrics. Flask-SocketIO pushes state to the browser at 10 Hz. LLM features are request-driven HTTP endpoints.

**Tech Stack:** Python 3.10 (venv), numpy, pyserial, opencv-python, mediapipe, flask, flask-socketio, pymongo, openai (NVIDIA OpenAI-compatible endpoint), google-genai, pytest. Arduino C++ for ESP32 (ESP32Servo library).

**Spec:** `docs/spec.md`

## Global Constraints

- Python 3.10 venv at `.venv` (`py -3.10 -m venv .venv`); mediapipe does not support 3.14.
- Serial: 115200 baud, newline-terminated ASCII lines.
- ESP32 → host, 50 Hz: `S,<ms>,<temple>,<forearm>,<ax_mg>,<ay_mg>,<az_mg>`
- Host → ESP32: `A,<thumb>,<index>,<rest>` (int degrees 0–160), `B,<hz>,<ms>`, `L,<G|R|O>`
- Firmware clamps servo angles to 0–160 and returns all servos to 0 (neutral/open) if no `A` line for 500 ms.
- Env config: `NG_MOCK=1` (mock sensors+vision), `NG_SERIAL_PORT` (e.g. `COM5`), `NG_CAMERA` (default `0`), `MONGODB_URI` (absent → in-memory store), `NVIDIA_API_KEY`, `NEMOTRON_MODEL` (default `nvidia/llama-3.3-nemotron-super-49b-v1.5`), `NVIDIA_BASE_URL` (default `https://integrate.api.nvidia.com/v1`), `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-2.5-flash`).
- Logins hardcoded: `therapist/therapist`, `patient/patient`.
- Modes: `stroke`, `parkinsons`, `phantom`, `cp`, `cognitive`.
- Difficulty level 1–5 → intent threshold `[0.08, 0.11, 0.14, 0.17, 0.20][level-1]`.

## Review Focus

1. Serial line garbage / partial lines on connect → parser returns `None`, engine keeps running (Task 1 test `test_parse_garbage_returns_none`).
2. Hand leaves camera frame → curls are `None`, target not set, gate closed, servos hold (Task 4 test `test_gate_closed_without_hand`).
3. LLM returns non-JSON or no tool calls → agent still returns a summary string and the trace (Task 6 test `test_agent_plain_text_final`).
4. Agent asks for difficulty 9 → clamped to 5 (Task 6 test `test_set_difficulty_clamped`).
5. Missing API key / Mongo URI → endpoint returns JSON `{"error": ...}` with 503, dashboard shows it, engine unaffected (Task 8 test `test_agent_endpoint_without_key`).

---

### Task 1: Project setup + serial protocol

**Files:**
- Create: `requirements.txt`, `.gitignore`, `neurogrip/__init__.py`, `neurogrip/protocol.py`, `tests/test_protocol.py`

**Interfaces:**
- Produces:
  - `@dataclass SensorFrame(ms:int, temple:int, forearm:int, ax:int, ay:int, az:int)`
  - `parse_sensor_line(line: str) -> SensorFrame | None`
  - `fmt_servo(thumb:int, index:int, rest:int) -> str` (clamps 0–160, ends `\n`)
  - `fmt_buzzer(hz:int, ms:int) -> str`, `fmt_led(state: str) -> str` (state in `G`,`R`,`O`)

- [ ] **Step 1:** `py -3.10 -m venv .venv`; requirements: `numpy pyserial opencv-python mediapipe flask flask-socketio pymongo openai google-genai pytest`; `.gitignore` has `.venv/ __pycache__/ .env`. Install.
- [ ] **Step 2: Tests**

```python
def test_parse_valid():
    f = parse_sensor_line("S,1200,410,395,12,-8,1003\n")
    assert f == SensorFrame(1200, 410, 395, 12, -8, 1003)
def test_parse_garbage_returns_none():
    for bad in ["", "S,1,2", "X,1,2,3,4,5,6", "S,a,b,c,d,e,f", "\x00\xffS,1"]:
        assert parse_sensor_line(bad) is None
def test_fmt_servo_clamps():
    assert fmt_servo(-5, 90, 200) == "A,0,90,160\n"
def test_fmt_led_and_buzzer():
    assert fmt_led("G") == "L,G\n" and fmt_buzzer(880, 120) == "B,880,120\n"
```

- [ ] **Step 3:** Run `.venv\Scripts\python -m pytest tests/test_protocol.py -v` → FAIL; implement; → PASS.
- [ ] **Step 4:** Commit `feat: serial protocol`.

### Task 2: Sensor sources + intent detection + accelerometer signals

**Files:**
- Create: `neurogrip/sources.py`, `neurogrip/intent.py`, `neurogrip/signals.py`, `tests/test_intent.py`, `tests/test_signals.py`

**Interfaces:**
- Consumes: `SensorFrame`, `parse_sensor_line`, `fmt_*` (Task 1)
- Produces:
  - `class MockSource(tremor_hz: float = 0.0, seed: int = 0)` with `read() -> SensorFrame` (one frame per call, ms advancing by 20) and `send(cmd: str) -> None` (stores in `self.sent: list[str]`). Touch baseline ~400; alternates 3 s rest / 3 s intent where both sites drop ~30%. Accel: 1000 mg on z plus `tremor_hz` sine of amplitude 60 mg plus small noise.
  - `class SerialSource(port: str, baud: int = 115200)` with same `read()` (blocking until a valid line) and `send(cmd)`.
  - `class IntentDetector(threshold: float = 0.14, calib_frames: int = 100)` with `update(f: SensorFrame) -> IntentState`, attribute `threshold` settable; `@dataclass IntentState(calibrated: bool, active: bool, strength: float, temple_drop: float, forearm_drop: float)`. Baseline = median of first `calib_frames` frames per site. drop = `abs(baseline - value) / baseline` (works whether the board's touch reading falls or rises). active = both drops ≥ threshold. strength = `clamp(min(drops) / (2*threshold), 0, 1)`. Not calibrated → active False.
  - `tremor_frequency(mag_mg: np.ndarray, fs: float = 50.0) -> float` — detrend, Hann window, rFFT, peak in 3–12 Hz; return 0.0 if detrended RMS < 15 mg.
  - `steadiness(mag_mg: np.ndarray) -> float` — `max(0, 100 - rms_detrended/2)`, rounded to 1 decimal.

- [ ] **Step 1: Tests**

```python
def test_intent_needs_calibration():
    d = IntentDetector(calib_frames=10)
    assert not d.update(SensorFrame(0, 400, 400, 0, 0, 1000)).calibrated
def test_intent_dual_site_required():
    d = IntentDetector(threshold=0.14, calib_frames=10)
    for i in range(10): d.update(SensorFrame(i, 400, 400, 0, 0, 1000))
    assert not d.update(SensorFrame(11, 300, 400, 0, 0, 1000)).active   # temple only
    s = d.update(SensorFrame(12, 300, 300, 0, 0, 1000))
    assert s.active and 0.5 < s.strength <= 1.0
def test_tremor_frequency_detects_5hz():
    t = np.arange(256) / 50
    assert abs(tremor_frequency(1000 + 60*np.sin(2*np.pi*5*t)) - 5.0) < 0.4
def test_tremor_zero_when_still():
    assert tremor_frequency(np.full(256, 1000.0)) == 0.0
def test_mock_source_produces_intent():
    src, d = MockSource(seed=1), IntentDetector()
    states = [d.update(src.read()) for _ in range(500)]
    assert any(s.active for s in states) and not all(s.active for s in states[100:])
```

- [ ] **Step 2:** Run → FAIL; implement; run `pytest tests -v` → PASS.
- [ ] **Step 3:** Commit `feat: sensor sources, intent detector, tremor`.

### Task 3: Vision (hand curls + compensation)

**Files:**
- Create: `neurogrip/vision.py`, `tests/test_vision.py`

**Interfaces:**
- Produces:
  - `finger_curls(lm: list[tuple[float, float]]) -> dict[str, float]` — 21 MediaPipe hand landmarks (x, y) → `{"thumb", "index", "rest"}` each 0–1. Non-thumb finger: `r = dist(tip, wrist) / dist(mcp, wrist)`, `curl = clamp((2.0 - r) / 1.0, 0, 1)`. Thumb: `r = dist(4, 17) / dist(0, 9)`, `curl = clamp((1.3 - r) / 0.7, 0, 1)`. `rest` = mean of middle (9→12), ring (13→16), pinky (17→20). Constants at module top as `OPEN_RATIO`, etc. for tuning.
  - `class CompensationDetector(calib_frames: int = 60, hike: float = 0.04, lean: float = 0.05)` with `update(pose: dict[str, tuple[float,float]] | None) -> list[str]` — pose keys `l_sh`, `r_sh`. Baseline = mean of first frames. Returns `["shoulder_hike"]` if either shoulder y < baseline y − hike, `["trunk_lean"]` if shoulder-midpoint x moved > lean; both possible; `[]` while calibrating or pose None.
  - `@dataclass VisionResult(curls: dict[str, float] | None, compensation: list[str])`
  - `class MockVision(seed: int = 0)` with `latest() -> VisionResult` — curls follow a slow 0→1→0 sine (period 4 s); `compensation` = `["shoulder_hike"]` for 1 s out of every 15 s.
  - `class CameraVision(camera_index: int)` with `start()`, `latest() -> VisionResult`, `stop()` — own thread; MediaPipe Hands (max 1 hand) + Pose on each frame; keeps the latest result.

- [ ] **Step 1: Tests** (build synthetic landmark lists: open hand with tips at 2× MCP distance from wrist; fist with tips at 1×)

```python
def test_open_hand_curls_low(): assert all(v < 0.1 for v in finger_curls(OPEN).values())
def test_fist_curls_high(): assert finger_curls(FIST)["index"] > 0.9 and finger_curls(FIST)["rest"] > 0.9
def test_shoulder_hike_detected():
    c = CompensationDetector(calib_frames=5)
    for _ in range(5): c.update({"l_sh": (0.4, 0.5), "r_sh": (0.6, 0.5)})
    assert c.update({"l_sh": (0.4, 0.44), "r_sh": (0.6, 0.5)}) == ["shoulder_hike"]
def test_no_pose_no_compensation():
    assert CompensationDetector(calib_frames=0).update(None) == []
```

- [ ] **Step 2:** Run → FAIL; implement (CameraVision is not unit-tested); → PASS.
- [ ] **Step 3:** Manual check: `.venv\Scripts\python -m neurogrip.vision` prints curls from webcam (add `if __name__ == "__main__"` loop).
- [ ] **Step 4:** Commit `feat: vision curls and compensation`.

### Task 4: Gate + session metrics

**Files:**
- Create: `neurogrip/gate.py`, `neurogrip/metrics.py`, `tests/test_gate.py`, `tests/test_metrics.py`

**Interfaces:**
- Consumes: `IntentState` (Task 2), `VisionResult` (Task 3)
- Produces:
  - `THRESHOLDS = [0.08, 0.11, 0.14, 0.17, 0.20]`
  - `@dataclass GateOutput(open: bool, target_set: bool, angles: tuple[int,int,int], led: str, buzzer_hz: int)`
  - `class Gate` with `step(intent: IntentState, vision: VisionResult) -> GateOutput`. target_set = curls not None and max curl ≥ 0.1. open = intent.active and not compensation and target_set. Open → angles = round(curl × 160) per finger (thumb, index, rest); closed → hold previous angles (start 0,0,0). led: `R` if compensation else `G` if open else `O`. buzzer_hz = `400 + int(800 × strength)` if intent.active else 0.
  - `class SessionMetrics` with `update(t_ms: int, intent: IntentState, vision: VisionResult, gate: GateOutput) -> list[dict]` (returns new events) and `snapshot() -> dict`. Tracks: reps (gate open and max curl ≥ 0.6, then max curl ≤ 0.3), activation_rate % (open frames / target_set frames), compensation events on rising edge per type → event `{"t": ms, "type": "shoulder_hike"|"trunk_lean"}`, and latency trials. Snapshot keys: `reps, activation_rate, compensation_count, events (last 50), latency_ms_mean, latency_trials, tremor_hz, steadiness, difficulty`.
  - `SessionMetrics.start_latency_trial(cue_ms: int)`; first `intent.active` rising edge after cue → latency `ms - cue_ms`, event `{"type": "latency", "ms": ...}`; none within 3000 ms → event `{"type": "latency_miss"}`.

- [ ] **Step 1: Tests**

```python
def test_gate_closed_without_hand():
    g = Gate(); out = g.step(ACTIVE, VisionResult(None, []))
    assert not out.open and out.angles == (0, 0, 0)
def test_gate_open_proportional():
    out = Gate().step(ACTIVE, VisionResult({"thumb": 0.5, "index": 1.0, "rest": 0.25}, []))
    assert out.open and out.angles == (80, 160, 40) and out.led == "G"
def test_gate_blocked_by_compensation_holds_angles():
    g = Gate(); g.step(ACTIVE, VisionResult({"thumb": .5, "index": .5, "rest": .5}, []))
    out = g.step(ACTIVE, VisionResult({"thumb": 1, "index": 1, "rest": 1}, ["trunk_lean"]))
    assert not out.open and out.angles == (80, 80, 80) and out.led == "R"
def test_rep_counted_with_hysteresis(): ...  # curl 0.0→0.7→0.2 while open → reps == 1; 0.7→0.5→0.7 → still 1
def test_activation_rate(): ...  # 3 open + 1 closed target_set frames → 75.0
def test_latency_trial(): ...  # cue at 1000, active at 1350 → latency_ms_mean == 350
def test_compensation_event_on_rising_edge_only(): ...  # 5 frames of hike → 1 event
```

- [ ] **Step 2:** Run → FAIL; implement; → PASS.
- [ ] **Step 3:** Commit `feat: gate and session metrics`.

### Task 5: Engine loop + store

**Files:**
- Create: `neurogrip/engine.py`, `neurogrip/store.py`, `tests/test_engine.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `class MemoryStore` and `class MongoStore(uri: str)` with identical methods: `save_session(doc: dict) -> str`, `history(patient_id: str, limit: int = 5) -> list[dict]` (newest first), `log_event(doc: dict) -> None`, `patients() -> list[dict]`, `upsert_patient(doc: dict) -> None`. `make_store() -> MemoryStore | MongoStore` (by `MONGODB_URI`, db `neurogrip`).
  - `class Engine(source, vision, store, patient_id: str = "demo")` with `step() -> dict` (one frame: read → intent → vision.latest() → gate → metrics → send `A`, and `L`/`B` only when changed; every 25 frames updates tremor/steadiness from last 256 accel magnitudes), `state() -> dict` (metrics snapshot + live `angles, gate_open, intent_strength, curls, led, mode`), `set_difficulty(level: int) -> int` (clamp 1–5, sets detector threshold), `cue_latency()` (sends `B,1500,150` and `L,G`, starts trial), `set_mode(mode: str)`, `end_session() -> str` (saves snapshot to store, resets metrics), `run_forever(stop: threading.Event)`. Events from metrics are logged to the store with `patient_id`.
  - `make_engine() -> Engine` — Mock source/vision if `NG_MOCK=1`, else `SerialSource(NG_SERIAL_PORT)` + `CameraVision(NG_CAMERA)`.

- [ ] **Step 1: Tests** — `test_engine_mock_runs`: Engine(MockSource(tremor_hz=5), MockVision(), MemoryStore()); 600 steps; assert `state()["reps"] >= 1`, some `A,` lines in `source.sent`, `abs(state()["tremor_hz"] - 5) < 0.6`. `test_set_difficulty_clamps`: `set_difficulty(9) == 5` and detector threshold 0.20. `test_end_session_persists`: after steps, `end_session()` then `store.history("demo")` has 1 doc with key `reps`.
- [ ] **Step 2:** Run → FAIL; implement; → PASS.
- [ ] **Step 3:** Commit `feat: engine loop and store`.

### Task 6: Nemotron agent with trace

**Files:**
- Create: `neurogrip/agent.py`, `tests/test_agent.py`

**Interfaces:**
- Consumes: `Engine` (Task 5), store.
- Produces:
  - `make_nvidia_client() -> openai.OpenAI | None` (None if no `NVIDIA_API_KEY`).
  - `class ToolBox(engine)` with `get_session_metrics() -> dict`, `get_patient_history(limit: int = 5) -> list[dict]`, `set_difficulty(level: int, reason: str) -> dict` (returns `{"level": clamped, "threshold": ...}`), `trigger_feedback(kind: str, message: str) -> dict` (kind `celebrate` → `B,1200,300`+`L,G`; `correct_posture` → `B,300,400`+`L,R`), and `SCHEMAS: list[dict]` (OpenAI tool schemas for the four).
  - `run_agent(client, model: str, tools: ToolBox, max_steps: int = 6) -> dict` → `{"summary": str, "next_session_plan": str, "trace": list[dict]}`. Loop: send messages + tools; for each tool call execute, append `{"step", "tool", "args", "result"}` to trace and a `tool` message; stop when the model replies without tool calls. Final content parsed as JSON `{summary, next_session_plan}`; if not JSON, `summary = content`, plan `""`. System prompt tells it to: 1) get metrics, 2) get history, 3) decide and call set_difficulty, 4) optionally trigger_feedback, 5) reply with JSON only.

- [ ] **Step 1: Tests** with a `FakeClient` whose `chat.completions.create` returns scripted responses (SimpleNamespace shaped like OpenAI objects):
  - `test_agent_runs_tool_loop`: script = [call get_session_metrics, call set_difficulty(level=4), final JSON] → trace tools `["get_session_metrics", "set_difficulty"]`, engine difficulty 4, summary from JSON.
  - `test_agent_plain_text_final`: script = ["Patient improved."] → summary "Patient improved.", trace `[]`.
  - `test_set_difficulty_clamped`: `ToolBox(engine).set_difficulty(9, "x")["level"] == 5`.
  - `test_agent_stops_at_max_steps`: model always calls a tool → returns after 6 steps with summary noting the limit.
- [ ] **Step 2:** Run → FAIL; implement; → PASS.
- [ ] **Step 3:** Commit `feat: nemotron agent with tool trace`.

### Task 7: AI triage (State Farm) + Gemini patient view

**Files:**
- Create: `neurogrip/triage.py`, `neurogrip/patient_view.py`, `tests/test_triage.py`

**Interfaces:**
- Produces:
  - `seed_demo_patients() -> list[dict]` — 10 fixed patients `{patient_id, name, condition, last_session_days_ago, activation_rate_trend: [5 floats], tremor_hz, latency_ms_mean, compensation_per_session}`; at least 2 clearly deteriorating.
  - `triage_patients(client, model: str, patients: list[dict]) -> list[dict]` — one Nemotron call asking for JSON array `[{patient_id, urgency: "urgent"|"watch"|"stable", reason}]`; strips code fences; unknown ids dropped; patients missing from the reply are added as `{"urgency": "watch", "reason": "not assessed by AI"}`; sorted urgent → watch → stable.
  - `explain_for_patient(metrics: dict, clinical_summary: str) -> str` — Gemini via `google.genai.Client(api_key=GEMINI_API_KEY).models.generate_content`, ≤ 80 words, encouraging, 8th-grade reading level. Raises `RuntimeError("GEMINI_API_KEY not set")` when missing.
- [ ] **Step 1: Tests:** `test_triage_parses_and_sorts` (fake reply in ```json fences, out-of-order) → urgent first; `test_triage_fills_missing_patients` → all 10 present.
- [ ] **Step 2:** Run → FAIL; implement; → PASS.
- [ ] **Step 3:** Commit `feat: ai triage and gemini patient view`.

### Task 8: Flask dashboard

**Files:**
- Create: `app.py`, `templates/login.html`, `templates/dashboard.html`, `static/dashboard.js`, `static/style.css`, `tests/test_app.py`

**Interfaces:**
- Consumes: `make_engine`, `ToolBox`, `run_agent`, `make_nvidia_client`, `triage_patients`, `seed_demo_patients`, `explain_for_patient`.
- Produces routes: `GET/POST /login`, `GET /logout`, `GET /` (dashboard; role in session), `POST /api/mode {mode}`, `POST /api/difficulty {level}` (therapist), `POST /api/latency` , `POST /api/session/end` (therapist), `POST /api/agent` → `run_agent` result (therapist), `GET /api/triage` (therapist), `POST /api/patient_view` → `{"text"}`. All LLM endpoints return `{"error": msg}` with 503 when the client/key is missing and 502 on upstream exceptions. Non-therapist on therapist endpoints → 403. SocketIO emits `state` (engine.state()) every 100 ms and `event` per new metrics event.
- Dashboard: header shows mode name; tiles: grip angles (3 bars), gate status, intent strength, tremor Hz, steadiness, latency, activation rate, reps, difficulty; event log (timestamped, newest first); reps sparkline; mode selector (highlights a per-mode set of tiles); therapist-only: difficulty control, "Run AI agent" button → summary + plan + **trace box** listing each tool call/args/result, triage panel (urgency badge + reason), end session. Patient view: big angle bars, reps, "Explain my progress" (Gemini).
- [ ] **Step 1: Tests** (Flask test client, `NG_MOCK=1`, engine not started): login wrong password stays on login; patient gets 403 on `/api/agent`; therapist `/api/agent` with no `NVIDIA_API_KEY` → 503 JSON (`test_agent_endpoint_without_key`).
- [ ] **Step 2:** Run → FAIL; implement; → PASS.
- [ ] **Step 3:** Manual: `$env:NG_MOCK=1; .venv\Scripts\python app.py`, open http://localhost:5000, log in as therapist: tiles move, events appear, mode switch changes header.
- [ ] **Step 4:** Commit `feat: live dashboard`.

### Task 9: ESP32 firmware

**Files:**
- Create: `firmware/neurogrip_esp32/neurogrip_esp32.ino`, `firmware/README.md`

**Interfaces:** Implements the serial protocol in Global Constraints.
- Pins (classic ESP32 DevKit, edit at top): touch temple `T0`/GPIO4, forearm `T3`/GPIO15; servos thumb GPIO13, index GPIO12, rest GPIO14; buzzer GPIO25; LED green GPIO26, red GPIO27; accelerometer ADXL345 (Grove 3-Axis ±16g) I2C SDA21/SCL22, addr 0x53, full-resolution mode, values → mg (×3.9).
- Loop: every 20 ms send `S` line; parse incoming lines non-blocking; `A` → clamp 0–160, write servos, record time; `B` → `tone(pin, hz, ms)`; `L` → set LEDs; watchdog: `millis() - lastA > 500` → write 0 to all servos.
- README: wiring table, separate 5V servo supply with common ground, Arduino IDE board "ESP32 Dev Module", library ESP32Servo.
- [ ] **Step 1:** Write the sketch; verify by reading through against the protocol (no `arduino-cli` on this machine). Flash with Arduino IDE when hardware is available; check with Serial Monitor that `S,` lines stream and servos go to 0 within 0.5 s of closing the host.
- [ ] **Step 2:** Commit `feat: esp32 firmware`.

### Task 10 (only if time remains): Winstead messaging + deploy notes

- Therapist→patient text messages over SocketIO (`message` event, shown as a banner on the patient view and logged as an event).
- `docs/deploy.md`: Vultr static deploy (mock mode) + GoDaddy DNS A record.
