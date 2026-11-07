# NeuroGrip: team progress

_Last updated: 2026-11-07_

## Where we are

**Every feature now works without the ESP32.** Camera mode uses the laptop webcam for real hand and pose tracking:
- An animated robotic hand on screen mirrors your hand, finger by finger.
- Parkinson's tremor and the finger-tap test are measured from the video.
- The reaction test is timed until the camera sees your grip.
- The Nemotron agent, AI triage and the Gemini patient view all run.

**Hardware: the firmware is written for 5 servos, one per finger. It has never been compiled or flashed.** See [Hardware checklist](#hardware-checklist).

## Run it (5 minutes)

```powershell
py -3.10 -m venv .venv                      # Python 3.10–3.12. Mediapipe does not support 3.13+
.venv\Scripts\pip install -r requirements.txt
$env:NG_MODE = "camera"                      # or "mock" (no camera) or "hardware"
.venv\Scripts\python app.py                  # open http://localhost:5000
```

| `NG_MODE` | Camera | ESP32 | Intent comes from |
|---|---|---|---|
| `camera` (default) | real webcam | not needed | **Hold to try** button or **Space** (or the Auto toggle) |
| `mock` | none (synthetic hand) | not needed | automatic 3 s on / 3 s off cycle |
| `hardware` | real webcam | required (`NG_SERIAL_PORT=COM5`) | capacitive headband |

Logins: `therapist` / `therapist` sees everything. `patient` / `patient` gets the simplified view.

Tests: `.venv\Scripts\python -m pytest tests -q`. All 80 should pass.

To use the AI features, set these first. Without them the buttons show a clear error.

| env var | what it turns on | where to get it |
|---|---|---|
| `NVIDIA_API_KEY` | Nemotron agent and AI triage | build.nvidia.com |
| `GEMINI_API_KEY` | "Explain my progress" (patient view) | aistudio.google.com |
| `MONGODB_URI` | MongoDB Atlas storage. Without it, data is kept in memory | MongoDB Atlas, free cluster |

## Try it in camera mode
1. Log in as therapist and hold your hand up to the webcam. A skeleton is drawn on the feed.
2. **Hold Space** and open and close your hand. The robotic hand copies each finger. Let go of Space and it stops: that's the gate.
3. Hike one shoulder while holding Space. The gate blocks, the hand glows red, and an incident is logged.
4. Pick **Parkinson's**, click **Start finger-tap test**, then tap thumb and index for 10 s. You get taps, rate, amplitude decrement, rhythm and a screening flag.
5. Pick **Cognitive** and click **Start reaction test**. Squeeze when "SQUEEZE!" appears.
6. Pick **Phantom limb**. The robotic hand is shown mirrored, for mirror therapy.

## How it fits together

```
ESP32 headband + wristband ──serial──▶ intent detector ─┐
(or Hold-to-try / Space in camera mode)                 │
                                                        ├─▶ GATE ─▶ 5 servo angles ─▶ ESP32 (one servo per finger)
webcam ─▶ MediaPipe hand + pose ─▶ 5 finger curls, ─────┘    │       + on-screen robotic hand
(or MockVision)                    compensation,             │       + buzzer / LEDs
                                   wrist (tremor),           ▼
                                   pinch (tap test)   session metrics ─▶ MongoDB
                                                             │
                              Flask + Socket.IO dashboard ◀──┘ (live, 10×/s; events instant)
                              ├─ Nemotron agent (tool calls → adjusts difficulty)
                              ├─ AI triage (Nemotron ranks the caseload)
                              └─ Gemini patient explanation
```

**The gate rule:** the robot hand moves only when all three are true:
1. Intent is detected.
2. Posture is clean (no shoulder hike or trunk lean).
3. The camera sees the healthy hand.

Each finger's servo angle = that finger's curl × 160°. Serial command: `A,<thumb>,<index>,<middle>,<ring>,<pinky>`.

### File map

| Path | What it does |
|---|---|
| `app.py` | Dashboard server: routes, logins, live socket, MJPEG camera feed |
| `neurogrip/protocol.py` | Serial message format shared with the firmware (5 servos) |
| `neurogrip/sources.py` | Sensor input: real serial (auto-reconnects) or mock; `IntentControl` for hold-to-try |
| `neurogrip/intent.py` | Dual-site capacitive intent detection, with self-calibration |
| `neurogrip/signals.py` | Accelerometer tremor frequency and steadiness |
| `neurogrip/vision.py` | Webcam: 5 finger curls, pinch, wrist, compensation, skeleton overlay |
| `neurogrip/clinical.py` | Camera tremor and finger-tap (bradykinesia) analysis |
| `neurogrip/gate.py` | The gate rule plus difficulty thresholds |
| `neurogrip/metrics.py` | Reps, activation rate, incidents, reaction latency (intent or grip) |
| `neurogrip/engine.py` | Main 50 Hz loop that ties everything together; tap test; randomized reaction cue |
| `neurogrip/agent.py` | Nemotron tool-calling agent |
| `neurogrip/triage.py` | AI caseload triage (State Farm) |
| `neurogrip/patient_view.py` | Gemini plain-language explanation |
| `neurogrip/store.py` | MongoDB or in-memory storage |
| `templates/`, `static/` | Dashboard UI. `static/hand.js` is the animated robotic hand |
| `firmware/` | ESP32 sketch and wiring table |

## Progress

### Done ✅
| Feature | Track |
|---|---|
| Camera mode: every feature works with only a webcam | Demo |
| Live camera feed with hand skeleton, beside a robotic hand that mimics all 5 fingers | Overall / Hardware |
| Hold-to-try or Space as a stand-in for the headband; Auto toggle | Demo |
| Parkinson's: tremor from the camera (wrist motion FFT) or the wristband | Overall |
| Parkinson's: 10 s finger-tap test (taps, rate, amplitude decrement, rhythm, screening flag) | Overall |
| Cognitive: reaction test with a random 1–3 s cue, full-screen SQUEEZE prompt and beep, timed to the camera-detected grip, last-10 trial chart | Overall |
| Phantom-limb mode mirrors the robotic hand | Overall |
| **5 servos, one per finger:** protocol, gate, firmware and UI updated | Hardware |
| Gate plus proportional per-finger control; compensation detection | Hardware |
| Gate activation rate (replaces bilateral symmetry), reps, incident log | Overall / Winstead |
| Nemotron agent with 4 tools and a visible tool-call trace | NVIDIA |
| Therapist and patient logins with different views; live timestamped incident log | Winstead |
| AI triage: Nemotron flags urgent patients with a reason | State Farm |
| Gemini patient explanation | MLH Gemini |
| MongoDB storage | MLH MongoDB |
| Firmware with a 500 ms safety watchdog (opens the hand if the laptop stops) | Hardware |
| Hardening: bad DB, unplugged cable or frozen camera won't break the demo | All |
| Rebuilt dashboard: light and dark themes, works on mobile | Overall |

### Not started
- Therapist → patient text messages (Winstead). Only if we have time.
- Vultr deploy and GoDaddy domain. Manual steps, about 20 minutes total.
- Real Nemotron and Gemini calls haven't been tried yet, because no API keys are set here. Test them once you have keys.

## Hardware checklist

Full wiring is in [`firmware/README.md`](../firmware/README.md).

- [ ] Install Arduino IDE, the **ESP32 board package 3.x** and **ESP32Servo ≥ 3.0**. On 2.x the buzzer can break a servo.
- [ ] Wire the **5 servos**:

  | Finger | Thumb | Index | Middle | Ring | Pinky |
  |---|---|---|---|---|---|
  | GPIO | 13 | 18 | 19 | 23 | 33 |

  Don't use GPIO 0, 2, 5, 12 or 15. They can stop the board from booting.
- [ ] Power the servos from a **separate 5V supply rated 3 A or more**, with its ground tied to the ESP32 GND. Five servos stalling on a grip can draw several amps.
- [ ] Flash, then open Serial Monitor at 115200. You should see `S,...` lines at about 50 per second.
- [ ] Send `A,90,90,90,90,90`. All five servos should move, then return to 0 within 0.5 s (the watchdog).
- [ ] Bench test: keep sending `A,90,90,90,90,90` while sending `B,1000,200`. No servo should twitch.
- [ ] Close Serial Monitor, then run with `$env:NG_MODE="hardware"` and `$env:NG_SERIAL_PORT="COM5"` (your port).
- [ ] Tune finger curls with `.venv\Scripts\python -m neurogrip.vision` if the hand doesn't follow well.

**Parts assumptions. Tell Hassan if any are wrong.**
- Classic ESP32 DevKit. On an ESP32-S3 the touch pins change.
- The Grove accelerometer is an **ADXL345**. A LIS3DHTR needs a different read function.

## Decisions worth knowing
- **"Bilateral symmetry" is now "gate activation rate":** the % of time the patient's intent was strong enough to move the robot. Symmetry would always read about 100%, because the servo copies the healthy hand.
- **In camera mode the tremor reading comes from the camera** (wrist motion). In hardware mode it comes from the wristband accelerometer.
- **In camera mode the reaction test is timed to a camera-detected grip.** In hardware mode it is timed to headband intent.
- **The reaction cue comes after a random 1–3 s,** so the patient can't anticipate it.
- **Logins are hardcoded:** fine for the demo. If judges ask, the answer is "v2 adds real auth."
- **All Parkinson's and cognitive outputs are labeled screening indicators,** never diagnoses.

## Known issues (small, deferred)
- "detailed thinking off" may be the wrong switch for Nemotron v1.5. Check the model card; it may be `/no_think`.
- The camera tracks one hand. Keep the robot hand out of frame so it doesn't track the wrong one.
- The camera's tremor threshold (`CV_TREMOR_MIN_AMP` in `clinical.py`) may need tuning on the demo webcam.
- If the ESP32 resets in the middle of a reaction test, that trial can get stuck.

## Demo plan (draft)
1. Log in as therapist and pick **Stroke**. Hold Space (or wear the headband) and grip: the robot hand follows each finger. Hike a shoulder and it blocks and logs an incident.
2. Pick **Parkinson's**: show the tremor reading and run the finger-tap test.
3. Pick **Cognitive**: run the reaction test.
4. **Run AI agent:** show the tool-call trace and the difficulty change it makes. (NVIDIA)
5. **Run AI triage:** urgent patients come out on top, each with a reason. (State Farm)
6. Log in as patient and click **Explain my progress**. (Gemini)
7. **Backup:** if the hardware dies, restart with `NG_MODE=camera`. If the camera dies too, use `NG_MODE=mock`.
