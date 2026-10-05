"""The song position for MOVE's SYNC (dnfw.waverider.songpos, the model of sync.c)."""

import re
import pathlib

from dnfw.waverider import live, songpos

SYNC_C = pathlib.Path(__file__).resolve().parents[1] / "csrc" / "waverider" / "sync.c"


def test_the_position_wraps_at_24_bars_onto_zero():
    assert songpos.position(0, 0) == 0
    assert songpos.position(live.SYNC_LOOP, 0) == 0
    # one sixteenth short of the wrap, all but done: just under 2^32
    p = songpos.position(live.SYNC_LOOP - 1, songpos.SIXTEENTH - 1)
    assert 2 ** 32 - 2 ** 32 // live.SYNC_LOOP // 60000 < p < 2 ** 32


def test_a_sixteenth_is_2_to_the_32_over_384():
    for s in (1, 5, 100):
        d = songpos.position(s + 1, 0) - songpos.position(s, 0)
        assert abs(d - 2 ** 32 / live.SYNC_LOOP) <= 1


def test_every_sync_length_is_a_whole_multiple_of_the_loop():
    # the phase is position x (a << k): a whole number of cycles in 24 bars
    for name, a, k in live.SYNC_NOTES:
        cycle = live.SYNC_LOOP / (a << k)
        assert abs(cycle * (a << k) - live.SYNC_LOOP) < 1e-9, name


def test_playing_at_120_steps_and_interpolates_from_the_tempo():
    sp = songpos.SongPos()
    out = [sp.frame(n, x, 14400) for n, x in songpos.playing(1500, 120.0)]
    # 120 BPM: 8 sixteenths a second, so a second of frames ends just short of 8
    assert sp.steps == 7
    assert abs(out[-1] / (2 ** 32 / live.SYNC_LOOP) - 8) < 0.01
    assert all(b >= a for a, b in zip(out, out[1:]))              # never backwards


def test_stop_holds_step_1_and_play_starts_from_it():
    sp = songpos.SongPos()
    for n, x in songpos.playing(600, 120.0):
        sp.frame(n, x, 14400)
    assert sp.sixteenths > 0
    for _ in range(songpos.STOP_FRAMES + 5):                      # STOP: both bytes 0
        p = sp.frame(0, 0, 14400)
    assert sp.stops == 1 and p == 0
    q = [sp.frame(n, x, 14400) for n, x in songpos.playing(200, 120.0)]
    assert q[0] > 0 and q[0] < 2 ** 32 // live.SYNC_LOOP // 100   # PLAY: from step 1 on


def test_a_torn_read_is_not_a_stop():
    sp = songpos.SongPos()
    for n, x in songpos.playing(400, 120.0):
        sp.frame(n, x, 14400)
    before = sp.sixteenths
    for _ in range(songpos.STOP_FRAMES - 1):                      # a few odd frames, not a STOP
        sp.frame(0, 0, 14400)
    assert sp.stops == 0 and sp.sixteenths == before


def test_a_pause_holds_just_short_of_the_next_step():
    sp = songpos.SongPos()
    sp.frame(3, 4, 14400)
    held = [sp.frame(3, 4, 14400) for _ in range(2000)]           # far longer than a step
    assert held[-1] == held[-2] < songpos.position(sp.sixteenths + 1, 0)


def test_sync_c_has_the_model_s_constants():
    src = SYNC_C.read_text(encoding="utf-8")
    assert re.search(r"#define SIXTEENTH\s+2700000u", src)
    assert re.search(r"#define SYNC_LOOP\s+384u", src)
    assert re.search(rf"#define STOP_FRAMES\s+{songpos.STOP_FRAMES}\b", src)
    assert re.search(rf"#define POSITION\s+{live.SYNC_POSITION}\b", src)
    assert "1024u / 42188u" in src and "170u * x + 2u * x / 3u" in src


def test_sync_free_phase_starts_each_cycle_on_step_1():
    # a 1/4 SYNC on Free: the phase wraps exactly when step 1, 5, 9, 13 begins
    m = live.sync_multiplier(next(i for i, n in enumerate(live.SYNC_NOTES) if n[0] == "1/4"))
    for s in (0, 4, 8, 12, 16):
        v = (songpos.position(s, 0) * m) & 0xFFFFFFFF
        assert min(v, 2 ** 32 - v) < m * 2                        # within the rounding of x 512 / 3
