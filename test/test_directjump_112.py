"""directjump on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_directjump_mod.py's."""

import json
import pathlib
import struct

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import directjump, ramcheck

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
SPEC = directjump.SPECS["1.12"]

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


def test_applies_to_stock_1_12_inside_its_ram(firmware):
    base = firmware.container.find(directjump.SECTION).unpack()
    content = directjump.apply(firmware).payloads[directjump.SECTION]
    ram = directjump.ram("1.12")
    assert ramcheck.in_stock_dma(base, content, ram) == []
    assert ramcheck.undeclared(base, content, ram, directjump.NOT_RAM) == []


def test_the_switch_moves_with_the_settings_block():
    """arpscale's 1.12 toggle plus 0x12, as on 1.11 (0x405cd8af + 0x12)"""
    arpscale_flag = json.loads((ROOT / "src/dnfw/mods/arpscale_code_1.12.json").read_text())["flag"]
    assert SPEC["flag"] == arpscale_flag + 0x12 == 0x405CE8C1
    assert [e.start for e in directjump.ram("1.12") if "switch" in e.what] == [0x405CE8C1]


def test_the_hooks_and_vtable_entries_are_at_1_12_s_sites():
    assert [e["va"] for e in SPEC["edits"]] == [0x400D9F74, 0x400DA56A, 0x400DA5BE, 0x400DA84A, 0x400DA90A,
                                               0x400DA926, 0x400FA3AC, 0x40200CDC, 0x40200D8C]


def test_the_code_names_1_12_s_sequencer_queue_and_switch():
    """The playing pattern, the timed queue, the record release, the switch and the ticks table:
    each moved, and the code names only the moved one"""
    blob = bytes.fromhex(SPEC["code"]["blob"])
    for va in (0x42C5A9A0, 0x44644228, 0x40138A0C, 0x400DA58E, 0x401F6B08):
        assert struct.pack(">I", osport.addr("1.12", va)) in blob, hex(va)
        assert struct.pack(">I", va) not in blob, hex(va)
