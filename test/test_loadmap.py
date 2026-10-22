"""The loadmap diagnostic: the plan matches MARKS, and tools/dn2loadmap.py reads back what the DSP writes.

scripts/sharc_loadmap_check.py runs the build itself in digikit's runner; this needs no emulator.
"""

from __future__ import annotations

import pytest

from dnfw.waverider import loadmap as L


def coldfire_word(seq: int, i: int, snap: list[int]) -> int:
    """Reply word 2 as loadmap.asm writes it for half i (halves swapped), read by the ColdFire."""
    half = snap[i >> 1] >> 16 if i & 1 else snap[i >> 1] & 0xFFFF
    tag = 0x8000 | (seq & 0x3F) << 8 | i
    dsp = half << 16 | tag
    return int.from_bytes(L.unswap(dsp).to_bytes(4, "big"), "big")


def test_the_plan_names_every_mark_in_order():
    spec = L._code()
    assert [m["name"] for m in spec["marks"]] == [m[0] for m in L.MARKS]
    assert [m["stub_sw"] for m in spec["marks"]] == [L.stub_sw(k) for k in range(L.N)]
    assert L.RECORDS_DM + L.RECORD_BYTES * L.N <= L.RECORDS_END
    assert L.HALVES == 2 * (3 + 2 * L.N)


def test_a_window_reads_back_through_reply_word_2():
    snap = [L.MAGIC | L.N, L.WINDOW_BLOCKS, 7] + [v for k in range(L.N) for v in (1000 * (k + 1) + 0x12340000, k + 1)]
    assert len(snap) == L.HALVES // 2
    halves = {}
    for i in range(L.HALVES):
        got = L.decode_half(coldfire_word(7, i, snap))
        assert got is not None and got[:2] == (7, i)
        halves[i] = got[2]
    s = L.snapshot(L.words_from_halves(halves))
    assert s["blocks"] == L.WINDOW_BLOCKS and s["seq"] == 7
    assert s["segments"][5] == ("w_entry", 0x12340000 + 6000, 6)
    assert len(L.table(s)) == L.N + 3


def test_a_word_without_the_tag_is_refused():
    assert L.decode_half(0) is None                       # before the first SNAP
    assert L.decode_half(0x4000_1234) is None             # bit 14 set: not a loadmap tag
    assert L.decode_half((0x8000 | L.HALVES) << 16) is None
    assert L.SNAP_EVERY == 32 * L.WINDOW_BLOCKS


def test_apply_refuses_another_stream():
    with pytest.raises(L.LoadmapError):
        L.apply(b"\0" * 64)
