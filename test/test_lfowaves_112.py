"""lfowaves on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_lfowaves_mod.py's."""

import json
import pathlib
import struct

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import lfowaves, platform
from dnfw.patch import paramtable

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
SPEC = lfowaves.SPECS["1.12"]

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


@pytest.fixture(scope="module")
def applied(firmware):
    return lfowaves.apply(firmware).payloads[lfowaves.SECTION]


def test_applies_on_1_12(applied):
    base, chunks = platform.split(applied)
    (copy,) = [c for s, _, c in platform.displaced(chunks) if s == osport.addr("1.12", lfowaves.SHORT_NAME)]
    assert copy > lfowaves.RUNTIME_VA


def test_the_parameter_table_is_in_place_on_stock_1_12(firmware):
    assert paramtable.moved(firmware.container.find(3).unpack(), lfowaves.BASE, "1.12") is None


def test_the_fills_read_1_12_s_tables():
    """The names and the four value tables are read from the user's 1.12 file, at the map's addresses"""
    one_eleven = json.loads((ROOT / "src/dnfw/mods/lfowaves_code.json").read_text())
    assert [f["from_va"] for f in SPEC["fills"]] == [osport.addr("1.12", f["from_va"]) for f in one_eleven["fills"]]


def test_the_blob_names_1_12_s_stock():
    """The return points, the strings, the Bitmap vtable and mask and the glyph sets are 1.12's"""
    blob = bytes.fromhex(SPEC["blob"])
    for va in (0x40137612, 0x40137894, 0x40137A00, 0x40210BCE, 0x40210C9E, 0x40219C2D,
               0x4020650C, 0x402B8D90, 0x44507B68):
        assert struct.pack(">I", osport.addr("1.12", va)) in blob, hex(va)
        assert struct.pack(">I", va) not in blob, hex(va)


def test_the_copy_stub_and_start_up_call_are_left_to_the_platform():
    sites = {e["va"] for e in lfowaves.edits("1.12")}
    assert 0x4000053F not in sites and not any(0x402CFA6C <= va < 0x402CFA6C + 46 for va in sites)
    assert len(lfowaves.edits("1.12")) == len(lfowaves.EDITS)
