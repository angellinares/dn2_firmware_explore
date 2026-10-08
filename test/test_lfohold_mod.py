"""LFO hold: it NOPs exactly the two stop-table stores in evaluator A, refuses an
image that is not stock there, and shares no byte with any other mod.

What it *does* is measured in the emulator (`scripts/emu_lfo_trigmodes.py
--hold`, 2026-10-08): stock ONE and HALF put the destination at exactly its
centre at the stop, and with the NOPs each waveform holds the value it reached;
RND is unchanged. `src/dnfw/mods/lfohold.py` carries the detail.
"""

import pathlib

import pytest

from dnfw.mods import ModError, check_compatible
from dnfw.mods import lfohold

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
NOP2 = bytes.fromhex("4e714e71")


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(lfohold.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(dn2_111):
    return lfohold.apply(dn2_111).payloads[lfohold.SECTION]


def test_stock_bytes_are_the_two_stores(stock):
    for at, want, _new, _what in lfohold.SITES:
        off = at - lfohold.BASE
        assert stock[off:off + len(want)] == want
    # the stores themselves: movel %a0@,%a2@(84) and movel %a0,%a2@(84)
    assert [w[4:] for _a, w, _n, _w in lfohold.SITES] == [bytes.fromhex("25500054"), bytes.fromhex("25480054")]


def test_writes_two_nops_and_nothing_else(stock, applied):
    assert len(applied) == len(stock)
    changed = [i for i in range(len(stock)) if stock[i] != applied[i]]
    want = set()
    for at, _stock, _new, _what in lfohold.SITES:
        off = at + 4 - lfohold.BASE
        assert applied[off:off + 4] == NOP2
        want |= set(range(off, off + 4))
    assert set(changed) <= want


def test_extents_cover_the_change(stock, applied):
    changed = [i for i in range(len(stock)) if stock[i] != applied[i]]
    for i in changed:
        assert any(e.start <= i < e.end for e in lfohold.extents())


def test_refuses_an_image_already_patched(dn2_111, applied):
    from dnfw.cli.mods import _staged
    staged = _staged(dn2_111, {lfohold.SECTION: applied})
    with pytest.raises(ModError):
        lfohold.apply(staged)


def test_shares_no_byte_with_any_mod(dn2_111):
    from dnfw.cli.mods import REGISTRY
    named = [(mid, list(mod.extents(dn2_111))) for mid, mod in REGISTRY.items()
             if mid not in ("transients",)]
    ours = [n for n in named if n[0] == lfohold.ID]
    for other in named:
        if other[0] != lfohold.ID:
            assert check_compatible(ours + [other]) == [], other[0]
