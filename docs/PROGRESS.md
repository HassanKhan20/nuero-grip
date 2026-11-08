# NeuroGrip: team progress

_Last updated: 2026-11-07_

## Where we are

**Every feature now works without the ESP32.** Camera mode uses the laptop webcam for real hand tracking:
- An animated robotic hand on screen mirrors your hand, finger by finger.
- Parkinson's tremor and the finger-tap test are measured from the video.
- The reaction test is timed until the camera sees your grip.
- The Nemotron agent, AI triage and the Gemini patient view all run.

**Hardware:** the firmware is written for **our exact board** (Inland ESP32-WROOM-32E) with 5 SG90 servos. It has never been compiled or flashed. See [Hardware checklist](#hardware-checklist).

## How NeuroGrip answers each track

Each track is its own full page, linked in order from the system bar on every page: **1 Live session** (`/`, Overall) → **2 AI reasoning** (`/reasoning`, NVIDIA) → **3 Command center** (`/command`, Winstead) → **4 Surge response** (`/surge`, State Farm). Pages 2–4 are therapist only; a patient opening one gets an Access denied page and a security incident. `/mind` is the full-screen headband check.

NeuroGrip is one system with three layers. Each layer is where one track's prompt is answered.

```
 sensors + camera ──► DETECT (rules, every second) ──► RESPOND (incidents, owners, timeline) ──► COORDINATE (AI + triage at scale)
   headband, IMU,       tremor band, slow/missed          command center, audit log,            Nemotron agent reviews sessions,
   webcam CV            cues, tap slowdown, sensor/       role-based access, lockout            1,200-patient surge triage + plan
                        camera loss, failed logins,
                        denied requests, capacity gap
```

| Track | Their prompt | What we built for it | Where to show it |
|---|---|---|---|
| **Overall** | Creativity, technical skill, impact | Intent-gated robotic hand (moves only while the patient tries) plus camera screening for 5 conditions, with the detection, response and coordination layers around it | The whole demo |
| **NVIDIA** (Nemotron beyond a chatbot) | Multi-step workflows, tool use, real-world use | A Nemotron agent with **6 tools**: reads session metrics and history, **reads the live detections**, changes difficulty, buzzes the device, and **escalates its own incidents**. Every step's reasoning is shown and exported as a PDF. It also writes the surge coordination brief. | System 2 · `/reasoning` → Run review (reasoning chain, toolbox, next steps); Command center shows incidents opened by "Nemotron agent" |
| **Winstead PC** (incident response command center) | Isolated secure system, access control, incident documentation with real-time updates, scope definitions, real-time comms | **Command center** (its own page, `/command`), with a live **Detectors** board showing all 10 rules: incidents opened automatically by detection rules or declared by hand. Each has a severity, category, **scope** (patient / device / network / account), owner, status (open → acknowledged → resolved) and a timeline. **Live team messages** go on each incident and reach every signed-in therapist instantly. **Audit log** records every sign-in, failed sign-in, blocked request, AI action and incident change. **Access control:** therapist-only routes; a patient account calling one is blocked, logged, and becomes a security incident. 3 failed sign-ins in a minute open an incident; 5 lock that address out. **Isolated mode** (`NG_ISOLATED=1`): no outbound AI calls, localhost only, everything else keeps working offline. Hardened session cookie and security headers. | System 3 · `/command` |
| **State Farm** (disaster: thousands affected, find urgent needs, coordinate help, no one overlooked) | Identify urgent needs, coordinate assistance, nobody overlooked | **Regional surge triage**: 1,200 patients after a disaster, spread unevenly across 5 districts (the hardest-hit districts have more people cut off from care). **Every patient** gets an explainable 0–100 risk score, and the hard rule (3+ days without a session, or declining → urgent) applies to all of them. Therapists are assigned most-at-risk first, up to capacity. Whoever can't get one goes on a ranked waitlist, and a **capacity-gap incident** opens automatically, so nobody silently drops off. Nemotron reads the totals and the top patients and writes the **coordination plan** (tele-rehab, group sessions, home kits). | System 4 · `/surge` → Write the plan |
| **MLH** | MongoDB, Vultr, GoDaddy, Gemini | MongoDB stores sessions, events, patients, **incidents and the audit log**. Gemini writes the patient's plain-language explanation (`gemini-3.5-flash`). Vultr/GoDaddy: see [DEPLOY.md](DEPLOY.md). | Patient login → Explain my progress |

### Detection rules (all in `neurogrip/detect.py` and `app.py`)
| Detection | Trigger | Severity | Closes itself? |
|---|---|---|---|
| Sensor stream lost | No sensor frames for 2 s | Critical | Yes, after 2 s healthy |
| Camera offline | No camera frames for 5 s (camera/hardware mode) | High | Yes |
| Tremor | 3.5–7.5 Hz sustained 5 s (flags whether it is in the 4–6 Hz Parkinsonian band) | Medium | No: a therapist reviews it |
| Slow reaction | Mean of the last 2–3 cues above 1,000 ms | Medium | No |
| Missed cues | 2 cues with no response within 3 s | Medium | No |
| Finger-tap slowdown | Tap test flags < 2 taps/s or > 25% amplitude decrement | Medium | No |
| Repeated failed sign-ins | 3 in a minute from one address (5 = lockout, critical) | High | No |
| Unauthorized access | A non-therapist account calls a therapist-only route | Medium | No |
| Capacity gap | Urgent patients left without a therapist after assignment | High | No |
| AI escalation | Nemotron calls `open_incident` during a session review | Set by the agent | No |

The same condition re-detected while its incident is still open does not create a duplicate. It raises the count, and escalates the severity if the new detection is worse. Clinical flags are screening indicators, never diagnoses.

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
| `hardware` | real webcam (optional) | required (`NG_SERIAL_PORT=COM5`) | foil pads on the headband and forearm. **Starts in Intent only control.** |

Logins: `therapist` / `therapist` sees everything. `patient` / `patient` gets the simplified view.

Tests: `.venv\Scripts\python -m pytest tests -q`. All 100 should pass.

To use the AI features, set these first. Without them the buttons show a clear error.

| env var | what it turns on | where to get it |
|---|---|---|
| `NVIDIA_API_KEY` | Nemotron agent and AI triage | build.nvidia.com |
| `GEMINI_API_KEY` | "Explain my progress" (patient view) | aistudio.google.com |
| `MONGODB_URI` | MongoDB Atlas storage. Without it, data is kept in memory | MongoDB Atlas, free cluster |

## The "mind control" demo: no camera needed
1. On the **Robotic hand** tile, click **Intent only**. The camera dims and says *Camera not used*.
2. Pick a grip shape: **Fist**, **Pinch**, **Point**, or **Wave** (fingers close one after another, thumb to pinky, the flashiest one).
3. **Hold Space**, or wear the headband in hardware mode. The intent line rises past the dashed threshold and the robotic hand closes smoothly. The harder you try, the further it closes; relax and it opens.

What to say: *"With only the headband's muscle signal, no camera, the hand closes when the patient tries and opens when they relax. That's for patients with no healthy hand to mirror."*

## Try it in camera mode
1. Log in as therapist and hold your hand up to the webcam. A skeleton is drawn on the feed.
2. **Hold Space** and open and close your hand. The robotic hand copies each finger. Let go of Space and it stops: that's the gate.
4. Pick **Parkinson's**, click **Start finger-tap test**, then tap thumb and index for 10 s. You get taps, rate, amplitude decrement, rhythm and a screening flag.
5. Pick **Cognitive** and click **Start reaction test**. Squeeze when "SQUEEZE!" appears.
6. Pick **Phantom limb**. The robotic hand is shown mirrored, for mirror therapy.

## How it fits together

```
ESP32 headband + wristband ──serial──▶ intent detector ─┐
(or Hold-to-try / Space in camera mode)                 │
                                                        ├─▶ GATE ─▶ 5 servo angles ─▶ ESP32 (one servo per finger)
webcam ─▶ MediaPipe hand ────────▶ 5 finger curls, ─────┘    │       + on-screen robotic hand
(or MockVision)                                           │       + buzzer / LEDs
                                   wrist (tremor),           ▼
                                   pinch (tap test)   session metrics ─▶ MongoDB
                                                             │
                              Flask + Socket.IO dashboard ◀──┘ (live, 10×/s; events instant)
                              ├─ Nemotron agent (tool calls → adjusts difficulty)
                              ├─ AI triage (Nemotron ranks the caseload)
                              └─ Gemini patient explanation
```

**Control modes:**
- **Mirror camera:** each finger copies your healthy hand.
- **Intent only:** intent strength closes the hand in the chosen grip shape, and no camera is needed. To start up as intent-only, set `NG_CONTROL=intent` and `NG_GRIP=wave`.

**The gate rule (mirror mode):** the robot hand moves only when both are true:
1. Intent is detected.
2. The camera sees the healthy hand.

Each finger's servo angle = that finger's curl × 160°. Serial command: `A,<thumb>,<index>,<middle>,<ring>,<pinky>`.

### File map

| Path | What it does |
|---|---|
| `app.py` | Dashboard server: routes, logins, live socket, MJPEG camera feed |
| `neurogrip/protocol.py` | Serial message format shared with the firmware (5 servos) |
| `neurogrip/sources.py` | Sensor input: real serial (auto-reconnects) or mock; `IntentControl` for hold-to-try |
| `neurogrip/intent.py` | Dual-site capacitive intent detection, with self-calibration |
| `neurogrip/signals.py` | Accelerometer tremor frequency and steadiness |
| `neurogrip/vision.py` | Webcam: 5 finger curls, pinch, wrist, skeleton overlay |
| `neurogrip/clinical.py` | Camera tremor and finger-tap (bradykinesia) analysis |
| `neurogrip/gate.py` | The gate rule plus difficulty thresholds |
| `neurogrip/metrics.py` | Reps, activation rate, incidents, reaction latency (intent or grip) |
| `neurogrip/engine.py` | Main 50 Hz loop that ties everything together; tap test; randomized reaction cue |
| `neurogrip/agent.py` | Nemotron tool-calling agent (6 tools, including reading and opening incidents) |
| `neurogrip/triage.py` | Caseload triage (10 patients, Nemotron) and regional surge triage (1,200 patients, rule-scored, Nemotron brief) |
| `neurogrip/detect.py` | Live detection rules that open and auto-close incidents |
| `neurogrip/incidents.py` | Incident log (scope, owner, status, timeline, no duplicates) and audit log |
| `static/command.js` | Command center and surge triage logic (therapist only) |
| `templates/_sysnav.html`, `base.html` | The system bar on every page: 1 Live session → 2 AI reasoning → 3 Command center → 4 Surge response |
| `templates/reasoning.html`, `static/reasoning.js` | AI reasoning page: Nemotron's tool chain step by step, toolbox, conclusion, next steps, past reviews |
| `templates/command.html`, `surge.html`, `denied.html` | Command center, surge response and the access-denied page (blocked + logged + incident) |
| `neurogrip/patient_view.py` | Gemini plain-language explanation |
| `neurogrip/store.py` | MongoDB or in-memory storage |
| `templates/`, `static/` | Dashboard UI. `static/hand.js` is the animated robotic hand |
| `firmware/` | ESP32 sketch and wiring table |

## Progress

### Done ✅
| Feature | Track |
|---|---|
| **Intent-only control:** the hand moves from intent alone, with no camera, in 4 grip shapes and smooth motion | Demo / Hardware |
| **Calibrate to this person** (relax, then squeeze) scales intent to the wearer's own pads, with a live raw-pad readout | Hardware |
| Firmware for our board: pins on the left header, auto-detects ADXL345 or LIS3DHTR, averaged touch reads | Hardware |
| Camera mode: every feature works with only a webcam | Demo |
| Live camera feed with hand skeleton, beside a robotic hand that mimics all 5 fingers | Overall / Hardware |
| Hold-to-try or Space as a stand-in for the headband; Auto toggle | Demo |
| Parkinson's: tremor from the camera (wrist motion FFT) or the wristband | Overall |
| Parkinson's: 10 s finger-tap test (taps, rate, amplitude decrement, rhythm, screening flag) | Overall |
| Cognitive: reaction test with a random 1–3 s cue, full-screen SQUEEZE prompt and beep, timed to the camera-detected grip, last-10 trial chart | Overall |
| Phantom-limb mode mirrors the robotic hand | Overall |
| **5 servos, one per finger:** protocol, gate, firmware and UI updated | Hardware |
| Gate plus proportional per-finger control | Hardware |
| Gate activation rate (replaces bilateral symmetry), reps, incident log | Overall / Winstead |
| Nemotron agent with 4 tools and a visible tool-call trace | NVIDIA |
| Therapist and patient logins with different views; live timestamped incident log | Winstead |
| AI triage: Nemotron flags urgent patients with a reason | State Farm |
| Gemini patient explanation | MLH Gemini |
| MongoDB storage | MLH MongoDB |
| Firmware with a 500 ms safety watchdog (opens the hand if the laptop stops) | Hardware |
| Hardening: bad DB, unplugged cable or frozen camera won't break the demo | All |
| Rebuilt dashboard: light and dark themes, works on mobile | Overall |
| **Detection layer:** 10 rules turn sensor, clinical and security signals into incidents, with no duplicates and auto-close for device faults | All |
| **Command center:** incidents with scope, owner, status, timeline and live team messages, plus an audit log and PDF export | Winstead |
| **Security:** therapist-only routes are logged and become incidents, sign-in lockout, hardened cookies and headers, `NG_ISOLATED=1` air-gapped mode | Winstead |
| **Regional surge triage:** 1,200 patients scored, capacity-aware assignment, waitlist, capacity-gap incident, Nemotron coordination brief | State Farm / NVIDIA |
| Nemotron agent reads live detections and escalates its own incidents (6 tools) | NVIDIA |

### Not started
- Therapist → patient text messages (Winstead). Only if we have time.
- Vultr deploy and GoDaddy domain. Manual steps, about 20 minutes total: follow [DEPLOY.md](DEPLOY.md).
- Nemotron and Gemini are both tested live with real keys (Nemotron: session review, caseload triage, surge brief; Gemini: patient explanation).

## Hardware checklist

**Our parts:**
- **Board:** Inland ESP32 dev board (**ESP32-WROOM-32E**, classic ESP32).
- **Servos:** 5× SG90, one per finger.
- **Power:** 4×AA pack for the servos.
- **Intent pads:** 2× foil pads, one in the headband and one on the forearm.
- **Other:** Grove buzzer, Grove green and red LEDs, Grove accelerometer (ADXL345 *or* LIS3DHTR, auto-detected).

Full wiring and test steps are in [`firmware/README.md`](../firmware/README.md).

| Part | Pin |
|---|---|
| Servo thumb / index / middle / ring / pinky | **IO13 / IO14 / IO27 / IO26 / IO25** (left header) |
| Temple pad / forearm pad | **IO32 / IO33** (left header) |
| Buzzer / LED green / LED red | IO18 / IO19 / IO23 |
| Accelerometer SDA / SCL | IO21 / IO22 |

⚠️ **Nothing on SD0–SD3, CMD or CLK** (flash pins) **and nothing on IO12** (boot pin). In the current breadboard photo, one wire looks like it's on **SD2** and one on **IO12**. Move them.

- [ ] Arduino IDE → board **"ESP32 Dev Module"** (esp32 core 3.x) + library **ESP32Servo**.
- [ ] Wire the servo **signal** wires to the pins above.
- [ ] Wire the AA pack: **+** → all servo red wires. **−** → all servo brown wires **and** ESP32 GND. Add a **470–1000 µF capacitor** across the pack.
- [ ] Make the pads: foil + short wire, a **thin foam or cloth layer** between foil and skin, strapped on firmly.
- [ ] Flash, then open Serial Monitor at 115200. The first line names the accelerometer, then `S,...` lines stream. Squeezing should drop the pad numbers.
- [ ] Send `A,90,90,90,90,90`. All five fingers move, then reopen within 0.5 s (the safety watchdog).
- [ ] Close Serial Monitor. Run `$env:NG_MODE="hardware"; $env:NG_SERIAL_PORT="COM5"; .venv\Scripts\python app.py`.
- [ ] On the dashboard click **Calibrate to this person**: relax for 2 s, then clench and squeeze for 3 s.
- [ ] Squeeze → the fingers close. Relax → they open. **That's the core loop.**

**Not tested yet:** the firmware hasn't been compiled on a real board. If the Arduino IDE shows an error, paste it to Hassan or Claude.

## Decisions worth knowing
- **Posture tracking (shoulder hike, trunk lean) was removed.** It was unreliable and not core. The gate is now intent plus a visible hand, and the pose model no longer runs, so the camera loop is faster.
- **"Bilateral symmetry" is now "gate activation rate":** the % of time the patient's intent was strong enough to move the robot. Symmetry would always read about 100%, because the servo copies the healthy hand.
- **In camera mode the tremor reading comes from the camera** (wrist motion). In hardware mode it comes from the wristband accelerometer.
- **In camera mode the reaction test is timed to a camera-detected grip.** In hardware mode it is timed to headband intent.
- **The reaction cue comes after a random 1–3 s,** so the patient can't anticipate it.
- **Logins are hardcoded:** fine for the demo. If judges ask, the answer is "v2 adds real auth."
- **All Parkinson's and cognitive outputs are labeled screening indicators,** never diagnoses.

## Known issues (small, deferred)
- The camera tracks one hand. Keep the robot hand out of frame so it doesn't track the wrong one.
- The camera's tremor threshold (`CV_TREMOR_MIN_AMP` in `clinical.py`) may need tuning on the demo webcam.
- If the ESP32 resets in the middle of a reaction test, that trial can get stuck.

## Demo plan (draft)
1. Log in as therapist and pick **Stroke**. Hold Space (or wear the headband) and grip: the robot hand follows each finger. Let go and it stops.
2. Pick **Parkinson's**: show the tremor reading and run the finger-tap test.
3. Pick **Cognitive**: run the reaction test.
4. **Run AI agent:** show the tool-call trace and the difficulty change it makes. (NVIDIA)
5. **System 4 · Surge response:** 1,200 patients scored instantly; show the waitlist and the hardest-hit district, then **Write the plan**. (State Farm + NVIDIA)
6. **System 3 · Command center:** the Detectors board lights up the firing rules; the tremor and capacity-gap incidents are already there. Acknowledge one, type a message (it appears live in a second therapist tab), resolve it. Open **Audit log**. (Winstead)
7. Log in as patient and try a therapist action (or a wrong password 3 times): a security incident appears live on the therapist's screen. (Winstead)
8. Log in as patient and click **Explain my progress**. (Gemini)
9. **Backup:** if the hardware dies, restart with `NG_MODE=camera`. If the camera dies too, use `NG_MODE=mock`.
