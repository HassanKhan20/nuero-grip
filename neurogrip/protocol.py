"""Serial line protocol shared with the ESP32 firmware."""
from dataclasses import dataclass

SERVO_MAX = 160


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


def fmt_servo(thumb: int, index: int, rest: int) -> str:
    return f"A,{_clamp(thumb)},{_clamp(index)},{_clamp(rest)}\n"


def fmt_buzzer(hz: int, ms: int) -> str:
    return f"B,{int(hz)},{int(ms)}\n"


def fmt_led(state: str) -> str:
    return f"L,{state}\n"
