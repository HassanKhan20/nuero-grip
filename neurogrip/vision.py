"""Healthy-hand tracking (finger curls) and compensatory motion detection."""
import logging
import math
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# Curl calibration constants: tune with `python -m neurogrip.vision`
FINGER_OPEN_RATIO = 2.0   # tip-to-wrist / mcp-to-wrist when fully open
FINGER_RANGE = 1.0        # ratio drop from open to fist
THUMB_OPEN_RATIO = 1.3    # thumb-tip-to-pinky-mcp / wrist-to-middle-mcp when open
THUMB_RANGE = 0.7

STALE_S = 0.5  # camera result older than this = no hand
FINGERS = {"index": (5, 8), "middle": (9, 12), "ring": (13, 16), "pinky": (17, 20)}

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_URLS = {
    "hand_landmarker.task": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
    "pose_landmarker_lite.task": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
}


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def finger_curls(lm: list[tuple[float, float]]) -> dict[str, float]:
    d = math.dist
    curls = {}
    for name, (mcp, tip) in FINGERS.items():
        r = d(lm[tip], lm[0]) / max(d(lm[mcp], lm[0]), 1e-6)
        curls[name] = _clamp01((FINGER_OPEN_RATIO - r) / FINGER_RANGE)
    r_thumb = d(lm[4], lm[17]) / max(d(lm[0], lm[9]), 1e-6)
    return {
        "thumb": round(_clamp01((THUMB_OPEN_RATIO - r_thumb) / THUMB_RANGE), 3),
        "index": round(curls["index"], 3),
        "rest": round((curls["middle"] + curls["ring"] + curls["pinky"]) / 3, 3),
    }


class CompensationDetector:
    def __init__(self, calib_frames: int = 60, hike: float = 0.04, lean: float = 0.05):
        self.calib_frames, self.hike, self.lean = calib_frames, hike, lean
        self._calib: list[dict] = []
        self._base: dict | None = None

    def update(self, pose: dict[str, tuple[float, float]] | None) -> list[str]:
        if pose is None:
            return []
        if self._base is None:
            self._calib.append(pose)
            if len(self._calib) >= self.calib_frames:
                n = len(self._calib)
                self._base = {k: (sum(p[k][0] for p in self._calib) / n, sum(p[k][1] for p in self._calib) / n)
                              for k in ("l_sh", "r_sh")}
            return []
        out = []
        b = self._base
        if pose["l_sh"][1] < b["l_sh"][1] - self.hike or pose["r_sh"][1] < b["r_sh"][1] - self.hike:
            out.append("shoulder_hike")
        mid_now = (pose["l_sh"][0] + pose["r_sh"][0]) / 2
        mid_base = (b["l_sh"][0] + b["r_sh"][0]) / 2
        if abs(mid_now - mid_base) > self.lean:
            out.append("trunk_lean")
        return out


@dataclass
class VisionResult:
    curls: dict[str, float] | None
    compensation: list[str] = field(default_factory=list)
    pinch: float | None = None                  # thumb-index distance / hand size
    wrist: tuple[float, float] | None = None    # normalized image coords
    frame_id: int = 0                           # changes only when a new camera frame was processed
    t: float = 0.0                              # capture time, seconds


def pinch_distance(lm: list[tuple[float, float]]) -> float:
    return round(math.dist(lm[4], lm[8]) / max(math.dist(lm[0], lm[9]), 1e-6), 4)


HAND_CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
                    (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
                    (18, 19), (19, 20), (0, 17)]


