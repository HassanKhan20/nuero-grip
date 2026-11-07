"""Sensor frame sources: real ESP32 over serial, or synthetic mock data."""
import math
import random

from .protocol import SensorFrame, parse_sensor_line

FRAME_MS = 20  # 50 Hz


class MockSource:
    """Synthetic headband + wristband. Alternates 3 s rest / 3 s intent."""

    def __init__(self, tremor_hz: float = 0.0, seed: int = 0):
        self.tremor_hz = tremor_hz
        self.rng = random.Random(seed)
        self.ms = 0
        self.sent: list[str] = []

    def read(self) -> SensorFrame:
        self.ms += FRAME_MS
        intent = (self.ms % 6000) >= 3000
        base = 280 if intent else 400
        temple = base + self.rng.randint(-3, 3)
        forearm = base + self.rng.randint(-3, 3)
        t = self.ms / 1000
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
        import serial

        self.ser = serial.Serial(port, baud, timeout=1)

    def read(self) -> SensorFrame:
        while True:
            line = self.ser.readline().decode("ascii", errors="ignore")
            frame = parse_sensor_line(line)
            if frame is not None:
                return frame

    def send(self, cmd: str) -> None:
        self.ser.write(cmd.encode("ascii"))
