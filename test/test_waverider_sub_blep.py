"""The sub's polyBLEP (dnfw.waverider.live, owner 2026-10-26): SQR and PLS keep their naive
samples away from the edges, bit for bit, and lose most of their aliasing near them."""

import numpy as np

from dnfw.waverider import live

F = np.float32


def _render(step, wave, blocks=1500, octave=0):
    out, ph = [], 0
    for _ in range(blocks):
        ys, ph = live.render_sub(ph, step << 1, (0x6400, octave, wave << 8, 0), 32, factor=0.01)
        out += ys
    return np.array(out, float)


def _naive(step, wave, n):
    out, ph = [], 0
    for _ in range(n):
        out.append(live.sub_value(ph, wave))
        ph = (ph + step) & 0xFFFFFFFF
    return np.array(out, float)


def test_the_reciprocal_is_close():
    for s in (3000, 10 ** 5, 2 ** 20 + 7, 12345678, 2 ** 27 + 999, 2 ** 30):
        assert abs(live.sub_recip(float(F(s))) * s - 1) < 1e-6


def test_the_block_test():
    step = 1 << 20
    assert live.sub_near_edge((1 << 32) - 5 * step, step, 32, 1 << 31)       # the rise at 0, ahead
    assert live.sub_near_edge((1 << 31) - 3 * step, step, 32, 1 << 31)        # the fall
    assert not live.sub_near_edge(1 << 28, step, 32, 1 << 31)                 # far from both
    assert live.sub_near_edge(0, live.SUB_BLEP_ALWAYS, 32, 1 << 31)           # a big step: always


def test_samples_away_from_the_edges_are_the_naive_waves():
    for wave in (2, 3):
        step = int(523.3 / 48000 * 2 ** 32)
        y = _render(step, wave, blocks=100)
        n = _naive(step, wave, len(y))
        ph = (np.arange(len(y), dtype=np.int64) * step) % 2 ** 32
        edge = 2 ** 31 if wave == 2 else 2 ** 30
        far = np.ones(len(y), bool)
        for e in (0, edge):
            d = (ph - e) % 2 ** 32
            far &= np.minimum(d, 2 ** 32 - d) >= step
        g = F(F(0x6400) * F(0.01))
        assert np.array_equal(F(y[far]), F(g * F(n[far])))
        assert not np.array_equal(F(y[~far]), F(g * F(n[~far])))     # and the edges do change


def test_the_aliasing_drops():
    def alias_db(x, f):
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
        fr = np.fft.rfftfreq(len(x), 1 / 48000)
        harm = np.abs(fr - np.round(fr / f) * f) < 3
        return 10 * np.log10(spec[~harm].sum() / spec.sum())
    for wave in (2, 3):
        f = 1234.0
        step = int(f / 48000 * 2 ** 32)
        y = _render(step, wave)[4800:]
        n = _naive(step, wave, 48000)[4800:]
        assert alias_db(y, f) < alias_db(n, f) - 12
