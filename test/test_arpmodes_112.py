"""arpmodes on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_arpmodes_mod.py's."""

import pathlib
import struct

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import arpmodes

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
BASE = arpmodes.BASE

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


@pytest.fixture(scope="module")
def applied(firmware):
    return arpmodes.apply(firmware).payloads[arpmodes.SECTION]


def test_the_caves_are_1_12_s_and_were_empty(firmware):
    """Both caves moved +0x540; in stock 1.12 each is zero with 4 B either side"""
    main = firmware.container.find(3).unpack()
    caves = [e for e in arpmodes.SPECS["1.12"]["edits"] if e["what"] == "arp modes code cave"]
    assert sorted(e["va"] for e in caves) == [0x402901F4, 0x402D0E00]
    for e in caves:
        at = e["va"] - BASE
        assert not any(main[at - 4:at + len(e["new"]) // 2 + 4])


def test_the_dispatch_jumps_to_the_first_cave(applied):
    assert applied[0x4002A13C - BASE:0x4002A13C - BASE + 6] == b"\x4e\xf9" + struct.pack(">I", 0x402D0E00)


def test_the_mode_bounds_are_raised_to_six(applied):
    for va in (0x4004BEFA, 0x4004BF00, 0x4004BFB4, 0x4004BFC6, 0x400DD694):
        assert applied[va - BASE + 1] == arpmodes.SPECS["1.12"]["mode_max"] == 6, hex(va)


def test_the_code_reads_1_12_s_tick():
    cave = next(e for e in arpmodes.SPECS["1.12"]["edits"] if e["va"] == 0x402D0E00)
    code = bytes.fromhex(cave["new"])
    assert struct.pack(">I", 0x466768B0) in code and struct.pack(">I", 0x466758B0) not in code
