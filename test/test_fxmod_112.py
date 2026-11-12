"""fxmod on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_fxmod_mod.py's."""

import json
import pathlib

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import fxmod

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
SPEC = fxmod.SPECS["1.12"]
ONE_ELEVEN = json.loads((ROOT / "src/dnfw/mods/fxmod_code.json").read_text())

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


def test_applies_on_1_12(firmware):
    assert fxmod.apply(firmware).payloads[fxmod.SECTION]


def test_the_cave_and_handler_move_with_the_map():
    """The cave is 1.11's moved +0x540 (the same 170 zero bytes, the same classifier verdict),
    and the bus handler keeps its place in it"""
    assert SPEC["cave_va"] == osport.addr("1.12", ONE_ELEVEN["cave_va"]) == 0x4028EF42
    assert SPEC["bus"]["handler"] - SPEC["cave_va"] == ONE_ELEVEN["bus"]["handler"] - ONE_ELEVEN["cave_va"]
    assert SPEC["cave_used"] == ONE_ELEVEN["cave_used"]


def test_every_site_is_1_11_s_mapped():
    assert [e["va"] for e in SPEC["edits"]] == [osport.addr("1.12", e["va"]) for e in ONE_ELEVEN["edits"]]
    assert [g["va"] for g in SPEC["guards"]] == [osport.addr("1.12", g["va"]) for g in ONE_ELEVEN["guards"]]


def test_the_chorus_group_points_at_1_12_s_chr():
    edit = next(e for e in SPEC["edits"] if e["va"] in range(0x401F7B30, 0x401F7B34))
    assert "0c34" in edit["new"]          # 0x40210c34, 1.11's 0x4021077c 'CHR' moved +0x4b8
