"""Waverider's MIDI map (`dnfw.waverider.pages.midi_rows`, docs/waverider-midi.md): every knob
place takes a CC and an NRPN, one number each, and page 5's own numbers stay clear of stock's."""

import pathlib
import struct

import pytest

from dnfw.waverider import pages
from dnfw.checkout import resources_dir  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.11_dist.zip"
SWITCH_CASES = {1, 2, 6, 33, 34, 38, 64, 66, 94, 98, 99, 110, 120, 121, 123}   # 0x40122c0c
TRIG_AND_LEVEL = {3, 4, 5, 13, 14, 95}                                          # DN2 manual, C.1, C.2
SENT_UNASKED = {0, 32, 7, 10, 11, 67, 68, 69, *range(96, 102), *range(120, 128)}


def test_every_place_has_one_cc_and_one_nrpn():
    rows = pages.midi_rows()
    assert len(rows) == sum(1 for page in pages.PAGES for rid in page if rid) == 40
    assert len({cc for _, _, cc in rows}) == len({n for _, n, _ in rows}) == len(rows)
    assert all(0 <= cc < 128 for _, _, cc in rows)
    assert [n for _, n, _ in rows][32:] == list(range(128 + 112, 128 + 120))


def test_pages_one_to_four_keep_stocks_knob_numbers():
    rows = pages.midi_rows()
    stock = [*range(40, 64), *range(70, 78)]
    assert [cc for _, _, cc in rows[:32]] == stock
    assert [n for _, n, _ in rows[:32]] == list(range(128 + 73, 128 + 105))


@pytest.mark.skipif(not STOCK.exists(), reason="no stock 1.11 image")
def test_page_five_is_clear_of_stock():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    sec = load(read_image(STOCK)).container.find(3)
    content, base = sec.unpack(), sec.dest
    used_cc, used_nrpn = set(), set()
    for rid in range(1, 321):
        at = pages.RECORD_TABLE + 60 * rid - base
        page, = struct.unpack_from(">I", content, at)
        cc, lsb = struct.unpack_from(">hh", content, at + 0x18)
        nrpn, = struct.unpack_from(">i", content, at + 0x1C)
        if page <= 15 or 26 <= page <= 28:          # a track's own channel
            used_cc |= {v for v in (cc, lsb) if v >= 0}
            if nrpn >= 0:
                used_nrpn.add(nrpn)
    page5 = pages.midi_rows()[32:]
    for _, nrpn, cc in page5:
        assert cc not in used_cc | SWITCH_CASES | TRIG_AND_LEVEL | SENT_UNASKED, cc
        assert nrpn not in used_nrpn | {128 + 108, 128 + 110}, nrpn
