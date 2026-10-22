"""The LFO4 mod: it applies to stock 1.11 and refuses what it cannot sit on.

Byte equality with the image on the instrument is test_flashed_build_reproduces.py: the last
build that passed there, rebuilt from today's mods. The old check here compared with
out/lfo4-fast (2026-09-27), which predates lfo4 1.0.1's state-array move (fbac7a3).
"""

import pathlib
import struct

import pytest

from dnfw.mods import ModError, lfo4, moddest, platform
from dnfw.patch import area, paramtable

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
BASE = lfo4.BASE


@pytest.fixture(scope="module")
def dn2_111():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def stock(dn2_111):
    return dn2_111.container.find(lfo4.SECTION).unpack()


@pytest.fixture(scope="module")
def applied(stock):
    return lfo4.compose(stock)


def _table_at(content: bytes) -> int:
    """Where the relocated table starts in CONTENT: its CODE chunk's image."""
    blob = content[platform.STOCK_LENGTH:]
    for i in range(struct.unpack_from(">I", blob, 8)[0]):
        cid, (off, n) = blob[12 + 12 * i:16 + 12 * i], struct.unpack_from(">II", blob, 16 + 12 * i)
        if cid == area.CODE and area.CodeChunk.unpack(blob[off:off + n]).load == lfo4.SPEC["table_va"]:
            return platform.STOCK_LENGTH + off + 16
    raise AssertionError("no CODE chunk holds the relocated table")


def test_changes_nothing_outside_its_extents(stock, applied):
    allowed = [(e.start, e.end) for e in lfo4.extents()]
    stray = [i for i in range(len(stock))
             if stock[i] != applied[i] and not any(lo <= i < hi for lo, hi in allowed)]
    assert stray == []
    (appended,) = [e for e in lfo4.extents() if e.what == "the appended DNFW area"]
    assert len(applied) == appended.end


def test_ships_no_stock_table():
    """The relocated table's place in the packaged blob is blank."""
    blob = bytes.fromhex(lfo4.SPEC["blob"])
    at = lfo4.SPEC["table_offset"]
    assert not any(blob[at:at + paramtable.RECORD * lfo4.SPEC["table_records"]])


def test_refuses_an_image_that_already_grew(stock):
    with pytest.raises(ModError, match="appended"):
        lfo4.compose(stock + bytes(16))


def test_refuses_a_changed_edit_site(stock):
    e = lfo4._edits()[0]
    bad = bytearray(stock)
    bad[e["va"] - BASE] ^= 0xFF
    with pytest.raises(ModError, match="not stock"):
        lfo4.compose(bytes(bad))


def test_carries_a_table_edit_made_before_it(dn2_111, stock):
    """moddest opens thirteen masks in the stock table; applied first, they
    are in LFO4's relocated copy -- which is why the CLI applies lfo4 last."""
    opened = moddest.apply(dn2_111).payloads[moddest.SECTION]
    out = lfo4.compose(opened)
    table = paramtable.TABLE - BASE
    moved = _table_at(out)
    for at, label in moddest._targets(stock):
        assert struct.unpack_from(">I", out, moved + at - table)[0] == moddest.OPEN, label


def test_carries_fxmod_table_edits(dn2_111, stock):
    """fxmod rewrites ten Chorus records' masks inside the stock table."""
    from dnfw.mods import fxmod
    edited = fxmod.apply(dn2_111).payloads[fxmod.SECTION]
    out = lfo4.compose(edited)
    lo = paramtable.TABLE - BASE
    hi = lo + paramtable.RECORD * paramtable.COUNT
    moved = _table_at(out)
    inside = [e for e in fxmod.SPEC["edits"] if lo <= e["va"] - BASE < hi]
    assert inside, "fxmod has no edit in the table any more; this test is stale"
    for e in inside:
        at, new = e["va"] - BASE, bytes.fromhex(e["new"])
        assert out[moved + at - lo:moved + at - lo + len(new)] == new, hex(e["va"])
