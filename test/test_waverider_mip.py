"""dnfw.waverider.mip: the octave levels, the level a pitch plays, and the reference reader
on them (linear and Hermite)."""

import numpy as np

from dnfw.waverider import mip, render


def saw(h_max=255):
    p = np.arange(512) * 2 * np.pi / 512
    s = sum(((-1) ** (h + 1)) * np.sin(h * p) / h for h in range(1, h_max + 1))
    return [int(v) for v in np.rint(s / np.abs(s).max() * 30000)]


def test_level_lengths_and_size():
    assert [mip.points(k) for k in range(mip.LEVELS)] == [512, 512, 512, 256, 128, 64, 32, 16]
    assert [mip.points(k, 2) for k in range(mip.LEVELS)] == [512, 256, 128, 64, 32, 16, 8, 4]
    assert mip.size_bytes() == 2 * 16 * 2032


def test_level_zero_is_the_frame_and_levels_are_band_limited():
    frame = saw()
    lv = mip.frame_levels(frame)
    assert lv[0] == frame
    for k in range(1, mip.LEVELS):
        spec = np.abs(np.fft.rfft(np.asarray(lv[k], float))) / len(lv[k])
        ref = np.abs(np.fft.rfft(np.asarray(frame, float))) / 512
        top = mip.top_harmonic(k)
        assert spec[top + 1:].max() < 2.0                      # rounding to int16 only
        # the kept harmonics are the frame's own
        assert np.allclose(spec[1:top + 1], ref[1:top + 1], atol=2.0)


def test_level_for_keeps_every_kept_harmonic_below_nyquist():
    for hz in (30, 65.4, 130.8, 261.6, 523.3, 1046.5, 2093.0, 4186.0, 8000.0):
        inc = render.increment(hz)
        k = mip.level_for(inc)
        assert mip.top_harmonic(k) * hz < 24000 or k == mip.LEVELS - 1
        if k:
            assert mip.top_harmonic(k - 1) * hz >= 24000           # the lowest that doesn't alias
    assert mip.level_for(render.increment(65.4)) == 0


def test_a_low_note_reads_level_zero_bit_for_bit():
    table = [saw(32)] * 16
    levels = mip.table_levels(table)
    inc = render.increment(65.4)
    for precision in ("ideal", "float32"):
        for interp in ("linear", "hermite"):
            assert mip.render(levels, 0, inc, 3 << 16, 64, precision, interp) == \
                render.render(table, 0, inc, 3 << 16, 64, precision, interp)


def test_hermite_passes_through_samples_and_lines():
    ident = lambda x: x
    assert render.hermite(0.1, 0.4, -0.2, 0.3, 0.0, ident) == 0.4
    # Catmull-Rom reproduces a straight line exactly
    for fr in (0.0, 0.25, 0.5, 0.9):
        assert abs(render.hermite(-1.0, 0.0, 1.0, 2.0, fr, ident) - fr) < 1e-12


def test_hermite_reads_cleaner_than_linear_on_a_sine():
    # 32 points a cycle, so interpolation error, not int16 rounding, dominates
    p = np.arange(32) * 2 * np.pi / 32
    frame = [int(v) for v in np.rint(30000 * np.sin(p))]
    table = [frame] * 2
    inc = render.increment(523.3)
    ideal = 30000 / 32768 * np.sin(2 * np.pi * np.arange(256) * inc / 2 ** 32)
    lin = np.asarray(render.render(table, 0, inc, 0, 256, "ideal", "linear")[0])
    her = np.asarray(render.render(table, 0, inc, 0, 256, "ideal", "hermite")[0])
    assert np.abs(her - ideal).max() < np.abs(lin - ideal).max() / 10
