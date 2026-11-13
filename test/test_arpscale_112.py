"""arpscale on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_arpscale_mod.py's."""

import json
import pathlib
import struct

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import arpscale

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
SPEC = arpscale.SPECS["1.12"]

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


def test_applies_on_1_12(firmware):
    assert arpscale.apply(firmware).payloads[arpscale.SECTION]


def test_the_toggle_is_the_byte_after_reloadconfirm_s():
    """Both move with the settings block (+0x1000): reloadconfirm's 1.12 flag, plus one"""
    reload_flag = json.loads((ROOT / "src/dnfw/mods/reloadconfirm_code_1.12.json").read_text())["flag"]
    assert SPEC["flag"] == reload_flag + 1 == 0x405CE8AF
    assert [e.start for e in arpscale.ram("1.12") if "toggle" in e.what] == [0x405CE8AF]


def test_the_moved_sites_are_1_12_s():
    one_eleven = json.loads((ROOT / "src/dnfw/mods/arpscale_code.json").read_text())
    moved = {a["va"]: b["va"] for a, b in zip(one_eleven["edits"], SPEC["edits"]) if a["va"] != b["va"]}
    assert moved == {0x40098630: 0x40098794, 0x400DD5A0: 0x400DD704, 0x400DD8C8: 0x400DDA2C}


def test_the_code_names_1_12_s_scales_and_playback():
    blob = bytes.fromhex(SPEC["code"]["blob"])
    for va in (0x4020EC20, 0x4020DEA0, 0x42C5A9A0, 0x401DDDEC):     # degrees, semitones, playback, event
        assert struct.pack(">I", osport.addr("1.12", va)) in blob, hex(va)
        assert struct.pack(">I", va) not in blob, hex(va)
