# No-Hardware CV Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every feature demoable with only a laptop webcam: real hand/pose CV, virtual robotic hand mimicking the healthy hand, CV-based Parkinson's tremor + finger-tapping bradykinesia test, CV-based reaction test, rebuilt frontend.

**Architecture:** New `camera` source mode = real `CameraVision` + `MockSource` driven by an `IntentControl` (UI hold button / spacebar / auto-cycle) instead of the headband. VisionResult carries wrist position, thumb–index pinch distance, and frame id/time; the engine buffers new frames for CV tremor and the tapping test. Engine events go to listeners so the dashboard gets them instantly. CameraVision publishes an annotated JPEG served as MJPEG.

**Tech Stack:** unchanged (numpy, OpenCV, MediaPipe Tasks, Flask-SocketIO, vanilla JS + SVG).

**Spec:** `docs/spec.md` + user request 2026-11-07: "detection part parkinsons etc and cv for arm mimicking and every other feature without hardware, frontend, everything".

## Global Constraints
- `NG_MODE` = `mock` | `camera` | `hardware` (default `camera`); `NG_MOCK=1` still means `mock`.
- No new Python dependencies. Frontend: vanilla JS, Socket.IO 4.7.5 from cdnjs only.
- Results are labeled screening indicators, never diagnoses.
- All existing tests keep passing.

## Review Focus
1. No hand in view during the tapping test → result `{"error": "too few taps"}`, not a crash (Task 1 `test_tapping_too_few_taps`).
2. Camera mode, webcam missing → feed endpoint 404s, state shows no hand, app runs (Task 4 `test_video_feed_404_without_camera`).
3. Reaction cue pressed twice → one pending trial, not two (Task 3 `test_cue_twice_single_trial`).
4. Hold-to-try released mid-grip → gate closes, angles hold (covered by existing gate tests + Task 2 `test_intent_control_drives_mock_source`).
5. CV jitter on a still hand → tremor 0 Hz, not noise peaks (Task 1 `test_cv_tremor_zero_when_still`).

---

### Task 1: CV clinical analysis (pure functions)
**Files:** Create `neurogrip/clinical.py`, `tests/test_clinical.py`
**Produces:**
- `cv_tremor(ts: np.ndarray, xy: np.ndarray, fs: float = 30.0) -> tuple[float, float]` — (hz, amplitude). Resample to uniform `fs` with `np.interp`, detrend both axes, project on principal axis (SVD), return `(0.0, rms)` if rms < `CV_TREMOR_MIN_AMP = 0.0015` (normalized image units), else rFFT peak in 3–12 Hz.
- `analyze_tapping(ts: np.ndarray, pinch: np.ndarray) -> dict` — threshold = min + 0.5·range; taps = rising crossings; per-tap amplitude = max in each above-threshold segment − global min. Returns `{taps, rate_hz, mean_amplitude, decrement_pct, rhythm_cv, flag}` where `decrement_pct` = (mean amp first third − last third) / first third × 100, `rhythm_cv` = std/mean of inter-tap intervals, `flag` = "possible bradykinesia" if rate < 2.0 or decrement > 25 else "within typical range". < 3 taps → `{"error": "too few taps", "taps": n}`.
- [ ] Tests: `test_cv_tremor_detects_5hz` (30 fps, 5 s, 0.004 amp → |hz−5|<0.4), `test_cv_tremor_zero_when_still` (0.0005 noise → 0.0), `test_tapping_steady` (3 Hz, 10 s → taps 29–31, |rate−3|<0.2, |decrement|<10, flag typical), `test_tapping_decrement` (amp 1→0.4 → decrement > 30, flag bradykinesia), `test_tapping_too_few_taps`.
- [ ] RED → implement → GREEN → commit.

### Task 2: Vision + source extensions
**Files:** Modify `neurogrip/vision.py`, `neurogrip/sources.py`; tests in `tests/test_vision.py`, `tests/test_intent.py`
**Produces:**
- `VisionResult(curls, compensation=[], pinch: float|None = None, wrist: tuple[float,float]|None = None, frame_id: int = 0, t: float = 0.0)`.
- `pinch_distance(lm) -> float` = dist(4, 8) / dist(0, 9).
- `MockVision(seed=0, tremor_hz=0.0)`: frame_id = t_ms // 33 (≈30 fps), t = t_ms/1000, wrist = (0.5 + 0.004·sin(2π·tremor_hz·t), 0.6), pinch = 0.15 + 0.6·a·(0.5+0.5·sin(2π·2.2·t)) with a = max(0.35, 1 − 0.05·(t mod 30)).
- CameraVision: flips the frame horizontally (mirror view), fills pinch/wrist/frame_id/t, draws hand skeleton (green; red shoulders line when compensating) and stores JPEG (quality 70) → `jpeg() -> bytes | None`; `available: bool` False when the camera fails to open.
- `class IntentControl` with `held: bool = False`, `auto: bool = False`, `active(ms) -> bool` (held or (auto and ms % 6000 ≥ 3000)).
- `MockSource(tremor_hz=0.0, seed=0, control: IntentControl|None = None, realtime: bool = False)`: intent from `control.active(ms)` when given, else the old cycle; `realtime` → ms from `time.monotonic()`.
- [ ] Tests: `test_pinch_distance_open_vs_closed`, `test_mock_vision_wrist_tremor_and_frames`, `test_intent_control_drives_mock_source` (held False → no intent after calibration; held True → active), `test_realtime_clock`.
- [ ] RED → implement → GREEN → commit.

