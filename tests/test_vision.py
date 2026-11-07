from neurogrip.vision import MockVision, VisionResult, finger_curls

WRIST = (0.5, 0.8)
MCPS = {5: (0.45, 0.6), 9: (0.5, 0.6), 13: (0.55, 0.6), 17: (0.6, 0.62)}


def _hand(open_hand: bool):
    lm = [WRIST] * 21
    for mcp, (x, y) in MCPS.items():
        lm[mcp] = (x, y)
        k = 2.0 if open_hand else 1.0
        lm[mcp + 3] = (WRIST[0] + k * (x - WRIST[0]), WRIST[1] + k * (y - WRIST[1]))
    lm[4] = (0.2, 0.6) if open_hand else (0.55, 0.62)
    return lm


OPEN, FIST = _hand(True), _hand(False)


def test_finger_curls_are_independent():
    lm = list(FIST)
    lm[8] = OPEN[8]  # only the index finger extended
    c = finger_curls(lm)
    assert c["index"] < 0.1 and c["middle"] > 0.9 and c["pinky"] > 0.9


def test_open_hand_curls_low():
    assert all(v < 0.1 for v in finger_curls(OPEN).values())


def test_fist_curls_high():
    c = finger_curls(FIST)
    assert set(c) == {"thumb", "index", "middle", "ring", "pinky"}
    assert all(v > 0.9 for v in c.values())


def test_mock_vision_has_curls():
    v = MockVision()
    results = [v.latest(t_ms=t) for t in range(0, 15000, 20)]
    assert all(r.curls is not None for r in results)
    assert max(r.curls["index"] for r in results) > 0.9


def test_vision_result_has_no_posture_field():
    assert not hasattr(VisionResult(None), "compensation")


def test_camera_result_goes_stale():
    import time
    from neurogrip.vision import CameraVision
    cam = CameraVision(0)  # not started
    cam._set(VisionResult(dict.fromkeys(("thumb", "index", "middle", "ring", "pinky"), 1)))
    assert cam.latest().curls is not None
    cam._result_at = time.monotonic() - 1
    assert cam.latest().curls is None


def test_pinch_distance_open_vs_closed():
    from neurogrip.vision import pinch_distance
    assert pinch_distance(OPEN) > 1.0 and pinch_distance(FIST) < 0.6


def test_mock_vision_wrist_tremor_and_frames():
    v = MockVision(tremor_hz=5)
    r = v.latest(t_ms=1000)
    assert r.frame_id == 1000 // 33 and r.t == 1.0
    assert r.wrist is not None and r.pinch is not None
    xs = [v.latest(t_ms=t).wrist[0] for t in range(0, 1000, 33)]
    assert max(xs) - min(xs) > 0.005
