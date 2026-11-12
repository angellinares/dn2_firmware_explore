"""layermidi on OS 1.12 (issue #382): the 1.11 mod's two hooks and code, built for 1.12.

Reads the user's own stock 1.12 image and skips without it. The 1.11 build is test_layermidi_mod.py's."""

import pathlib
import struct

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import layermidi, platform
from dnfw.osport import versions

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
BASE = layermidi.BASE

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


@pytest.fixture(scope="module")
def applied(firmware):
    return layermidi.apply(firmware).payloads[layermidi.SECTION]


def test_the_1_12_spec_is_used(firmware):
    assert versions.of_firmware(firmware).name == "1.12"
    assert layermidi.SPECS["1.12"]["os"] == "Digitone II 1.12"


def test_the_hooks_are_where_1_11_has_them_and_jump_to_the_chunk(applied):
    spec = layermidi.SPECS["1.12"]
    for e in spec["edits"]:
        at = e["va"] - BASE
        assert applied[at:at + len(e["new"]) // 2].hex() == e["new"]
    labels = spec["code"]["labels"]
    assert applied[0x40026980 - BASE:0x40026980 - BASE + 6] == b"\x4e\xb9" + struct.pack(">I", labels["note_hook"])
    assert applied[0x40026D32 - BASE:0x40026D32 - BASE + 6] == b"\x4e\xf9" + struct.pack(">I", labels["release_hook"])


def test_the_code_names_1_12_s_addresses():
    """The MIDI record allocator and its free list moved; the release returns where it did"""
    blob = bytes.fromhex(layermidi.SPECS["1.12"]["code"]["blob"])
    assert struct.pack(">I", 0x4012A6E8) in blob and struct.pack(">I", 0x4012A408) not in blob
    assert struct.pack(">I", 0x4460F4B8) in blob and struct.pack(">I", 0x4460E4B8) not in blob
    assert struct.pack(">I", 0x40026D38) in blob


def test_the_chunk_runs_where_1_11_s_does(applied):
    base, chunks = platform.split(applied)
    codes = [platform.area.CodeChunk.unpack(d) for c, d in chunks if c == platform.area.CODE]
    assert [c.load for c in codes] == [layermidi.CODE_VA]
    assert codes[0].image == bytes.fromhex(layermidi.SPECS["1.12"]["code"]["blob"])


def test_nothing_else_of_stock_changes(firmware, applied):
    stock = firmware.container.find(layermidi.SECTION).unpack()
    base, _ = platform.split(applied)
    edits = [(e["va"] - BASE, len(e["new"]) // 2) for e in layermidi.SPECS["1.12"]["edits"]]
    loader = platform.loader_extents(0, "1.12")
    owned = edits + [(x.start, x.length) for x in loader]
    changed = [i for i in range(len(stock)) if base[i] != stock[i]]
    assert changed and all(any(a <= i < a + n for a, n in owned) for i in changed)
