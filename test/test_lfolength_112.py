"""lfolength on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_lfolength_mod.py's."""

import pathlib
import struct

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import lfolength

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
SPEC = lfolength.SPECS["1.12"]

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


def test_applies_on_1_12(firmware):
    assert lfolength.apply(firmware).payloads[lfolength.SECTION]


def test_the_hooks_are_at_1_12_s_sites():
    hooks = sorted(e["va"] for e in SPEC["edits"] if e["what"].startswith("lfolength hook"))
    assert hooks == [0x4013783C, 0x401378C4, 0x40137C46, 0x40137CCC]


def test_the_routines_return_to_1_12_s_code():
    """Every jmp back into stock is the 1.11 target moved by the map (+0x2e0), none is 1.11's"""
    blob = bytes.fromhex(SPEC["code"]["blob"])
    for va in (0x40137970, 0x4013797E, 0x401379F2, 0x40137566, 0x40137574, 0x401375EA, 0x4013761A):
        assert struct.pack(">I", osport.addr("1.12", va)) in blob, hex(va)
        assert struct.pack(">I", va) not in blob, hex(va)


def test_the_latch_is_in_1_12_s_state_blocks():
    assert SPEC["state_blocks"] == [0x44640C18, 0x44640498]
    latches = [e for e in lfolength.ram("1.12") if "latch" in e.what]
    assert latches[0].start == 0x44640C18 + lfolength.LATCH
