"""Page 3's noise glyph (dnfw.waverider.noise_glyph, page.c's noise_field): the same
generator as the DSP's reference, and the C table in step with it."""
import pathlib

from dnfw.waverider import live, noise_glyph as g

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _reference(typ, colr, n):
    v, out = live.NoiseVoice(g.SEED), []
    while len(out) < n:
        out += v.render((100 << 8, typ << 8, colr << 8, 127 << 8), not out, 16)
    return out[:n]


def test_the_trace_follows_the_dsp_reference_sample_for_sample():
    for typ in range(4):
        for colr in (0, 64, 127):
            ref = _reference(typ, colr, g.WARMUP + 98)[g.WARMUP:]
            got = [y / g.Q for y in g.samples(100, typ, colr, 127, 98)]
            assert max(abs(a - b) for a, b in zip(ref, got)) < 0.01, (typ, colr)


def test_nois_0_is_a_flat_line_and_dec_decays_it():
    assert set(g.samples(0, 1, 64, 127, 98)) == {0}
    short = g.samples(127, 0, 64, 20, 98)
    assert max(abs(y) for y in short[-20:]) < max(abs(y) for y in short[:20]) / 10


def test_the_types_differ_in_texture():
    def rough(t):
        s = g.samples(100, t, 64, 127, 98)
        return sum(abs(b - a) for a, b in zip(s, s[1:]))
    assert rough(0) > rough(1) > rough(2)


def test_the_c_table_is_generated_from_the_mirror():
    assert (ROOT / "csrc/waverider/noise_env.h").read_text() == g.header(98)


def test_the_sub_trace_is_the_dsp_s_shapes():
    for wave in range(4):
        for i in range(0, 1 << 32, 1 << 26):
            assert abs(g.sub_value(i, wave) / g.Q - live.sub_value(i, wave)) < 1e-3, (wave, i)


def test_oct_draws_two_cycles_at_minus_1_and_one_at_minus_2():
    def crossings(octave):
        s = g.sub_samples(100, octave, 2, 98)
        return sum(1 for a, b in zip(s, s[1:]) if (a > 0) != (b > 0))
    assert (crossings(0), crossings(1)) == (3, 1)


def test_sub_0_leaves_the_noise_alone_in_both_glyphs():
    noise = (80, 1, 64, 127)
    assert g.strip(noise, (0, 0, 0), 24, 121, 14, 25, 3) == g.strip(noise, (0, 0, 0), 24, 121, 14, 25, 4)
    assert g.strip(noise, (80, 0, 0), 24, 121, 14, 25, 3) != g.strip(noise, (80, 0, 0), 24, 121, 14, 25, 4)
