# nuero-grip
motor-intent rehabilitation platform. headband detects cognitive/motor intent, CV tracks healthy hand, gating engine controls robotic actuation. covers stroke, parkinson's, phantom limb, CP, and cognitive screening.

**Team: start with [docs/PROGRESS.md](docs/PROGRESS.md).** It covers what's done, what's next and the hardware checklist.

## run it

```powershell
py -3.10 -m venv .venv          # mediapipe needs Python 3.10–3.12
.venv\Scripts\pip install -r requirements.txt

# camera mode (default): real webcam CV, no ESP32. Hold the button or Space for intent
$env:NG_MODE = "camera"
.venv\Scripts\python app.py      # http://localhost:5000  (therapist/therapist, patient/patient)

# mock mode: no camera, no hardware, everything synthetic (demo backup)
$env:NG_MODE = "mock"
.venv\Scripts\python app.py

# hardware mode: ESP32 headband + wristband + 5 servos
$env:NG_MODE = "hardware"
$env:NG_SERIAL_PORT = "COM5"     # ESP32 port (Device Manager)
$env:NG_CAMERA = "0"             # webcam index
.venv\Scripts\python app.py
```

Optional keys (features show a clear error without them):

| env | used for |
|---|---|
| `NVIDIA_API_KEY` (+ `NEMOTRON_MODEL`) | Nemotron session agent and AI triage |
| `GEMINI_API_KEY` (+ `GEMINI_MODEL`) | "Explain my progress" in the patient view |
| `MONGODB_URI` | MongoDB Atlas storage (otherwise in memory) |
| `NG_MOCK_TREMOR` | mock tremor Hz (default 4.5, `0` = none) |

Tests: `.venv\Scripts\python -m pytest tests -q`

The first camera run downloads the MediaPipe models into `models/`, so it needs internet. Tune curl detection by running `.venv\Scripts\python -m neurogrip.vision`. Firmware and wiring are in [firmware/README.md](firmware/README.md).
