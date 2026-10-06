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
    wavs = [0x3000] * 6
    assert (live.render_two(t, blocks(wavs, dclk=live.DCLK_DEFAULT, note_at=1), 32)
            == live.render_two(t, blocks(wavs, dclk=0, note_at=1), 32))


def test_dclk_crossfades_a_pos_jump_over_its_time():
    t = dsp.tables()
    wavs = [0] * 4 + [0x7800] * 8
    on = live.render_two(t, blocks(wavs, dclk=live.DCLK_DEFAULT, note_at=1), 32)      # 3 ms
    off = live.render_two(t, blocks(wavs, dclk=0, note_at=1), 32)
    stay = live.render_two(t, blocks([0] * 12, dclk=0, note_at=1), 32)
    j, n = 4 * 32, live.dclk_lengths()[live.DCLK_DEFAULT >> 8]
    assert n == 144
    assert on[:j] == off[:j]
    assert on[j] == stay[j]                      # the jump's first sample is still the old frame
    assert on[j + n:] == off[j + n:]             # after 3 ms, the new frame alone, bit for bit
    mid = j + n // 2
    assert abs(on[mid] - (stay[mid] + off[mid]) / 2) < 0.02


def test_dclk_small_moves_pass_straight_through():
    t = dsp.tables()
    wavs = [0x1000 + 0x100 * b for b in range(10)]      # 1/8 frame a block
    assert (live.render_two(t, blocks(wavs, dclk=live.DCLK_DEFAULT, note_at=1), 32)
            == live.render_two(t, blocks(wavs, dclk=0, note_at=1), 32))


def test_dclk_range_and_names():
    n = live.dclk_names()
    assert n[0] == "Off" and n[1] == "1.0 ms" and n[31] == "3.0 ms" and n[127] == "100 ms"
    assert live.dclk_lengths()[1] == 48 and live.dclk_lengths()[127] == 4800
