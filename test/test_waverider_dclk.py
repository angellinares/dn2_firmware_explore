"""SMTH (the glide on POS) and DCLK (the declick) in the reference model (M10b-2)."""

from dnfw.waverider import dsp, live, render

OFF = 0x7F00                       # SMTH 127: what every sound saved before SMTH holds
OSC2_OFF = (0, 0, 0x4000, 0)


def osc1(wav, smth=OFF):
    return (wav, 0, 0x4000, 0x6400, 0x3200, live.MPOS_NONE, 0, 0, 0, smth)


def blocks(wavs, smth=OFF, dclk=0, note_at=None):
    return [(48.0, osc1(w, smth), OSC2_OFF,
             (0, b == note_at, live.PRST_OFF, 0, 0, dclk)) for b, w in enumerate(wavs)]


def test_smth_127_is_the_target_exactly():
    assert live.smth_table()[127] == 1.0
    for s in (0.0, 12345.0, 983040.0):
        for t in (0, 77, 983040):
            assert live.smooth(s, t, OFF, False) == float(t)


def test_smth_glides_and_a_note_snaps():
    s = 0.0
    seen = []
    for _ in range(10):
        s = live.smooth(s, 983040, 0x3C00, False)
        seen.append(s)
    assert seen == sorted(seen) and 0 < seen[0] < seen[-1] < 983040
    assert live.smooth(seen[-1], 1000, 0x3C00, True) == 1000.0


def test_smth_names_and_times():
    names = live.smth_names()
    assert len(names) == 128 and names[127] == "Off" and names[0] == "1000 ms"
    assert abs(live.smth_tau(126) - 2 ** -9) < 1e-12


def test_smth_off_renders_as_before_smth():
    t = dsp.tables()
    wavs = [0] * 3 + [0x7800] * 3
    with_field = live.render_two(t, blocks(wavs), 32)
    without = live.render_two(t, [(48.0, osc1(w)[:9], OSC2_OFF, (0, False, live.PRST_OFF, 0, 0))
                                  for w in wavs], 32)
    assert with_field == without


def test_dclk_leaves_an_unchanged_block_untouched():
    t = dsp.tables()
    on = live.render_two(t, blocks([0x3000] * 6, dclk=OFF, note_at=1), 32)
    off = live.render_two(t, blocks([0x3000] * 6, dclk=0, note_at=1), 32)
    # block 0 fades in (no last block); the note block is left alone; after it, nothing
    # changes, so the offset is exactly 0 and every sample is the same
    assert on[32:] == off[32:]


def test_dclk_ramps_a_pos_jump_in_over_a_millisecond():
    t = dsp.tables()
    wavs = [0] * 4 + [0x7800] * 4
    on = live.render_two(t, blocks(wavs, dclk=OFF, note_at=1), 32)
    off = live.render_two(t, blocks(wavs, dclk=0, note_at=1), 32)
    j = 4 * 32
    d = [a - b for a, b in zip(on[j:j + 64], off[j:j + 64])]
    assert abs(d[0]) > 1e-3
    assert abs(d[31]) < 0.6 * abs(d[0]) and abs(d[63]) < 0.3 * abs(d[0])   # it carries on decaying
    # the jump block starts where the old frame would have gone on
    tab = t[0]
    ph = 0
    for b in range(4):                                     # the oscillator's phase at block 4
        _, ph = render.render(tab, ph, live.increment(48.0), live.position(0), 32)
    y, _ = render.render(tab, ph, 0, live.position(0), 1)
    assert abs(on[j] - live._f32(live.gain(0x6400) * y[0])) < 1e-6


def test_the_decay_table_is_one_millisecond():
    d = live.dclk_table()
    assert d[0] == 1.0 and abs(d[48] - 0.36787944) < 1e-6 and len(d) == live.DCLK_TAPS