### Task 3: Engine — CV tremor, tapping test, randomized reaction cue, listeners, modes
**Files:** Modify `neurogrip/engine.py`, `neurogrip/metrics.py`; tests in `tests/test_engine.py`, `tests/test_metrics.py`
**Produces:**
- `SessionMetrics(difficulty=3, latency_response="intent"|"grip")`: grip response = rising edge of max curl ≥ 0.6. Snapshot adds `latencies` (last 10), `cv_tremor_hz`, `tremor_amp`, `tapping` (last result or None).
- Engine: `kind` attr (`mock`|`camera`|`hardware`, ctor kwarg, default `mock`); `control: IntentControl`; `listeners: list[Callable[[dict], None]]` called (outside the lock, exceptions logged) for every event; buffers `(t, wrist)` for new frame ids (deque 300) → every 25 frames `cv_tremor` over the last 5 s; tremor tile uses accel unless `kind == "camera"`.
- `start_tapping_test(duration_s: float = 10.0)`; while active, buffers `(t, pinch)`; when done sets `metrics.tapping` and emits `{"type": "tapping", **result}`. State: `tapping_active`, `tapping_remaining_s`.
- `cue_latency()` schedules a cue 1–3 s ahead (ignored while one is pending/active); at cue time sends buzzer+LED, starts the trial, emits `{"type": "cue"}`. State: `cue_pending`, `cue_active`.
- `make_engine()` honours `NG_MODE`; camera → `MockSource(control=..., realtime=True)` + `CameraVision`, latency_response "grip"; mock → realtime MockSource + MockVision(tremor_hz).
- [ ] Tests: `test_cv_tremor_from_mock_vision` (MockVision tremor 5 Hz, kind camera, 400 steps → |cv_tremor_hz−5|<0.6 and state tremor_hz uses it), `test_tapping_test_completes` (duration 3 s, mock steps → tapping result with taps ≥ 3, event emitted to listener), `test_cue_twice_single_trial`, `test_cue_fires_after_delay`, `test_grip_latency_response` (metrics unit), `test_listener_exception_does_not_break_step`.
- [ ] RED → implement → GREEN → commit.

### Task 4: App routes
**Files:** Modify `app.py`, `tests/test_app.py`
**Produces:** `POST /api/intent {held: bool}` and `POST /api/intent/auto {auto: bool}` (login; 400 in hardware mode), `POST /api/tapping` (therapist), `GET /video_feed` (login; MJPEG `multipart/x-mixed-replace; boundary=frame` at ≤ 15 fps; 404 if the vision has no frames), state includes `source_kind`. Events pushed via engine listener → `socketio.emit("event", e)`.
- [ ] Tests: `test_intent_hold_sets_control`, `test_video_feed_404_without_camera`, `test_tapping_requires_therapist`, `test_state_has_source_kind`.
- [ ] RED → implement → GREEN → commit.

### Task 5: Frontend rebuild
**Files:** Rewrite `templates/dashboard.html`, `static/dashboard.js`, `static/style.css`; add `static/hand.js` (virtual hand SVG)
- Hero: camera feed (placeholder in mock/offline) | virtual robotic hand (fingers curl from `angles`, glow green when gate open / red on compensation; mirrored + enlarged in phantom mode) | intent panel (meter, Hold-to-try button + spacebar, Auto toggle; hidden in hardware mode).
- Metric tiles, Parkinson's panel (tremor Hz + amplitude + source; finger-tap test button, countdown, results with flag), Cognitive panel (reaction test button, trial history bars, mean), incident log, agent trace, triage, patient explain.
- Full-screen overlays for both roles: reaction cue ("SQUEEZE!" + WebAudio beep) and tapping test countdown.
- [ ] `test_dashboard_renders_for_both_roles` still passes; manual: run `NG_MODE=mock` and `NG_MODE=camera`, check the page in a browser.
- [ ] Commit.
