"""geometry: the shipped mip scheme with the frame length a parameter."""

import numpy as np
import pytest

from dnfw.waverider import geometry as G
from dnfw.waverider import mip


def test_512_levels_are_mips():
    rng = np.random.default_rng(1)
    frame = [int(v) for v in rng.integers(-20000, 20000, 512)]
    ours = G.frame_levels(frame)
    theirs = mip.frame_levels(frame)
    assert len(ours) == len(theirs) == mip.LEVELS
    for a, b in zip(ours, theirs):
        assert len(a) == len(b)
        assert np.max(np.abs(np.clip(np.rint(a), -32768, 32767) - np.array(b))) == 0


@pytest.mark.parametrize("freq", [30.0, 100.0, 440.0, 1000.0, 3000.0, 8000.0, 15000.0])
def test_512_level_choice_is_mips(freq):
    inc = G.increment(freq)
    assert G.level_for(inc, 512, mip.LIMIT_HZ) == mip.level_for(inc, mip.LIMIT_HZ)


def test_2048_geometry():
    assert G.levels(2048) == 10
    assert G.top_harmonic(2048, 0) == 1023
    assert [G.level_points(2048, k) for k in range(10)] == [2048, 2048, 2048, 1024, 512, 256, 128, 64, 32, 16]


def test_level_keeps_its_harmonics_only():
    n = 2048
    x = np.arange(n) / n
    frame = np.sin(2 * np.pi * 3 * x) + 0.5 * np.sin(2 * np.pi * 700 * x)
    lv = G.frame_levels(frame)
    k = 1                                   # top harmonic 511: 700 is gone, 3 stays
    m = len(lv[k])
    spec = np.abs(np.fft.rfft(lv[k])) / (m / 2)
    assert abs(spec[3] - 1.0) < 1e-9 and spec[200:].max() < 1e-9


def test_no_alias_above_the_limit():
    n = 2048
    for freq in (60.0, 500.0, 2000.0):
        k = G.level_for(G.increment(freq), n)
        assert G.top_harmonic(n, k) * freq < G.LIMIT_HZ
        assert k == 0 or G.top_harmonic(n, k - 1) * freq >= G.LIMIT_HZ * (1 - 1e-6)


def test_render_a_sine_is_a_sine():
    n = 2048
    frame = np.sin(2 * np.pi * np.arange(n) / n) * 30000
    lv = G.table_levels([frame, frame])
    y = G.render(lv, 440.0, [0.0] * 150)
    t = np.arange(len(y)) / G.RATE
    ref = np.sin(2 * np.pi * G.increment(440.0) / 2 ** 32 * G.RATE * t) * 30000
    assert np.max(np.abs(y - ref)) < 1.0