class MockVision:
    """Curls follow a 4 s open/close cycle; shoulder hike for 1 s every 15 s."""

    def __init__(self, seed: int = 0, tremor_hz: float = 0.0):
        self.seed = seed
        self.tremor_hz = tremor_hz

    def latest(self, t_ms: int | None = None) -> VisionResult:
        t = time.monotonic() * 1000 if t_ms is None else t_ms
        s = t / 1000
        c = round(0.5 - 0.5 * math.cos(2 * math.pi * t / 4000), 3)
        comp = ["shoulder_hike"] if 10000 <= t % 15000 < 11000 else []
        wrist = (0.5 + 0.004 * math.sin(2 * math.pi * self.tremor_hz * s), 0.6)
        fatigue = max(0.35, 1 - 0.05 * (s % 30))  # tapping amplitude decays: bradykinesia demo
        pinch = round(0.15 + 0.6 * fatigue * (0.5 + 0.5 * math.sin(2 * math.pi * 2.2 * s)), 4)
        return VisionResult({"thumb": c, "index": c, "rest": c}, comp, pinch, wrist, int(t // 33), s)

    def jpeg(self) -> bytes | None:
        return None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def _model(name: str) -> str:
    path = MODEL_DIR / name
    if not path.exists():
        MODEL_DIR.mkdir(exist_ok=True)
        urllib.request.urlretrieve(MODEL_URLS[name], path)
    return str(path)


class CameraVision:
    """Webcam + MediaPipe Tasks in a background thread; latest() returns the newest result."""

    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index
        self._result = VisionResult(None, [])
        self._result_at = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jpeg: bytes | None = None
        self.available = True
        self.comp = CompensationDetector()

    def jpeg(self) -> bytes | None:
        """Latest annotated frame (mirrored, skeleton drawn), or None when the camera is stale/off."""
        with self._lock:
            return self._jpeg if time.monotonic() - self._result_at <= STALE_S else None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _set(self, result: VisionResult) -> None:
        with self._lock:
            self._result, self._result_at = result, time.monotonic()

    def latest(self, t_ms: int | None = None) -> VisionResult:
        with self._lock:
            if time.monotonic() - self._result_at > STALE_S:
                return VisionResult(None, [])  # frozen/unplugged camera must not keep a target alive
            return self._result

    def _run(self) -> None:
        try:
            self._loop()
        except Exception:
            logging.getLogger(__name__).exception("camera vision thread crashed")

    def _loop(self) -> None:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision as mpv

        hands = mpv.HandLandmarker.create_from_options(mpv.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_model("hand_landmarker.task")),
            running_mode=mpv.RunningMode.VIDEO, num_hands=1))
        pose = mpv.PoseLandmarker.create_from_options(mpv.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_model("pose_landmarker_lite.task")),
            running_mode=mpv.RunningMode.VIDEO))
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self.available = False
            logging.getLogger(__name__).error("camera %s could not be opened", self.camera_index)
            return
        t0 = time.monotonic()
        frame_id = 0
        while not self._stop.is_set():
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            frame = cv2.flip(frame, 1)  # mirror view: feels natural to the patient
            now = time.monotonic()
            ts = int((now - t0) * 1000)
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            h = hands.detect_for_video(img, ts)
            p = pose.detect_for_video(img, ts)
            curls = pinch = wrist = None
            if h.hand_landmarks:
                lm = [(l.x, l.y) for l in h.hand_landmarks[0]]
                curls, pinch, wrist = finger_curls(lm), pinch_distance(lm), lm[0]
            pose_pts = None
            if p.pose_landmarks:
                pl = p.pose_landmarks[0]
                if min(pl[11].visibility or 0, pl[12].visibility or 0) > 0.5:
                    pose_pts = {"l_sh": (pl[11].x, pl[11].y), "r_sh": (pl[12].x, pl[12].y)}
            comp = self.comp.update(pose_pts)
            frame_id += 1
            jpeg = self._annotate(cv2, frame, h.hand_landmarks[0] if h.hand_landmarks else None, pose_pts, comp)
            with self._lock:
                self._result = VisionResult(curls, comp, pinch, wrist, frame_id, now)
                self._result_at = now
                self._jpeg = jpeg
        cap.release()

    @staticmethod
    def _annotate(cv2, frame, hand, pose_pts, comp) -> bytes:
        hgt, wid = frame.shape[:2]
        if pose_pts:
            a = tuple(int(v) for v in (pose_pts["l_sh"][0] * wid, pose_pts["l_sh"][1] * hgt))
            b = tuple(int(v) for v in (pose_pts["r_sh"][0] * wid, pose_pts["r_sh"][1] * hgt))
            cv2.line(frame, a, b, (80, 80, 240) if comp else (200, 200, 200), 4)
        if hand:
            pts = [(int(l.x * wid), int(l.y * hgt)) for l in hand]
            for i, j in HAND_CONNECTIONS:
                cv2.line(frame, pts[i], pts[j], (120, 220, 60), 2)
            for pt in pts:
                cv2.circle(frame, pt, 4, (255, 255, 255), -1)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return buf.tobytes() if ok else b""


if __name__ == "__main__":
    import sys

    cam = CameraVision(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    cam.start()
    try:
        while True:
            print(cam.latest())
            time.sleep(0.2)
    except KeyboardInterrupt:
        cam.stop()
