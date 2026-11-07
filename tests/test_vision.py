from neurogrip.vision import CompensationDetector, MockVision, finger_curls

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


def test_open_hand_curls_low():
    assert all(v < 0.1 for v in finger_curls(OPEN).values())


def test_fist_curls_high():
    c = finger_curls(FIST)
    assert c["thumb"] > 0.9 and c["index"] > 0.9 and c["rest"] > 0.9


def test_shoulder_hike_detected():
    c = CompensationDetector(calib_frames=5)
    for _ in range(5):
        c.update({"l_sh": (0.4, 0.5), "r_sh": (0.6, 0.5)})
    assert c.update({"l_sh": (0.4, 0.44), "r_sh": (0.6, 0.5)}) == ["shoulder_hike"]


def test_trunk_lean_detected():
    c = CompensationDetector(calib_frames=5)
    for _ in range(5):
        c.update({"l_sh": (0.4, 0.5), "r_sh": (0.6, 0.5)})
    assert c.update({"l_sh": (0.47, 0.5), "r_sh": (0.67, 0.5)}) == ["trunk_lean"]


def test_no_pose_no_compensation():
    assert CompensationDetector(calib_frames=0).update(None) == []


def test_mock_vision_has_curls_and_occasional_compensation():
    v = MockVision()
    results = [v.latest(t_ms=t) for t in range(0, 15000, 20)]
    assert all(r.curls is not None for r in results)
    assert max(r.curls["index"] for r in results) > 0.9
    assert any(r.compensation for r in results) and not all(r.compensation for r in results)
