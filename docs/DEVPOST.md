## Inspiration

After a stroke, the hand usually isn't broken. The brain's connection to it is. Recovery means the brain rewiring itself, and that takes **hundreds of repetitions where the patient tries to move and the movement actually happens**. The trap is that a patient with a weak hand *can't* move it, so they can't practice. They start using the good hand instead, the weak one gets worse, and therapy sessions only fit a few dozen repetitions.

Clinical devices already solve this by moving the hand **only when the patient's own effort is detected**. They cost thousands of dollars and are tied to clinics. We wanted to build that same loop from parts that cost a few dozen dollars, and make it something a patient could use at home with a therapist still in the loop.

## What it does

**NeuroGrip's robotic hand only moves when the patient is trying to move.**

1. **Intent:** sensors on a headband (temple) and the forearm detect the patient's effort.
2. **Target:** a webcam tracks the patient's *healthy* hand and measures how bent each of its five fingers is.
3. **Gate:** the robotic hand copies that shape finger by finger, but only while the effort is there. If the patient stops trying, the hand stops.
4. **Data:** every session records reps, how often the patient's effort was enough to move the hand, peak range of motion per finger, reaction time and tremor.
5. **AI care loop:**
   - **NVIDIA Nemotron** reviews each session using tool calls. It pulls the metrics and the patient's history, **raises or lowers the effort needed to trigger the hand**, raises an alert if anything is declining, and writes a 3-sentence clinical summary. Its reasoning appears before every tool call.
   - **AI triage** ranks a 10-patient caseload as URGENT, MONITOR or STABLE, so one therapist can follow many patients at home.
   - **Gemini** explains the session to the patient in plain, encouraging language.

The same loop works as a platform for other conditions:
- **Parkinson's:** tremor frequency, plus a 10-second finger-tap test modelled on the clinical exam.
- **Cognitive screening:** a reaction-time test.
- **Cerebral palsy:** the same intent-gated practice.
- **Mirror therapy for amputees with phantom-limb pain.**

The robotic hand stands in for what would be a soft glove on the patient's weak hand. For amputees, it stands in for the prosthetic.

## How we built it

**Hardware:**
- An ESP32 streams the intent sensors and a wrist accelerometer at 50 Hz.
- Five hobby servos drive a tendon-actuated hand with fishing-line tendons and rubber-band return springs.
- The firmware has a **500 ms safety watchdog**: if the laptop stops sending commands, the hand opens.

**Vision:** MediaPipe hand landmarks give a curl value $c_i \in [0,1]$ for each finger, from the ratio of fingertip-to-wrist distance to knuckle-to-wrist distance:

$$
r_i = \frac{\lVert p_{\text{tip}} - p_{\text{wrist}} \rVert}{\lVert p_{\text{mcp}} - p_{\text{wrist}} \rVert},
\qquad
c_i = \operatorname{clamp}_{[0,1]}\!\left(\frac{R_{\text{open}} - r_i}{\Delta R}\right),
\qquad
\theta_i = 160^\circ \cdot c_i
$$

**Intent:** each sensor site $s$ is compared with a relaxed baseline $b_s$. After a quick per-person calibration ("relax, then squeeze as hard as you can"), each site's change is scaled to that person's own full effort $D_s$:

$$
d_s = \frac{\lvert b_s - x_s \rvert}{b_s},
\qquad
n = \min_{s \,\in\, \{\text{temple},\,\text{forearm}\}} \frac{d_s}{D_s},
\qquad
\text{intent} \iff n \ge f_\ell
$$

The difficulty level $\ell$ sets $f_\ell \in \{0.2, 0.3, 0.4, 0.5, 0.6\}$: the share of the person's own maximum effort needed to move the hand. That is the dial Nemotron turns, so the robot never does the work for the patient.

**Clinical signals:**
- **Tremor:** the motion signal is detrended and windowed, and the tremor frequency is the strongest peak between 3 and 12 Hz:
  $$f_{\text{tremor}} = \arg\max_{3 \le f \le 12\,\text{Hz}} \big\lvert \mathcal{F}\{w \cdot \tilde{x}\}(f) \big\rvert$$
  It comes from the wrist accelerometer, or from the webcam's wrist track when no hardware is connected.
- **Finger-tap test:** we count taps, the tap rate and the rhythm. **Amplitude decrement** compares how wide the first third of the taps were with the last third:
  $$\delta = \frac{\bar{A}_{\text{first}} - \bar{A}_{\text{last}}}{\bar{A}_{\text{first}}} \times 100\%$$
  The test flags a possible concern when the rate is below 2 Hz or $\delta > 25\%$. These are screening indicators, never diagnoses.

**Software:**
- A Python engine runs a 50 Hz loop.
- A Flask + Socket.IO dashboard updates 10 times a second, with an interactive 3D hand built in Three.js.
- Nemotron runs through NVIDIA's API with a real tool-calling loop. Gemini writes the patient view.
- Sessions are stored in MongoDB Atlas.
- There are separate therapist and patient logins.
- **Three run modes:** full hardware; webcam only, holding Space to signal intent; and fully simulated. The demo can't be sunk by one broken component.

## Challenges we ran into

- **Capacitive intent sensing is fussy.** Bare foil on skin reads "touched" all the time. A thin foam layer between foil and skin, plus per-wearer calibration, turned it into a reading that rises gradually with effort.
- **A camera bug that looked random.** Webcam frames sometimes arrived less than 1 ms apart and got the same timestamp. MediaPipe rejected them, and the camera thread died while the dashboard still showed the camera as healthy. We made timestamps strictly increasing and made the camera restart itself.
- **Our AI model was retired mid-hackathon.** The Nemotron model we started with disappeared from NVIDIA's hosted catalog, so we moved to the current Nemotron Super and its reasoning settings.
- **Picking honest metrics.** "Bilateral symmetry" always read about 100%, because the robot copies the healthy hand. We replaced it with **gate activation rate**: the share of time the patient's own effort was strong enough to move the hand.
- **Power.** Five servos gripping at once can draw about 3 A. That meant a separate battery pack, a shared ground and a smoothing capacitor, all in a hand held together with hot glue.

## Accomplishments that we're proud of

- The core idea works end to end: **effort in, finger-by-finger movement out, and nothing moves without effort.**
- An AI agent that does real work. It **changes the therapy**, not just summarizes it, and shows its reasoning at every step.
- Every feature also works with just a laptop webcam, so anyone can try it.

## What we learned

- The hard part of rehab tech isn't moving a motor. It's deciding **when** the motor is allowed to move, and measuring it honestly.
- Calibrating to the person beats any fixed threshold; everyone's "full effort" is different.
- Build for failure first: watchdogs, self-healing camera, fallback modes. In a live demo, recovering from a failure matters as much as the features.

## What's next

- **Surface EMG** in place of capacitive pads, to read the muscle's electrical signal even when the hand can't visibly move yet.
- Moving the actuator into a **soft glove** worn on the patient's own weak hand.
- A pilot with physical and occupational therapists to check the metrics against standard clinical scores.
