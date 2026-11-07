"""Serial line protocol shared with the ESP32 firmware."""
from dataclasses import dataclass

SERVO_MAX = 160
FINGERS = ("thumb", "index", "middle", "ring", "pinky")  # servo order on the wire


@dataclass
class SensorFrame:
    ms: int
    temple: int
    forearm: int
    ax: int
    ay: int
    az: int


def parse_sensor_line(line: str) -> SensorFrame | None:
    parts = line.strip().split(",")
    if len(parts) != 7 or parts[0] != "S":
        return None
    try:
        return SensorFrame(*(int(p) for p in parts[1:]))
    except ValueError:
        return None


def _clamp(v: int) -> int:
    return max(0, min(SERVO_MAX, int(v)))


def fmt_servo(thumb: int, index: int, middle: int, ring: int, pinky: int) -> str:
    return "A," + ",".join(str(_clamp(a)) for a in (thumb, index, middle, ring, pinky)) + "\n"


def fmt_buzzer(hz: int, ms: int) -> str:
    return f"B,{int(hz)},{int(ms)}\n"


def fmt_led(state: str) -> str:
    return f"L,{state}\n"
