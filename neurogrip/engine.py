"""Main loop: sensors + vision -> intent gate -> servos/biofeedback -> metrics."""
import json
import logging
import math
import os
import queue
import random
import threading
import time
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import Callable

import numpy as np

from .clinical import analyze_tapping, cv_tremor
from .gate import CONTROL_MODES, GRIPS, THRESHOLDS, Gate
from .intent import CAL_FRACTIONS, IntentDetector, SiteRange, calibrate_from
from .metrics import SessionMetrics
from .protocol import fmt_buzzer, fmt_led, fmt_servo
from .signals import steadiness, tremor_frequency
from .sources import FRAME_MS, HandBoard, IntentControl, MockSource, SerialSource
from .store import make_store
from .vision import CameraVision, MockVision

log = logging.getLogger(__name__)

MODES = ["stroke", "parkinsons", "phantom", "cp", "cognitive"]
KINDS = ["mock", "camera", "hardware"]
DEFAULT_LEVEL = 3
SENSOR_TIMEOUT_S = 1.0
CV_TREMOR_WINDOW_S = 5.0
CUE_DELAY_MS = (1000, 3000)
CAL_RELAX_MS, CAL_SQUEEZE_MS = 2000, 3000


class Engine:
    def __init__(self, source, vision, store, patient_id: str = "demo", kind: str = "mock"):
        self.source, self.vision, self.store, self.patient_id = source, vision, store, patient_id
        self.kind = kind
        self.control: IntentControl = getattr(source, "control", None) or IntentControl()
        self._latency_response = "grip" if kind == "camera" else "intent"
        self.intent = IntentDetector(threshold=THRESHOLDS[DEFAULT_LEVEL - 1])
        self.gate = Gate()
        self.metrics = SessionMetrics(difficulty=DEFAULT_LEVEL, latency_response=self._latency_response)
        self.mode = "stroke"
        self.listeners: list[Callable[[dict], None]] = []
        self.new_events: deque[dict] = deque(maxlen=200)
        self._mags: deque[float] = deque(maxlen=256)
        self._pad_hist: deque[tuple[int, int]] = deque(maxlen=16)
        self._cv_hist: deque[tuple[float, float, float]] = deque(maxlen=400)
        self._last_frame_id = -1
        self._frames = 0
        self._t_ms = 0
        self._last_led: str | None = None
        self._last_frame_at = 0.0
        self._cue_at_ms: int | None = None
        self._cal_phase: str | None = None
        self._cal_until = 0
        self._cal_relaxed: list[tuple[int, int]] = []
        self._cal_effort: list[tuple[int, int]] = []
        self._touch = {"temple": 0, "forearm": 0, "temple_drop": 0.0, "forearm_drop": 0.0}
        self._tap_start_ms: int | None = None
        self._tap_duration_ms = 10000
        self._tap_samples: list[tuple[float, float]] = []
        self._outbox: queue.Queue = queue.Queue(maxsize=1000)
        self._writer: threading.Thread | None = None
        self._lock = threading.RLock()
        self._live = {"angles": (0, 0, 0, 0, 0), "gate_open": False, "intent_strength": 0.0,
                      "intent_active": False, "calibrated": False, "curls": None, "led": "O"}

    def send(self, cmd: str) -> None:
        with self._lock:
            self.source.send(cmd)

    smooth_frames = 1  # >1: moving average of the pad readings (hardware: tames +-2-count touch jitter)

    def _smooth(self, f):
        if self.smooth_frames <= 1:
            return f
        if f.temple <= 0 or f.forearm < 0:  # link lost: pass it through untouched, restart the window
            self._pad_hist.clear()
            return f
        self._pad_hist.append((f.temple, f.forearm))
        n = len(self._pad_hist)
        return replace(f, temple=round(sum(v[0] for v in self._pad_hist) / n, 1),
                       forearm=round(sum(v[1] for v in self._pad_hist) / n, 1))

    def step(self) -> dict:
        f = self._smooth(self.source.read())
        self._last_frame_at = time.monotonic()
        with self._lock:
            self._t_ms = f.ms
            istate = self.intent.update(f)
            if self.control.always:  # hand + camera, no headband: the robot copies the camera all the time
                istate = replace(istate, calibrated=True, active=True, strength=1.0, link_lost=False)
            self._touch = {"temple": f.temple, "forearm": f.forearm,
                           "temple_drop": istate.temple_drop, "forearm_drop": istate.forearm_drop}
            cal_events = self._calibration_step(f)
            v = self.vision.latest(f.ms)
            g = self.gate.step(istate, v)
            events = self.metrics.update(f.ms, istate, v, g) + cal_events

            self.source.send(fmt_servo(*g.angles))
            if g.led != self._last_led:
                self.source.send(fmt_led(g.led))
                self._last_led = g.led
            if g.buzzer_hz and self._frames % 5 == 0:
                self.source.send(fmt_buzzer(g.buzzer_hz, 110))

            self._mags.append(math.sqrt(f.ax ** 2 + f.ay ** 2 + f.az ** 2))
            if v.frame_id != self._last_frame_id:
                self._last_frame_id = v.frame_id
                if v.wrist is not None:
                    self._cv_hist.append((v.t, v.wrist[0], v.wrist[1]))
                if self._tap_start_ms is not None and v.pinch is not None:
                    self._tap_samples.append((v.t, v.pinch))
            self._frames += 1
            if self._frames % 25 == 0:
                self._update_tremor()

            if self._cue_at_ms is not None and f.ms >= self._cue_at_ms:
                self._cue_at_ms = None
                self.source.send(fmt_buzzer(1500, 150))
                self.source.send(fmt_led("G"))
                self._last_led = "G"
                self.metrics.start_latency_trial(f.ms)
                events.append({"t": f.ms, "type": "cue"})

            if self._tap_start_ms is not None and f.ms - self._tap_start_ms >= self._tap_duration_ms:
                result = self._finish_tapping()
                events.append({"t": f.ms, "type": "tapping", **result})

            for e in events:
                self._persist({**e, "patient_id": self.patient_id, "mode": self.mode})
            self.new_events.extend(events)
            self._live = {"angles": g.angles, "gate_open": g.open, "intent_strength": round(istate.strength, 2),
                          "intent_active": istate.active, "calibrated": istate.calibrated,
                          "curls": v.curls, "led": g.led}
            live = self._live
        for e in events:  # outside the lock: listeners do socket I/O
            for fn in list(self.listeners):
                try:
                    fn(e)
                except Exception:
                    log.exception("event listener failed")
        return live

    def _calibration_step(self, f) -> list[dict]:
        if self._cal_phase is None:
            return []
        (self._cal_relaxed if self._cal_phase == "relax" else self._cal_effort).append((f.temple, f.forearm))
        if f.ms < self._cal_until:
            return []
        if self._cal_phase == "relax":
            self._cal_phase, self._cal_until = "squeeze", f.ms + CAL_SQUEEZE_MS
            return [{"t": f.ms, "type": "calibration_squeeze"}]
        self._cal_phase = None
        try:
            base, full = calibrate_from(self._cal_relaxed, self._cal_effort)
        except ValueError as e:
            return [{"t": f.ms, "type": "calibration_failed", "reason": str(e)}]
        self.intent.set_calibration(base, full)
        self._save_range(full)
        return [{"t": f.ms, "type": "calibrated",
                 "temple_range_pct": round(full[0] * 100, 1), "forearm_range_pct": round(full[1] * 100, 1)}]

    cal_file: str | None = None  # where this wearer's range is kept across restarts (hardware only)

    def _save_range(self, full) -> None:
        if not self.cal_file:
            return
        try:
            Path(self.cal_file).write_text(json.dumps({"full": list(full), "directions": list(full.directions),
                                                      "noise": list(getattr(full, "noise", (0.0, 0.0)))}))
        except OSError as e:
            log.warning("could not save calibration: %s", e)

    def load_range(self, path: str) -> bool:
        """Restore the last calibration (headband is re-zeroed automatically on the first relaxed frames)."""
        self.cal_file = path
        try:
            d = json.loads(Path(path).read_text())
            self.intent.load_range(SiteRange(tuple(d["full"]), tuple(d["directions"]), tuple(d.get("noise", (0, 0)))))
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def start_calibration(self) -> None:
        """Relax for 2 s, then squeeze as hard as possible for 3 s: scales intent to this wearer."""
        with self._lock:
            self._cal_phase, self._cal_until = "relax", self._t_ms + CAL_RELAX_MS
            self._cal_relaxed, self._cal_effort = [], []

    def _update_tremor(self) -> None:
        if len(self._mags) >= 128:
            arr = np.array(self._mags)
            self.metrics.tremor_hz = tremor_frequency(arr)
            self.metrics.steadiness = steadiness(arr)
        if len(self._cv_hist) >= 30:
            hist = np.array(self._cv_hist)
            recent = hist[hist[:, 0] >= hist[-1, 0] - CV_TREMOR_WINDOW_S]
            hz, amp = cv_tremor(recent[:, 0], recent[:, 1:])
            self.metrics.cv_tremor_hz, self.metrics.tremor_amp = hz, amp
        if self.kind == "camera":  # no wristband: the camera is the tremor sensor
            self.metrics.tremor_hz = self.metrics.cv_tremor_hz
            self.metrics.steadiness = round(max(0.0, 100.0 - self.metrics.tremor_amp * 5000), 1)

    def _finish_tapping(self) -> dict:
        samples, self._tap_samples, self._tap_start_ms = self._tap_samples, [], None
        if len(samples) < 2:
            result = {"error": "too few taps", "taps": 0}
        else:
            arr = np.array(samples)
            result = analyze_tapping(arr[:, 0], arr[:, 1])
        self.metrics.tapping = result
        return result

    def _persist(self, doc: dict) -> None:
        """Queue an event for the store; a slow or dead database must never stall the servo loop."""
        if self._writer is None:
            self._writer = threading.Thread(target=self._write_events, daemon=True)
            self._writer.start()
        try:
            self._outbox.put_nowait(doc)
        except queue.Full:
            log.warning("event queue full; dropping event")

    def _write_events(self) -> None:
        while True:
            doc = self._outbox.get()
            try:
                self.store.log_event(doc)
            except Exception as e:
                log.warning("could not store event: %s", e)

    def state(self) -> dict:
        with self._lock:
            tapping_left = 0.0
            if self._tap_start_ms is not None:
                tapping_left = max(0.0, (self._tap_duration_ms - (self._t_ms - self._tap_start_ms)) / 1000)
            return {**self.metrics.snapshot(), **self._live, "mode": self.mode, "patient_id": self.patient_id,
                    "sensors_ok": time.monotonic() - self._last_frame_at < SENSOR_TIMEOUT_S,
                    "source_kind": self.kind,
                    "control_mode": self.gate.control, "grip": self.gate.grip,
                    "touch": dict(self._touch),
                    "range_calibrated": self.intent.range_calibrated,
                    "intent_debug": self.intent.debug(),
                    "calibration_phase": self._cal_phase,
                    "calibration_remaining_s": round(max(0, self._cal_until - self._t_ms) / 1000, 1)
                    if self._cal_phase else 0.0,
                    "camera_ok": getattr(self.vision, "available", True),
                    "intent_held": self.control.held, "intent_auto": self.control.auto,
                    "intent_always": self.control.always,
                    "hand_connected": getattr(getattr(self.source, "output", None), "connected", None),
                    "cue_pending": self._cue_at_ms is not None,
                    "cue_active": self.metrics.trial_active,
                    "tapping_active": self._tap_start_ms is not None,
                    "tapping_remaining_s": round(tapping_left, 1)}

    def set_difficulty(self, level: int) -> int:
        level = max(1, min(5, int(level)))
        with self._lock:
            self.intent.threshold = THRESHOLDS[level - 1]
            self.intent.fraction = CAL_FRACTIONS[level - 1]
            self.metrics.difficulty = level
        return level

    def post_event(self, event: dict) -> dict:
        """Add an out-of-loop event (e.g. an AI agent alert) to the activity log, store and live socket."""
        with self._lock:
            e = {"t": self._t_ms, **event}
            self.metrics.events.append(e)
            self.new_events.append(e)
            self._persist({**e, "patient_id": self.patient_id, "mode": self.mode})
        for fn in list(self.listeners):
            try:
                fn(e)
            except Exception:
                log.exception("event listener failed")
        return e

    def cue_latency(self) -> None:
        """Schedule a reaction cue 1-3 s from now (random so the patient can't anticipate it)."""
        with self._lock:
            if self._cue_at_ms is not None or self.metrics.trial_active:
                return
            self._cue_at_ms = self._t_ms + random.randint(*CUE_DELAY_MS)

    def start_tapping_test(self, duration_s: float = 10.0) -> None:
        with self._lock:
            self._tap_start_ms = self._t_ms
            self._tap_duration_ms = int(duration_s * 1000)
            self._tap_samples = []

    def set_control(self, mode: str, grip: str | None = None) -> None:
        """mirror = copy the healthy hand (camera); intent = intent strength alone drives a grip."""
        if mode not in CONTROL_MODES:
            raise ValueError(f"control mode must be one of {CONTROL_MODES}")
        if grip is not None and grip not in GRIPS:
            raise ValueError(f"grip must be one of {GRIPS}")
        with self._lock:
            self.gate.control = mode
            if grip is not None:
                self.gate.grip = grip

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode}")
        with self._lock:
            self.mode = mode

    def end_session(self) -> str:
        with self._lock:
            doc = {"patient_id": self.patient_id, "mode": self.mode, **self.metrics.snapshot()}
            self.metrics = SessionMetrics(difficulty=self.metrics.difficulty, latency_response=self._latency_response)
        return self.store.save_session(doc)  # outside the lock: network I/O

    def run_forever(self, stop: threading.Event) -> None:
        self.vision.start()
        paced = isinstance(self.source, MockSource)
        while not stop.is_set():
            try:
                self.step()
            except Exception:
                log.exception("engine step failed")
                time.sleep(0.5)
            if paced:
                time.sleep(FRAME_MS / 1000)
        self.vision.stop()


