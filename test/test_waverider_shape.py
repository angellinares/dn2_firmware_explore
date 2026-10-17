"""Page 5's model (dnfw.waverider.live: fold, shaper), which page5.asm matches bit
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


def test_npos_changes_nothing_yet():
    tables = dsp.tables()
    blocks = [(60.0, (0x4000, 0, 0x4000, 0x6400), (0x4000, 0x100, 0x4000, 0x6400))] * 3
    assert live.render_two(tables, blocks, shapes=[(0, 0x7F00, 0, 0x4000)] * 3) == live.render_two(tables, blocks)


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
    assert live.render_two(tables, blocks, shapes=[(0, 0, 0x0400, 0x7F00)] * 3) == plain   # TYPE 4, past the list: Off (3 is Formant)


def test_type_offers_only_what_plays_and_page5_fits_its_span():
    assert pages.SHAPE_TYPES == live.SHAPE_TYPES == ("Off", "Ring", "AM", "Formant")
    assert live.SHAPE_TYPES.index("Formant") == live.TYPE_FORMANT
    assert pages.RANGES[pages.SHAPE_TYPE] == (0, 3 << 8, 0)
    assert dsp.FORMANT_DM >= dsp.PHASE_DM and dsp.FORMANT_DDR_END <= dsp.DDR_REGION[1]
    assert len(dsp.objects()["formant"]) <= dsp.FORMANT_COEF_DM - dsp.FORMANT_DM - 64
    assert dsp.PAGE5_DM >= dsp.BUILD3_END and dsp.PAGE5_END <= dsp.REGION[1]
    assert len(dsp.objects()["page5"]) <= dsp.PAGE5_COPY_DM - dsp.PAGE5_DM - 64


BLOCKS = [(60.0, (0x4000, 0, 0x4000, 0x6400), (0x4000, 0x100, 0x4000, 0x6400))] * 3
SOLO = [(60.0, (0x4000, 0, 0x4000, 0x6400), (0x4000, 0x100, 0x4000, 0))] * 3


def test_warp_and_fm_at_0_and_fm_without_osc_2_render_as_before():
    tables = dsp.tables()
    assert live.render_two(tables, BLOCKS, shapes=[(0, 0, 0, 0x4000, 0x00FF, 0)] * 3) == live.render_two(tables, BLOCKS)
    assert live.render_two(tables, SOLO, shapes=[(0, 0, 0, 0x4000, 0, 0x7F00)] * 3) == live.render_two(tables, SOLO)


def test_warp_and_fm_change_the_sound():
    tables = dsp.tables()
    plain = live.render_two(tables, BLOCKS)
    for shape in ((0, 0, 0, 0x4000, 0x4000, 0), (0, 0, 0, 0x4000, 0, 0x4000)):
        assert live.render_two(tables, BLOCKS, shapes=[shape] * 3) != plain


def test_the_warp_table_starts_flat_and_its_lines_meet_at_the_waves_middle():
    tab = live.warp_table()
    assert len(tab) == 128 and tab[0] == (1.0, 1.0) and tab[127][0] == live.WARP_K1_TOP
    for v in (1, 64, 127):
        k1, k2 = tab[v]
        d = 0.5 / k1                                  # where the first line reaches the middle
        assert abs(live.warp_phase(int(d * 2 ** 32), k1, k2) / 2 ** 32 - 0.5) < 1e-6
        ys = [live.warp_phase(p << 24, k1, k2) for p in range(256)]
        assert ys[0] == 0 and all(a <= b for a, b in zip(ys, ys[1:]))


def test_read_phases_without_warp_or_fm_is_the_running_phase():
    assert live.read_phases(0xFFFFFFF0, 0x10, 3) == [0xFFFFFFF0, 0, 0x10]
    assert live.read_phases(0, 0x100, 2, offsets=[0x80000000, 0x10]) == [0x80000000, 0x110]


def test_fm_offsets_are_one_cycle_at_the_peak_and_full_depth():
    off = live.fm_offsets([T, -T], live.SHAPE_MAX)
    assert all(min(o, 2 ** 32 - o) < 2 ** 12 for o in off)   # +-1 cycle is 0 mod 1


def test_the_level_follows_the_fastest_phase():
    assert live.phase_sel(1000) == 1000
    assert live.phase_sel(1000, (10.0, 0.5)) == 10000
    assert live.phase_sel(1000, None, 1000, live.SHAPE_MAX) == 1000 + round(2 * math.pi * 1000)


def test_the_phase_buffers_fit_and_phase_asm_has_its_span():
    assert dsp.PAGE5_END <= dsp.FMB_DM < dsp.PH_DM < dsp.WARP_TABLE_DM < dsp.PHASE_DM < dsp.REGION[1]
    assert dsp.PH_DM - dsp.FMB_DM >= 4 * live.PHASE_MAX
    assert dsp.WARP_TABLE_DM - dsp.PH_DM >= 4 * (live.PHASE_MAX + 1)
    assert dsp.PHASE_DM - dsp.WARP_TABLE_DM == 8 * 128
