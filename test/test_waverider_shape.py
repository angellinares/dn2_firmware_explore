"""Page 5's model (dnfw.waverider.live: fold, shaper, npos_offset), which page5.asm matches bit
for bit in the SHARC runner (scripts/sharc_waverider_shape.py), and its place in the image."""
import math

from dnfw.waverider import dsp, live, pages

T = live._f32(live.SHAPE_PEAK)


def sine(peak, n=256):
    return [live._f32(peak * math.sin(2 * math.pi * k / n)) for k in range(n)]


def test_fold_keeps_zero_and_the_fold_point_and_stays_inside_it():
    for word in (0x0100, 0x4000, 0x7F00):
        assert live.fold([0.0], word) == [0.0]
        ys = live.fold(sine(2 * T), word)
        assert max(abs(y) for y in ys) <= T * 1.0000001


def test_fold_has_no_spike_where_the_phase_is_exactly_half():
    # x g / T + 1 = 2 exactly: the phase is 2^31, whose ABS overflows; the >> 1 keeps it at +T
    g = live._f32(live._f32(1.0 + live._f32(0x4000 * live._f32(live.FOLD_DRIVE / live.SHAPE_MAX)))
                  * live._f32(1 / live.SHAPE_PEAK))
    for x in (1.0 / g, -3.0 / g, 5.0 / g):
        assert abs(live.fold([live._f32(x)], 0x4000)[0]) <= T * 1.0000001


def test_fold_below_the_fold_point_is_the_drive_alone():
    xs = [x * 0.5 for x in sine(T)]
    drive = 1 + live.FOLD_DRIVE / 127
    assert max(abs(y - x * drive) for x, y in zip(xs, live.fold(xs, 0x0100))) < 1e-6


def test_npos_spans_half_the_range_at_the_top_and_nothing_at_0():
    x, offs = live.npos_seeds()[0], []
    for _ in range(4000):
        off, x = live.npos_offset(x, live.SHAPE_MAX)
        offs.append(off)
    assert -live.NPOS_DEPTH <= min(offs) < -0.9 * live.NPOS_DEPTH
    assert 0.9 * live.NPOS_DEPTH < max(offs) <= live.NPOS_DEPTH
    assert all(s & 1 and s for s in live.npos_seeds()) and len(set(live.npos_seeds())) == 32


def test_the_shaper_with_osc_2_silent_scales_the_mix_by_one_less_the_amount():
    o1 = sine(T)
    for kind in (1, 2):
        ys = live.shaper(o1, o1, kind, live.SHAPE_MAX)
        want = [0.0] * len(o1) if kind == 1 else [live._f32(v * 0.5) for v in o1]
        assert max(abs(a - b) for a, b in zip(ys, want)) < 1e-7


def test_a_sound_at_page_5s_defaults_renders_as_before():
    tables = dsp.tables()
    blocks = [(60.0, (0x4000, 0, 0x4000, 0x6400), (0x4000, 0x100, 0x4000, 0x6400))] * 3
    plain = live.render_two(tables, blocks)
    assert live.render_two(tables, blocks, shapes=[(0, 0, 0, 0x4000)] * 3) == plain
    assert live.render_two(tables, blocks, shapes=[(0, 0, 0x0300, 0x7F00)] * 3) == plain   # TYPE 3: Off


def test_type_offers_only_what_plays_and_page5_fits_its_span():
    assert pages.SHAPE_TYPES == live.SHAPE_TYPES == ("Off", "Ring", "AM")
    assert pages.RANGES[pages.SHAPE_TYPE] == (0, 2 << 8, 0)
    assert dsp.PAGE5_DM >= dsp.BUILD3_END and dsp.PAGE5_END <= dsp.REGION[1]
    assert len(dsp.objects()["page5"]) <= dsp.PAGE5_COPY_DM - dsp.PAGE5_DM - 64
