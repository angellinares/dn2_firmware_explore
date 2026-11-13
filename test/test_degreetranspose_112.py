"""degreetranspose on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_degreetranspose_mod.py's."""

import json
import pathlib
import struct

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import degreetranspose

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
SPEC = degreetranspose.SPECS["1.12"]

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


def test_applies_on_1_12(firmware):
    assert degreetranspose.apply(firmware).payloads[degreetranspose.SECTION]


def test_the_moved_sites_are_1_12_s():
    """The load and save masks, the track default, the transpose reset and the MIDI note
    on and off move; the frame ISR and the keyboard view do not"""
    one_eleven = json.loads((ROOT / "src/dnfw/mods/degreetranspose_code.json").read_text())
    moved = {a["va"]: b["va"] for a, b in zip(one_eleven["edits"], SPEC["edits"]) if a["va"] != b["va"]}
    assert moved == {va: osport.addr("1.12", va) for va in moved}
    assert len(moved) == 6


def test_the_code_names_1_12_s_scales_playback_and_text():
    blob = bytes.fromhex(SPEC["code"]["blob"])
    for va in (0x4020EC20, 0x4020DEA0, 0x42C5A9A0, 0x4011545C, 0x44507EB8, 0x40215CCA):
        assert struct.pack(">I", osport.addr("1.12", va)) in blob, hex(va)
        assert struct.pack(">I", va) not in blob, hex(va)
