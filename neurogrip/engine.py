"""Main loop: sensors + vision -> intent gate -> servos/biofeedback -> metrics."""
import logging
import math
import os
import threading
import time
from collections import deque

import numpy as np

from .gate import THRESHOLDS, Gate
from .intent import IntentDetector
from .metrics import SessionMetrics
from .protocol import fmt_buzzer, fmt_led, fmt_servo
from .signals import steadiness, tremor_frequency
from .sources import FRAME_MS, MockSource, SerialSource
from .store import make_store
from .vision import CameraVision, MockVision

log = logging.getLogger(__name__)

MODES = ["stroke", "parkinsons", "phantom", "cp", "cognitive"]
DEFAULT_LEVEL = 3


class Engine:
    def __init__(self, source, vision, store, patient_id: str = "demo"):
        self.source, self.vision, self.store, self.patient_id = source, vision, store, patient_id
        self.intent = IntentDetector(threshold=THRESHOLDS[DEFAULT_LEVEL - 1])
        self.gate = Gate()
        self.metrics = SessionMetrics(difficulty=DEFAULT_LEVEL)
        self.mode = "stroke"
        self.new_events: deque[dict] = deque(maxlen=200)
        self._mags: deque[float] = deque(maxlen=256)
        self._frames = 0
        self._t_ms = 0
        self._last_led: str | None = None
        self._lock = threading.RLock()
        self._live = {"angles": (0, 0, 0), "gate_open": False, "intent_strength": 0.0,
                      "intent_active": False, "calibrated": False, "curls": None, "led": "O",
                      "compensation": []}

    def send(self, cmd: str) -> None:
        with self._lock:
            self.source.send(cmd)

    def step(self) -> dict:
        f = self.source.read()
        with self._lock:
            self._t_ms = f.ms
            istate = self.intent.update(f)
            v = self.vision.latest(f.ms)
            g = self.gate.step(istate, v)
            events = self.metrics.update(f.ms, istate, v, g)

            self.source.send(fmt_servo(*g.angles))
            if g.led != self._last_led:
                self.source.send(fmt_led(g.led))
                self._last_led = g.led
            if g.buzzer_hz and self._frames % 5 == 0:
                self.source.send(fmt_buzzer(g.buzzer_hz, 110))

            self._mags.append(math.sqrt(f.ax ** 2 + f.ay ** 2 + f.az ** 2))
            self._frames += 1
            if self._frames % 25 == 0 and len(self._mags) >= 128:
                arr = np.array(self._mags)
                self.metrics.tremor_hz = tremor_frequency(arr)
                self.metrics.steadiness = steadiness(arr)

            for e in events:
                self.store.log_event({**e, "patient_id": self.patient_id, "mode": self.mode})
            self.new_events.extend(events)
            self._live = {"angles": g.angles, "gate_open": g.open, "intent_strength": round(istate.strength, 2),
                          "intent_active": istate.active, "calibrated": istate.calibrated,
                          "curls": v.curls, "led": g.led, "compensation": list(v.compensation)}
            return self._live

    def state(self) -> dict:
        with self._lock:
            return {**self.metrics.snapshot(), **self._live, "mode": self.mode, "patient_id": self.patient_id}

    def set_difficulty(self, level: int) -> int:
        level = max(1, min(5, int(level)))
        with self._lock:
            self.intent.threshold = THRESHOLDS[level - 1]
            self.metrics.difficulty = level
        return level

    def cue_latency(self) -> None:
        with self._lock:
            self.source.send(fmt_buzzer(1500, 150))
            self.source.send(fmt_led("G"))
            self._last_led = "G"
            self.metrics.start_latency_trial(self._t_ms)

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode}")
        with self._lock:
            self.mode = mode

    def end_session(self) -> str:
        with self._lock:
            doc = {"patient_id": self.patient_id, "mode": self.mode, **self.metrics.snapshot()}
            session_id = self.store.save_session(doc)
            self.metrics = SessionMetrics(difficulty=self.metrics.difficulty)
            return session_id

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


def make_engine() -> Engine:
    store = make_store()
    if os.environ.get("NG_MOCK") == "1":
        return Engine(MockSource(tremor_hz=float(os.environ.get("NG_MOCK_TREMOR", "4.5"))), MockVision(), store)
    return Engine(SerialSource(os.environ["NG_SERIAL_PORT"]), CameraVision(int(os.environ.get("NG_CAMERA", "0"))), store)
