"""Page 4's scope mirror (dnfw.waverider.scope_glyph), the reference the emulator frames
are checked against (5 of 5 pixel for pixel, 2026-10-08)."""
import math

from dnfw.waverider import scope_glyph as g


def _sine(period, amp=12000):
    return [round(amp * math.sin(2 * math.pi * k / period)) for k in range(g.RING)]


def test_silence_draws_the_centre_line():
    quiet = [round(40 * math.sin(k / 5)) for k in range(g.RING)]
    lit = g.strip(quiet, 4096, **g.BOX)
    cy = (g.BOX["y0"] + g.BOX["y1"]) >> 1
    assert lit == {(x, cy) for x in range(g.BOX["x0"], g.BOX["x1"] + 1)}


def test_the_trigger_holds_a_steady_tone_still():
    s = _sine(97)          # windows clear of the ring's wrap (2048 isn't a multiple of 97)
    assert g.strip(s, 3800, **g.BOX) == g.strip(s, 3800 - 13, **g.BOX) == g.strip(s, 3800 - 97 * 2, **g.BOX)


def test_the_trace_fills_the_box_at_its_peak():
    lit = g.strip(_sine(150), 4096, **g.BOX)
    ys = {y for _, y in lit}
    half = (g.BOX["y1"] - g.BOX["y0"]) >> 1
    cy = (g.BOX["y0"] + g.BOX["y1"]) >> 1
    assert max(ys) == cy + half and min(ys) >= cy - half


def test_the_level_doesnt_change_the_shape():
    assert g.strip(_sine(97, 3000), 4096, **g.BOX) == g.strip(_sine(97, 24000), 4096, **g.BOX)


def test_reply_block_reads_tracks_7_to_16_as_audio_tap_does():
    rec = bytearray(32 * 84)
    for k in range(32):                                    # track 10 (0-based 9): channels 6, 7
        rec[84 * k + 18: 84 * k + 21] = (1000 * k & 0xFFFFFF).to_bytes(3, "big")
        rec[84 * k + 21: 84 * k + 24] = (-1000 * k & 0xFFFFFF).to_bytes(3, "big")
    assert g.reply_block(bytes(rec), 9) == [0] * 32
    assert g.reply_block(bytes(rec), 8) == [0] * 32
