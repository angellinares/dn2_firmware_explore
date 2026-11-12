"""arpplocks on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_arpplocks_mod.py's."""

import json
import pathlib
import struct

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import arpplocks

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
SPEC = arpplocks.SPECS["1.12"]

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


def test_applies_on_1_12(firmware):
    assert arpplocks.apply(firmware).payloads[arpplocks.SECTION]


def test_the_moved_sites_are_1_12_s():
    """The pattern load and save, the lock-list builder, its gate, the apply and the id lookup
    move +0x164; the arp menu, the note set and the recount do not"""
    one_eleven = json.loads((ROOT / "src/dnfw/mods/arpplocks_code.json").read_text())
    moved = {a["va"]: b["va"] for a, b in zip(one_eleven["edits"], SPEC["edits"]) if a["va"] != b["va"]}
    assert moved == {0x400D85E8: 0x400D874C, 0x400D89B0: 0x400D8B14, 0x400DB092: 0x400DB1F6,
                     0x400DCCC0: 0x400DCE24, 0x400DE595: 0x400DE6F9, 0x400DE59E: 0x400DE702,
                     0x400DE5E6: 0x400DE74A, 0x400DE75E: 0x400DE8C2}


def test_the_code_names_1_12_s_addresses():
    """The routines it calls and the data it reads are 1.12's, none of them 1.11's"""
    blob = bytes.fromhex(SPEC["code"]["blob"])
    for va in (0x4018A97A, 0x4019C40C, 0x401160BC, 0x4011C7BA,       # app, bit test, key, redraw
               0x4058E8D8, 0x405984A8, 0x446478C8):                 # track sounds, arp state, held
        assert struct.pack(">I", osport.addr("1.12", va)) in blob, hex(va)
        assert struct.pack(">I", va) not in blob, hex(va)
    for base, d in ((0x400DCCC0, 8), (0x400D85E8, 6), (0x400DB092, 8)):   # jumps back into stock
        assert struct.pack(">I", osport.addr("1.12", base) + d) in blob, hex(base + d)


def test_the_code_sits_where_1_11_s_does():
    """Same chunk address and labels, so the RAM and NOT_RAM entries hold on both"""
    assert SPEC["code"]["va"] == arpplocks.SPEC["code"]["va"]
    assert SPEC["code"]["labels"] == arpplocks.SPEC["code"]["labels"]
    assert [(e.start, e.length) for e in arpplocks.ram("1.12")] == [(e.start, e.length) for e in arpplocks.ram()]