def source_kind_from_env() -> str:
    if os.environ.get("NG_MOCK") == "1":
        return "mock"
    kind = os.environ.get("NG_MODE", "camera").lower()
    if kind not in KINDS:
        raise ValueError(f"NG_MODE must be one of {KINDS}")
    return kind


def default_control(kind: str) -> str:
    """Hardware runs the core loop (headband -> fingers) by default; camera/mock show mirroring."""
    return "intent" if kind == "hardware" else "mirror"


def make_engine() -> Engine:
    store = make_store()
    kind = source_kind_from_env()
    camera = int(os.environ.get("NG_CAMERA", "0"))
    if kind == "mock":
        tremor = float(os.environ.get("NG_MOCK_TREMOR", "4.5"))
        engine = Engine(MockSource(tremor_hz=tremor, realtime=True), MockVision(tremor_hz=tremor), store, kind="mock")
    elif kind == "camera":
        # optional robot hand on USB with no headband (NG_HAND_PORT); NG_ALWAYS_ON=1: it copies the camera
        # all the time instead of only while Hold to try / Space is held
        hand = HandBoard(os.environ["NG_HAND_PORT"]) if os.environ.get("NG_HAND_PORT") else None
        control = IntentControl(always=os.environ.get("NG_ALWAYS_ON") == "1")
        engine = Engine(MockSource(control=control, realtime=True, output=hand), CameraVision(camera), store,
                        kind="camera")
    else:
        engine = Engine(SerialSource(os.environ["NG_SERIAL_PORT"]), CameraVision(camera), store, kind="hardware")
    engine.set_control(os.environ.get("NG_CONTROL", default_control(kind)), os.environ.get("NG_GRIP", "fist"))
    if kind == "hardware":
        engine.smooth_frames = int(os.environ.get("NG_SMOOTH", "6"))  # 6 frames = 120 ms at 50 Hz
        engine._pad_hist = deque(maxlen=max(1, engine.smooth_frames))
        engine.load_range(os.environ.get("NG_CAL_FILE", str(Path(__file__).resolve().parent.parent / ".ng_calibration.json")))
    if os.environ.get("NG_LEVEL"):  # starting difficulty 1-5 (1 = lowest trigger)
        engine.set_difficulty(int(os.environ["NG_LEVEL"]))
    return engine
