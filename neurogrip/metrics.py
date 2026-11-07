"""Per-session metrics: reps, gate activation rate, compensation events, reaction latency."""
from collections import deque

from .gate import GateOutput
from .intent import IntentState
from .vision import VisionResult

REP_HIGH, REP_LOW = 0.6, 0.3
LATENCY_TIMEOUT_MS = 3000


class SessionMetrics:
    def __init__(self, difficulty: int = 3):
        self.reps = 0
        self._armed = False
        self._target_frames = 0
        self._open_frames = 0
        self._prev_comp: set[str] = set()
        self.compensation_count = 0
        self.events: deque[dict] = deque(maxlen=50)
        self._cue_ms: int | None = None
        self._prev_active = False
        self.latencies: list[int] = []
        self.tremor_hz = 0.0
        self.steadiness = 100.0
        self.difficulty = difficulty

    def start_latency_trial(self, cue_ms: int) -> None:
        self._cue_ms = cue_ms

    def update(self, t_ms: int, intent: IntentState, vision: VisionResult, gate: GateOutput) -> list[dict]:
        new: list[dict] = []
        peak = max(vision.curls.values()) if vision.curls else None

        if gate.target_set:
            self._target_frames += 1
            self._open_frames += gate.open
        if peak is not None:
            if gate.open and peak >= REP_HIGH:
                self._armed = True
            elif self._armed and peak <= REP_LOW:
                self.reps += 1
                self._armed = False

        comp = set(vision.compensation)
        for kind in sorted(comp - self._prev_comp):
            self.compensation_count += 1
            new.append({"t": t_ms, "type": kind})
        self._prev_comp = comp

        if self._cue_ms is not None:
            if intent.active and not self._prev_active and t_ms >= self._cue_ms:
                ms = t_ms - self._cue_ms
                self.latencies.append(ms)
                new.append({"t": t_ms, "type": "latency", "ms": ms})
                self._cue_ms = None
            elif t_ms - self._cue_ms > LATENCY_TIMEOUT_MS:
                new.append({"t": t_ms, "type": "latency_miss"})
                self._cue_ms = None
        self._prev_active = intent.active

        self.events.extend(new)
        return new

    def snapshot(self) -> dict:
        return {
            "reps": self.reps,
            "activation_rate": round(100 * self._open_frames / self._target_frames, 1) if self._target_frames else 0.0,
            "compensation_count": self.compensation_count,
            "events": list(self.events),
            "latency_ms_mean": round(sum(self.latencies) / len(self.latencies)) if self.latencies else None,
            "latency_trials": len(self.latencies),
            "tremor_hz": self.tremor_hz,
            "steadiness": self.steadiness,
            "difficulty": self.difficulty,
        }
