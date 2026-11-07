# NeuroGrip: team progress

_Last updated: 2026-11-07_

## Where we are

**The software runs end to end without hardware.** Mock mode simulates the headband, the wristband and the hand. The dashboard, the gate, the metrics, the Nemotron agent, AI triage and the Gemini patient view all work in it.

**Next on the software side is a camera-only mode.** It will use the real webcam CV, with no ESP32 needed. The progress table below shows what's done.

**Hardware is not connected yet.** The firmware is written but has never been compiled or flashed. See [Hardware checklist](#hardware-checklist).

## Run it (5 minutes)

```powershell
py -3.10 -m venv .venv                      # Python 3.10–3.12. Mediapipe does not support 3.13+
.venv\Scripts\pip install -r requirements.txt
$env:NG_MOCK = "1"
.venv\Scripts\python app.py                  # open http://localhost:5000
```

Logins: `therapist` / `therapist` sees everything. `patient` / `patient` gets the simplified view.

Tests: `.venv\Scripts\python -m pytest tests -q`. All 66 should pass.

To use the AI features, set these first. Without them the buttons show a clear error.

| env var | what it turns on | where to get it |
|---|---|---|
| `NVIDIA_API_KEY` | Nemotron agent and AI triage | build.nvidia.com |
| `GEMINI_API_KEY` | "Explain my progress" (patient view) | aistudio.google.com |
| `MONGODB_URI` | MongoDB Atlas storage. Without it, data is kept in memory | MongoDB Atlas, free cluster |

## How it fits together

```
ESP32 headband + wristband ──serial──▶ intent detector ─┐
(or MockSource)                                         │
                                                        ├─▶ GATE ─▶ servo angles ─▶ ESP32 servos
webcam ─▶ MediaPipe hand + pose ─▶ finger curls, ───────┘    │       (+ buzzer / LEDs)
(or MockVision)                    compensation              ▼
                                                     session metrics ─▶ MongoDB
                                                             │
                              Flask + Socket.IO dashboard ◀──┘ (live, 10×/s)
                              ├─ Nemotron agent (tool calls → adjusts difficulty)
                              ├─ AI triage (Nemotron ranks the caseload)
                              └─ Gemini patient explanation
```

**The gate rule:** the robot hand moves only when all three are true:
1. Both headband sites detect intent.
2. Posture is clean (no shoulder hike or trunk lean).
3. The camera sees the healthy hand.

Servo angle = finger curl × 160°.

### File map

| Path | What it does |
|---|---|
| `app.py` | Dashboard server: routes, logins, live socket |
| `neurogrip/protocol.py` | Serial message format shared with the firmware |
| `neurogrip/sources.py` | Sensor input: real serial (auto-reconnects) or mock |
| `neurogrip/intent.py` | Dual-site capacitive intent detection, with self-calibration |
| `neurogrip/signals.py` | Accelerometer tremor frequency and steadiness |
| `neurogrip/vision.py` | Webcam hand curls, compensation detection, mock vision |
| `neurogrip/clinical.py` | Camera-based tremor and finger-tapping test (new) |
| `neurogrip/gate.py` | The gate rule plus difficulty thresholds |
| `neurogrip/metrics.py` | Reps, activation rate, incident events, reaction latency |
| `neurogrip/engine.py` | Main 50 Hz loop that ties everything together |
| `neurogrip/agent.py` | Nemotron tool-calling agent |
| `neurogrip/triage.py` | AI caseload triage (State Farm) |
| `neurogrip/patient_view.py` | Gemini plain-language explanation |
| `neurogrip/store.py` | MongoDB or in-memory storage |
| `firmware/` | ESP32 sketch and wiring table |
| `docs/spec.md` | What we agreed to build |
| `docs/superpowers/plans/` | Step-by-step build plans |

## Progress

### Done ✅
| Feature | Track |
|---|---|
| Serial protocol, intent detection, accelerometer tremor and steadiness | Hardware |
| Webcam finger-curl tracking and compensation detection (shoulder hike, trunk lean) | Hardware / Overall |
| Gate plus proportional per-finger servo control | Hardware |
| Metrics: reps, **gate activation rate** (replaces bilateral symmetry), reaction latency with a cue | Overall |
| Mock mode: the whole app runs with no hardware | Demo backup |
| Nemotron agent with 4 tools and a **visible tool-call trace** on the dashboard | NVIDIA |
| Therapist and patient logins with different views, plus a live timestamped incident log | Winstead |
| AI triage: Nemotron flags urgent patients with a reason for each | State Farm |
| Gemini patient explanation | MLH Gemini |
| MongoDB storage (sessions, events, patient profiles) | MLH MongoDB |
| ESP32 firmware: 500 ms safety watchdog that opens the hand if the laptop stops | Hardware |
| Hardening from code review: bad DB, unplugged cable or frozen camera won't break the demo | All |
| Camera-based tremor and finger-tapping analysis (Parkinson's) | Overall |

### In progress 🔨: camera-only mode (no ESP32 needed)
Plan: [`docs/superpowers/plans/2026-11-07-no-hardware-cv.md`](superpowers/plans/2026-11-07-no-hardware-cv.md)

| Step | Status |
|---|---|
| 1. Camera tremor and finger-tap analysis functions | ✅ done |
| 2. Vision upgrades: wrist/pinch tracking, skeleton overlay, "hold to try" intent | ⏳ next |
| 3. Engine: camera tremor, 10 s finger-tap test, random-delay reaction cue | ⏳ |
| 4. Routes: live camera feed, intent controls, tap test | ⏳ |
| 5. **Frontend rebuild:** camera feed next to an animated robotic hand that mirrors yours, Parkinson's and cognitive panels, full-screen cues | ⏳ |

When this is done, `NG_MODE=camera` will demo everything with just a laptop webcam: real hand tracking, the robot hand mimicking it on screen, Parkinson's screening and the reaction test.

### Not started
- Therapist → patient text messages (Winstead). Only if we have time.
- Vultr deploy and GoDaddy domain. Manual steps, about 20 minutes total.

## Hardware checklist

Full wiring is in [`firmware/README.md`](../firmware/README.md).

- [ ] Install Arduino IDE, the **ESP32 board package 3.x** and **ESP32Servo ≥ 3.0**. On 2.x the buzzer can break the thumb servo.
- [ ] Wire everything to the pins in the table. **The index servo goes on GPIO18, not GPIO12** (GPIO12 can stop the board from booting).
- [ ] Power the servos from a **separate 5V supply**, with its ground tied to the ESP32 GND.
- [ ] Flash, then open Serial Monitor at 115200. You should see `S,...` lines at about 50 per second.
- [ ] Send `A,90,90,90`. The servos should move, then return to 0 within 0.5 s (the watchdog).
- [ ] Bench test: keep sending `A,90,90,90` while sending `B,1000,200`. The thumb servo must not twitch.
- [ ] Close Serial Monitor, then run with `$env:NG_SERIAL_PORT="COM5"` (your port) and without `NG_MOCK`.
- [ ] Tune finger curls with `.venv\Scripts\python -m neurogrip.vision` if the robot hand doesn't follow well.

**Parts assumptions. Tell Hassan if any are wrong.**
- Classic ESP32 DevKit. On an ESP32-S3 the touch pins change.
- The Grove accelerometer is an **ADXL345**. A LIS3DHTR needs a different read function.
- Three servos: thumb, index, and "rest" (the other three fingers together).

## Decisions worth knowing
- **"Bilateral symmetry" is now "gate activation rate":** the % of time the patient's intent was strong enough to move the robot. Symmetry would always read about 100%, because the servo copies the healthy hand.
- **Logins are hardcoded:** fine for the demo. If judges ask, the answer is "v2 adds real auth."
- **An open healthy hand releases the robot grip.** Before the fix, the hand stayed clenched.
- **Mock tremor defaults to 4.5 Hz** so the tile isn't stuck at 0. Set `NG_MOCK_TREMOR=0` to turn it off.
- **Parkinson's and cognitive results are labeled screening indicators,** never diagnoses.

## Known issues (small, deferred)
- If Nemotron replies with nothing, the summary box is blank.
- "detailed thinking off" may be the wrong switch for Nemotron v1.5. Check the model card; it may be `/no_think`.
- The camera may lock onto the robot hand instead of the healthy hand if both are in view. Keep the robot hand out of frame.
- If the ESP32 resets in the middle of a reaction test, that trial can get stuck.

## Demo plan (draft)
1. Log in as therapist and pick **Stroke**. Try to grip: the robot hand follows, but only with intent and clean posture. Hike a shoulder and it blocks and logs an incident.
2. Switch to **Parkinson's**: show the tremor reading and run the finger-tap test.
3. Switch to **Cognitive**: run the reaction test.
4. **Run AI agent:** show the tool-call trace and the difficulty change it makes. (NVIDIA)
5. **Run AI triage:** urgent patients come out on top, each with a reason. (State Farm)
6. Log in as patient and click **Explain my progress**. (Gemini)
7. **Backup:** if the hardware dies, restart with `NG_MOCK=1`, or with `NG_MODE=camera` once that mode is finished.
