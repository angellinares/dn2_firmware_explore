"""The Formant type's filter in the model (dnfw.waverider.formant)."""

from __future__ import annotations

import math
import random

from dnfw.waverider import formant as F


def test_every_pole_is_inside_the_unit_circle():
    for p in [i / 8 for i in range(33)]:
        for shift in (0.5, 0.71, 1.0, 1.41, 2.0, 4.0):
            for a0, _, b1, _, b2 in F.cascade(p, shift):
                assert -b2 < 1.0                                  # |pole|^2 = -B2 for a complex pair
                assert b1 * b1 + 4 * b2 < 0 or abs(b1) < 1 - b2   # complex, or both real roots inside


def test_each_resonator_has_a_gain_of_1_at_0_hz():
    for a0, a1, b1, a2, b2 in F.cascade(1.5, 1.2):
        assert abs((a0 + a1 + a2) / (1 - b1 - b2) - 1.0) < 1e-6


def test_the_blend_runs_through_the_table_at_whole_positions():
    for i, (_, freqs, bws) in enumerate(F.VOWELS):
        assert F.formants(float(i)) == (tuple(float(f) for f in freqs), tuple(float(b) for b in bws))
    mid = F.formants(0.5)[0][0]
    assert mid == (600 + 400) / 2


def test_a_raised_shift_stops_below_nyquist():
    assert max(F.formants(4.0, 8.0)[0]) <= F.NYQUIST_GUARD * F.RATE


def test_the_level_makes_every_vowel_as_loud_as_a():
    ref = F.power_gain(F.cascade(0.0))
    for p in (0.0, 1.0, 2.0, 2.5, 3.0, 4.0):
        for shift in (0.8, 1.0, 1.3):
            g = F.level(p, shift)
            assert abs(F.power_gain(F.cascade(p, shift)) * g * g / ref - 1.0) < 1e-5


def test_run_is_the_cascade_and_keeps_its_states_across_blocks():
    rnd = random.Random(5)
    x = [rnd.uniform(-1, 1) for _ in range(256)]
    bq = F.cascade(1.7, 1.1)
    states = [[0.0, 0.0] for _ in bq]
    got = []
    for k in range(0, len(x), 32):                     # eight blocks, the states carried over
        got += F.run(x[k:k + 32], bq, states)
    ref = list(x)                                      # an independent float64 recursion
    for a0, _, b1, _, b2 in bq:
        out, y1, y2 = [], 0.0, 0.0
        for v in ref:
            o = a0 * v + b1 * y1 + b2 * y2
            out.append(o)
            y2, y1 = y1, o
        ref = out
    peak = max(abs(v) for v in ref)
    assert max(abs(a - b) for a, b in zip(got, ref)) < 1e-4 * peak


def test_run_rounds_each_step_to_float32():
    out = F.run([0.1, -0.3, 0.7], F.cascade(0.0), [[0.0, 0.0] for _ in range(5)])
    assert all(F._f32(v) == v for v in out) and any(v != 0 for v in out)
    assert not any(math.isnan(v) for v in out)


def test_the_level_keeps_a_saw_at_110_hz_within_3_db_across_the_vowels():
    n = 12000
    saw = [sum(math.sin(2 * math.pi * k * 110 * i / F.RATE) / k for k in range(1, 41)) / 2 for i in range(n)]
    rms = []
    for p in range(5):
        bq = F.cascade(float(p))
        y = F.run(saw, bq, [[0.0, 0.0] for _ in bq])[4000:]
        g = F.level(float(p))
        rms.append(10 * math.log10(sum(v * v for v in y) / len(y)) + 20 * math.log10(g))
    assert max(rms) - min(rms) < 3.0, rms


def test_the_glide_takes_a_jump_in_steps_and_a_note_at_once():
    p, seen = 0.0, []
    for _ in range(40):
        p = F.glide(p, 4.0, False)
        seen.append(p)
    assert seen[0] == F.GLIDE_STEP and seen[31] == 4.0 and all(b - a <= F.GLIDE_STEP + 1e-12 for a, b in zip([0.0] + seen, seen))
    assert F.glide(1.0, 3.5, True) == 3.5 and F.glide(None, 2.0, False) == 2.0
    assert F.glide(3.0, 2.95, False) == 2.95


# The Formant type in the render (live.render_two, TYPE 3), layout A's block of delay

def _blocks(n=12):
    from dnfw.waverider import live
    osc1 = (0, 0, 0x4000, 0x6400, 0x3200, live.MPOS_NONE, 0, 0, 0, 0)
    return [(45.0, osc1, (0, 0, 0x4000, 0), (0, b == 1, live.PRST_OFF, 0, 0, 0)) for b in range(n)]


def _shape(typ=3, vowel=0, shift=0, dry=0):
    return (0, 0, typ << 8, vowel, 0, 0, shift, dry)          # AMT, P1, P2


def test_formant_fully_dry_is_the_plain_sound_one_block_late():
    from dnfw.waverider import dsp, live
    t, blk = dsp.tables(), _blocks()
    plain = live.render_two(t, blk, 32)
    got = live.render_two(t, blk, 32, shapes=[_shape(dry=0x7F00)] * len(blk))
    assert got[:32] == [0.0] * 32 and got[32:] == plain[:-32]


def test_a_new_sounds_formant_filters_and_amt_moves_the_vowel_p1_the_shift():
    from dnfw.waverider import dsp, live
    t, blk = dsp.tables(), _blocks()
    plain = live.render_two(t, blk, 32)
    a = live.render_two(t, blk, 32, shapes=[_shape()] * len(blk))            # every knob at 0: A, no shift, wet
    u = live.render_two(t, blk, 32, shapes=[_shape(vowel=0x7F00)] * len(blk))
    up = live.render_two(t, blk, 32, shapes=[_shape(shift=0x7F00)] * len(blk))
    assert a[32:] != plain[:-32] and a != u and a != up


def test_the_other_types_ignore_p1_and_p2_and_take_six_words():
    from dnfw.waverider import dsp, live
    t, blk = dsp.tables(), _blocks()
    ring6 = live.render_two(t, blk, 32, shapes=[(0, 0, 1 << 8, 0x4000, 0, 0)] * len(blk))
    ring8 = live.render_two(t, blk, 32, shapes=[(0, 0, 1 << 8, 0x4000, 0, 0, 0x7F00, 0x7F00)] * len(blk))
    assert ring6 == ring8


def test_the_knobs_map_to_the_vowel_and_the_shift():
    assert F.position_of(0) == 0.0 and F.position_of(0x7F00) == 4.0
    assert F.shift_of(0) == 1.0 and abs(F.shift_of(0x7F00) - 2.0) < 1e-12
