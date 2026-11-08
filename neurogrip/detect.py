"""Live detection rules: watch the engine's state and events and turn findings into incidents.

Device rules (sensor stream, camera) open and close incidents on their own. Clinical rules
(tremor, slow or missed reactions, tapping slowdown) open screening flags for a therapist to review.
None of these are diagnoses.
"""
from .incidents import IncidentLog

SENSOR_LOSS_S = 2.0       # stream silent this long -> critical incident
RECOVER_S = 2.0           # healthy this long -> auto-resolve device incidents
TREMOR_BAND = (3.5, 7.5)  # Hz range treated as pathological tremor
PARKINSON_BAND = (4.0, 6.0)
SLOW_REACTION_MS = 1000
MISSED_CUES = 2


class Detector:
    def __init__(self, incidents: IncidentLog, patient_id: str = "demo", sustain_s: float = 5.0):
        self.incidents, self.patient_id, self.sustain_s = incidents, patient_id, sustain_s
        self._since: dict[str, float | None] = {}
        self._fired: set[str] = set()  # episodes already reported: one incident update per episode
        self._latencies: list[int] = []
        self._misses = 0

    def _held(self, name: str, cond: bool, now: float) -> float:
        """Seconds `cond` has been continuously true (0 when false)."""
        if not cond:
            self._since[name] = None
            self._fired.discard(name)
            return 0.0
        if self._since.get(name) is None:
            self._since[name] = now
        return now - self._since[name]

    def _first(self, name: str) -> bool:
        """True the first time a sustained condition is reported in this episode."""
        if name in self._fired:
            return False
        self._fired.add(name)
        return True

    def _device(self, kind: str, failing: bool, now: float, after_s: float, device: str,
                title: str, severity: str, detail: str, restored: str) -> None:
        scope = {"device": device}
        if self._held(kind + ":bad", failing, now) >= after_s and self._first(kind + ":bad"):
            self.incidents.raise_incident(kind, title, severity, "device", scope, detail)
        if self._held(kind + ":ok", not failing, now) >= RECOVER_S and self._first(kind + ":ok"):
            self.incidents.auto_resolve(kind, scope, restored)

    def check(self, state: dict, now: float) -> None:
        patient = state.get("patient_id") or self.patient_id
        hardware = state.get("source_kind") == "hardware"
        self._device("sensor_loss", not state.get("sensors_ok", True), now, SENSOR_LOSS_S,
                     "ESP32 headband" if hardware else "sensor stream",
                     "Sensor stream lost", "critical",
                     f"No sensor frames for {SENSOR_LOSS_S:.0f}+ s. Servos fall back to neutral (firmware watchdog).",
                     "Sensor stream restored.")
        if state.get("source_kind") != "mock":
            self._device("camera_loss", not state.get("camera_ok", True), now, self.sustain_s, "camera",
                         "Camera offline", "high",
                         "No camera frames: mirroring, CV tremor and the tapping test are unavailable.",
                         "Camera frames restored.")

        hz = float(state.get("tremor_hz") or 0.0)
        in_band = TREMOR_BAND[0] <= hz <= TREMOR_BAND[1]
        if self._held("tremor", in_band, now) >= self.sustain_s and self._first("tremor"):
            if PARKINSON_BAND[0] <= hz <= PARKINSON_BAND[1]:
                where = "inside the 4-6 Hz band typical of Parkinsonian rest tremor"
            else:
                where = "outside the 4-6 Hz Parkinsonian band (consider essential or physiologic tremor)"
            self.incidents.raise_incident(
                "tremor", f"Tremor {hz:.1f} Hz detected", "medium", "clinical", {"patient": patient},
                f"{hz:.1f} Hz oscillation sustained {self.sustain_s:.0f}+ s, {where}. "
                f"Steadiness {state.get('steadiness', 100)}/100. Screening flag, not a diagnosis.")

    def on_event(self, e: dict) -> None:
        scope = {"patient": e.get("patient_id") or self.patient_id}
        kind = e.get("type")
        if kind == "latency":
            self._latencies = (self._latencies + [int(e["ms"])])[-3:]
            mean = round(sum(self._latencies) / len(self._latencies))
            if len(self._latencies) >= 2 and mean > SLOW_REACTION_MS:
                self.incidents.raise_incident(
                    "slow_reaction", "Slow reaction time", "medium", "clinical", scope,
                    f"Mean {mean} ms over the last {len(self._latencies)} cues (typical < {SLOW_REACTION_MS} ms).")
        elif kind == "latency_miss":
            self._misses += 1
            if self._misses >= MISSED_CUES:
                self.incidents.raise_incident(
                    "missed_cues", "Missed reaction cues", "medium", "clinical", scope,
                    f"{self._misses} cues with no response within 3 s. Check attention, fatigue or sensor fit.")
        elif kind == "tapping" and e.get("flag") == "possible bradykinesia":
            self.incidents.raise_incident(
                "bradykinesia", "Finger-tap slowdown", "medium", "clinical", scope,
                f"{e.get('taps')} taps at {e.get('rate_hz')} taps/s, amplitude decrement {e.get('decrement_pct')}% "
                "(flag: < 2 taps/s or > 25% decrement). Screening flag, not a diagnosis.")
