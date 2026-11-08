"""Healthy-hand tracking: finger curls, pinch distance and wrist position from the webcam."""
import logging
import math
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Curl calibration constants: tune with `python -m neurogrip.vision`
FINGER_OPEN_RATIO = 2.0   # tip-to-wrist / mcp-to-wrist when fully open
FINGER_RANGE = 1.0        # ratio drop from open to fist
THUMB_OPEN_RATIO = 1.3    # thumb-tip-to-pinky-mcp / wrist-to-middle-mcp when open
THUMB_RANGE = 0.7

STALE_S = 0.5  # camera result older than this = no hand
CAMERA_RETRY_S = 2.0  # wait before reopening a camera that failed or stopped sending frames
NO_FRAME_S = 2.0  # no frame for this long = camera lost (unplugged, grabbed by another app, sleep)
FINGERS = {"index": (5, 8), "middle": (9, 12), "ring": (13, 16), "pinky": (17, 20)}

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_URLS = {
    "hand_landmarker.task": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
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
    out = {"thumb": round(_clamp01((THUMB_OPEN_RATIO - r_thumb) / THUMB_RANGE), 3)}
    out.update({k: round(v, 3) for k, v in curls.items()})
    return out


@dataclass
class VisionResult:
    curls: dict[str, float] | None
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
    """Curls follow a 4 s open/close cycle."""

    def __init__(self, seed: int = 0, tremor_hz: float = 0.0):
        self.seed = seed
        self.tremor_hz = tremor_hz

    def latest(self, t_ms: int | None = None) -> VisionResult:
        t = time.monotonic() * 1000 if t_ms is None else t_ms
        s = t / 1000
        # fingers close in a slight wave (thumb leads, pinky lags) so each servo visibly moves on its own
        curls = {k: round(0.5 - 0.5 * math.cos(2 * math.pi * (t - 120 * i) / 4000), 3)
                 for i, k in enumerate(("thumb", "index", "middle", "ring", "pinky"))}
        wrist = (0.5 + 0.004 * math.sin(2 * math.pi * self.tremor_hz * s), 0.6)
        fatigue = max(0.35, 1 - 0.05 * (s % 30))  # tapping amplitude decays: bradykinesia demo
        pinch = round(0.15 + 0.6 * fatigue * (0.5 + 0.5 * math.sin(2 * math.pi * 2.2 * s)), 4)
        return VisionResult(curls, pinch, wrist, int(t // 33), s)

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
        self._result = VisionResult(None)
        self._result_at = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._jpeg: bytes | None = None
        self.available = True

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
                return VisionResult(None)  # frozen/unplugged camera must not keep a target alive
            return self._result

    def _run(self) -> None:
        """Keep the camera alive: if it fails or stops sending frames, report it down and reopen it."""
        log = logging.getLogger(__name__)
        while not self._stop.is_set():
            try:
                self._loop()
            except Exception:
                log.exception("camera vision failed; retrying in %.0f s", CAMERA_RETRY_S)
            if self._stop.is_set():
                break
            self.available = False
            self._stop.wait(CAMERA_RETRY_S)

    def _loop(self) -> None:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision as mpv

        hands = mpv.HandLandmarker.create_from_options(mpv.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_model("hand_landmarker.task")),
            running_mode=mpv.RunningMode.VIDEO, num_hands=1))
        cap = cv2.VideoCapture(self.camera_index)
        try:
            self._capture(cv2, mp, hands, cap)
        finally:
            cap.release()
            hands.close()

    def _capture(self, cv2, mp, hands, cap) -> None:
        if not cap.isOpened():
            raise RuntimeError(f"camera {self.camera_index} could not be opened (in use by another app?)")
        t0 = last_ok = time.monotonic()
        last_ts = -1
        frame_id = getattr(self._result, "frame_id", 0) or 0
        while not self._stop.is_set():
            ok, frame = cap.read()
            if not ok:
                if time.monotonic() - last_ok > NO_FRAME_S:
                    raise RuntimeError(f"camera {self.camera_index} stopped sending frames")
                time.sleep(0.05)
                continue
            last_ok = time.monotonic()
            self.available = True
            frame = cv2.flip(frame, 1)  # mirror view: feels natural to the patient
            now = time.monotonic()
            # MediaPipe VIDEO mode rejects repeated timestamps; buffered frames can arrive <1 ms apart
            ts = last_ts = max(int((now - t0) * 1000), last_ts + 1)
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            h = hands.detect_for_video(img, ts)
            curls = pinch = wrist = None
            if h.hand_landmarks:
                lm = [(l.x, l.y) for l in h.hand_landmarks[0]]
                curls, pinch, wrist = finger_curls(lm), pinch_distance(lm), lm[0]
            frame_id += 1
            jpeg = self._annotate(cv2, frame, h.hand_landmarks[0] if h.hand_landmarks else None)
            with self._lock:
                self._result = VisionResult(curls, pinch, wrist, frame_id, now)
                self._result_at = now
                self._jpeg = jpeg

    @staticmethod
    def _annotate(cv2, frame, hand) -> bytes:
        hgt, wid = frame.shape[:2]
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
