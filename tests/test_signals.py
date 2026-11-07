import numpy as np

from neurogrip.signals import steadiness, tremor_frequency


def test_tremor_frequency_detects_5hz():
    t = np.arange(256) / 50
    assert abs(tremor_frequency(1000 + 60 * np.sin(2 * np.pi * 5 * t)) - 5.0) < 0.4


def test_tremor_zero_when_still():
    assert tremor_frequency(np.full(256, 1000.0)) == 0.0


def test_steadiness_perfect_when_still():
    assert steadiness(np.full(256, 1000.0)) == 100.0


def test_steadiness_drops_with_shake():
    t = np.arange(256) / 50
    assert steadiness(1000 + 60 * np.sin(2 * np.pi * 5 * t)) < 90
