"""The loadmap diagnostic: the plan matches MARKS, and tools/dn2loadmap.py reads back what the DSP writes.

scripts/sharc_loadmap_check.py runs the build itself in digikit's runner; this needs no emulator.
"""

from __future__ import annotations

import pytest

from dnfw.waverider import loadmap as L


def coldfire_view(dsp_words: list[int]) -> bytes:
    """The rows as the ColdFire's copy holds them: each DSP word read big-endian has its halves
    swapped (idle_load.asm swaps reply word 1's halves for that reason)."""
    out = bytearray(L.ROWS_SPAN)
    for j, w in enumerate(dsp_words):
        at = 0x54 * (j // 2) + 4 * (j % 2)
        out[at:at + 4] = L.unswap(w).to_bytes(4, "big")
    return bytes(out)


def page(seq: int, p: int, data: list[int]) -> list[int]:
    words = [L.MAGIC | (seq & 0xFF) << 8 | p] + data
    x = 0
    for w in words:
        x ^= w
    return words + [x]


def test_the_plan_names_every_mark_in_order():
    spec = L._code()
    assert [m["name"] for m in spec["marks"]] == [m[0] for m in L.MARKS]
    assert [m["stub_sw"] for m in spec["marks"]] == [L.stub_sw(k) for k in range(L.N)]
    assert L.RECORDS_DM + L.RECORD_BYTES * L.N <= L.RECORDS_END
    assert L.HALVES == 2 * (3 + 2 * L.N)


def test_a_window_reads_back_through_the_rows():
    snap = [L.MAGIC | L.N, L.WINDOW_BLOCKS, 7] + [v for k in range(L.N) for v in (1000 * (k + 1), k + 1)] + [0]
    pages = {}
    for p in range(L.PAGES):
        got = L.decode_page(L.page_words(coldfire_view(page(7, p, snap[22 * p:22 * p + 22]))))
        assert got is not None and got[:2] == (7, p)
        pages[p] = got[2]
    s = L.snapshot(pages)
    assert s["blocks"] == L.WINDOW_BLOCKS and s["seq"] == 7
    assert s["segments"][5] == ("w_entry", 6000, 6)
    assert len(L.table(s)) == L.N + 3


def test_a_torn_page_is_refused():
    words = page(1, 0, list(range(22)))
    words[5] ^= 1
    assert L.decode_page(words) is None
    assert L.decode_page([0] * 24) is None


def test_apply_refuses_another_stream():
    with pytest.raises(L.LoadmapError):
        L.apply(b"\0" * 64)
