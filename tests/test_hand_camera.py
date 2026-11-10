"""Hand + camera mode: the robot hand on USB copies the webcam, with no headband."""
from neurogrip.engine import Engine
from neurogrip.sources import HandBoard, IntentControl, MockSource
from neurogrip.store import MemoryStore
from neurogrip.vision import MockVision, VisionResult


class FakeBoard:
    connected = True

    def __init__(self):
        self.sent = []

    def send(self, cmd):
        self.sent.append(cmd)


class ClosedFist(MockVision):
    def latest(self, t_ms=None):
        return VisionResult({k: 1.0 for k in ("thumb", "index", "middle", "ring", "pinky")}, frame_id=1)


def test_always_on_robot_copies_the_camera_from_the_first_frame_without_trying():
    e = Engine(MockSource(control=IntentControl(always=True)), ClosedFist(), MemoryStore(), kind="camera")
    e.step()
    s = e.state()
    assert s["gate_open"] is True
    assert min(s["angles"]) > 0, "robot should copy the closed hand"


def test_hold_to_try_still_gates_when_not_always_on():
    e = Engine(MockSource(control=IntentControl()), ClosedFist(), MemoryStore(), kind="camera")
    for _ in range(150):
        e.step()
    assert e.state()["gate_open"] is False


def test_servo_commands_reach_the_hand_board():
    board = FakeBoard()
    e = Engine(MockSource(control=IntentControl(always=True), output=board), ClosedFist(), MemoryStore(), kind="camera")
    e.step()
    assert any(c.startswith("A,") and c != "A,0,0,0,0,0\n" for c in board.sent)
    assert e.state()["hand_connected"] is True


def test_no_hand_board_reports_none():
    e = Engine(MockSource(control=IntentControl()), MockVision(), MemoryStore(), kind="camera")
    assert e.state()["hand_connected"] is None


def test_hand_board_that_is_not_plugged_in_does_not_crash():
    board = HandBoard("COM_DOES_NOT_EXIST_NG")
    board.send("A,0,0,0,0,0\n")  # dropped quietly until the board shows up
    assert board.connected is False
