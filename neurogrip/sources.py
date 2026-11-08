"""Sensor frame sources: real ESP32 over serial, or synthetic mock data."""
import logging
import math
import random
import time

from .protocol import SensorFrame, parse_sensor_line

FRAME_MS = 20  # 50 Hz
RECONNECT_DELAY_S = 1.0
MOCK_EFFORT_DROP = 0.36   # simulated touch change at full effort (fraction of baseline)
MOCK_RAMP_PER_S = 0.3     # how fast simulated effort builds/fades: ~1.2 s to full
log = logging.getLogger(__name__)


class IntentControl:
    """Stand-in for the headband when there is no hardware: UI hold button / spacebar, or auto-cycle."""

    def __init__(self):
        self.held = False
        self.auto = False

    def active(self, ms: int) -> bool:
        return self.held or (self.auto and (ms % 6000) >= 3000)


class MockSource:
    """Synthetic headband + wristband. Intent alternates 3 s rest / 3 s on, or follows an IntentControl."""

    def __init__(self, tremor_hz: float = 0.0, seed: int = 0, control: IntentControl | None = None,
                 realtime: bool = False):
        self.tremor_hz = tremor_hz
        self.rng = random.Random(seed)
        self.control = control
        self.realtime = realtime
        self._t0 = time.monotonic()
        self._drop = 0.0
        self._n = 0  # sample counter: the simulated wristband samples at exactly 50 Hz
        self.ms = 0
        self.sent: list[str] = []

    def read(self) -> SensorFrame:
        prev = self.ms
        self.ms = int((time.monotonic() - self._t0) * 1000) if self.realtime else self.ms + FRAME_MS
        intent = self.control.active(self.ms) if self.control else (self.ms % 6000) >= 3000
        # the touch signal ramps like a real muscle effort instead of snapping on/off
        target = MOCK_EFFORT_DROP if intent else 0.0
        step = MOCK_RAMP_PER_S * max(0, self.ms - prev) / 1000
        self._drop += max(-step, min(step, target - self._drop))
        base = round(400 * (1 - self._drop))
        temple = base + self.rng.randint(-3, 3)
        forearm = base + self.rng.randint(-3, 3)
        self._n += 1
        t = self._n * FRAME_MS / 1000  # uniform sample clock, independent of loop jitter
        az = 1000 + 60 * math.sin(2 * math.pi * self.tremor_hz * t) if self.tremor_hz else 1000
        return SensorFrame(self.ms, temple, forearm,
                           self.rng.randint(-3, 3), self.rng.randint(-3, 3),
                           int(az) + self.rng.randint(-3, 3))

    def send(self, cmd: str) -> None:
        self.sent.append(cmd)
        if len(self.sent) > 1000:
            del self.sent[:500]


class SerialSource:
    def __init__(self, port: str, baud: int = 115200):
        self.port, self.baud = port, baud
        self.ser = self._open()

    def _open(self):
        import serial

        return serial.Serial(self.port, self.baud, timeout=1)

    def _reconnect(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass
        while True:
            time.sleep(RECONNECT_DELAY_S)
            try:
                self.ser = self._open()
                log.info("serial reconnected on %s", self.port)
                return
            except Exception as e:
                log.warning("serial reconnect failed: %s", e)

    def read(self) -> SensorFrame:
        while True:
            try:
                raw = self.ser.readline()
            except Exception as e:  # SerialException / OSError when the cable is pulled
                log.warning("serial read failed (%s); reconnecting", e)
                self._reconnect()
                continue
            line = raw.decode("ascii", errors="ignore")
            if line.startswith("#"):  # board info: servo angles written, headband link up/lost
                log.info("board: %s", line.strip())
                continue
            frame = parse_sensor_line(line)
            if frame is not None:
                return frame

    def send(self, cmd: str) -> None:
        try:
            self.ser.write(cmd.encode("ascii"))
        except Exception as e:
            log.warning("serial write failed: %s", e)
