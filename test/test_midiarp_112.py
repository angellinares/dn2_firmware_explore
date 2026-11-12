"""midiarp on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_midiarp_mod.py's."""

import pathlib
import struct

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import midiarp, platform

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
BASE = midiarp.BASE

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


@pytest.fixture(scope="module")
def applied(firmware):
    return midiarp.apply(firmware).payloads[midiarp.SECTION]


def test_the_edits_are_at_1_12_s_sites():
    """Three jsr operands keep or move by the map: another project's map gave the opcodes, 2 B early"""
    sites = sorted(e["va"] for e in midiarp.SPECS["1.12"]["edits"])
    assert sites == sorted([0x400187F6, 0x400268FA, 0x4005F9C2, 0x400D91C2, 0x400DA040, 0x40121BF6, 0x40122066])


def test_the_length_tables_are_read_from_1_12(firmware, applied):
    spec = midiarp.SPECS["1.12"]
    assert (spec["trig_lengths_va"], spec["arp_lengths_va"]) == (0x401D8CE8, 0x40288048)
    main = firmware.container.find(3).unpack()
    _, chunks = platform.split(applied)
    image = next(platform.area.CodeChunk.unpack(d).image for c, d in chunks if c == platform.area.CODE)
    lut = spec["lut_va"] - spec["code"]["va"]
    assert image[lut:lut + midiarp.LUT_BYTES] == midiarp.nlen_lut(main, spec)


def test_the_code_names_1_12_s_routines():
    blob = bytes.fromhex(midiarp.SPECS["1.12"]["code"]["blob"])
    for va in (0x4013801C, 0x4012BB90, 0x400DB688, 0x4012A694, 0x4012A6E8, 0x4460F4B8):
        assert struct.pack(">I", va) in blob, hex(va)
    for va in (0x40137D3C, 0x4012B8B0, 0x400DB524, 0x4012A3B4, 0x4012A408, 0x4460E4B8):
        assert struct.pack(">I", va) not in blob, hex(va)
