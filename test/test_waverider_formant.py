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
