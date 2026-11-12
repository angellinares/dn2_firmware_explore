"""reloadconfirm on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_reloadconfirm_mod.py's."""

import pathlib
import struct

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import ModError, platform, reloadconfirm

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
BASE = reloadconfirm.BASE

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


@pytest.fixture(scope="module")
def applied(firmware):
    return reloadconfirm.apply(firmware).payloads[reloadconfirm.SECTION]


def test_the_hooks_land_at_1_12_s_sites(applied):
    spec = reloadconfirm.SPECS["1.12"]
    sites = [e["va"] for e in spec["edits"]]
    assert sites == [0x4005F1A2, 0x400987A2]            # FUNC + NO (same), PERSONALIZE's epilogue (+0x164)
    labels = spec["code"]["labels"]
    for va, label in zip(sites, ("key_hook", "menu_hook")):
        assert applied[va - BASE:va - BASE + 6] == b"\x4e\xf9" + struct.pack(">I", labels[label])


def test_the_toggle_moves_with_the_settings_block():
    """No instruction names the block's tail, so the map cannot place FLAG: it is the block's 1.12
    start (+0x1000, every vote) plus the same 0x52"""
    spec = reloadconfirm.SPECS["1.12"]
    assert spec["flag"] == 0x405CE8AE
    blob = bytes.fromhex(spec["code"]["blob"])
    assert struct.pack(">I", 0x405CE8AE) in blob and struct.pack(">I", 0x405CD8AE) not in blob
    assert [x.start for x in reloadconfirm.ram("1.12")] == [reloadconfirm.CODE_VA, 0x405CE8AE]


def test_no_literal_names_the_1_12_tail(firmware):
    """The flag is BSS (past the image), cleared at reset; what matters is that stock never names
    the tail it lives in, on 1.12 as on 1.11"""
    main = firmware.container.find(3).unpack()
    named = {struct.unpack_from(">I", main, i)[0] for i in range(0, len(main) - 3, 2)}
    assert not any(0x405CE8AE <= v < 0x405CE95C for v in named)


def test_the_chunk_runs_where_1_11_s_does(applied):
    _, chunks = platform.split(applied)
    codes = [platform.area.CodeChunk.unpack(d) for c, d in chunks if c == platform.area.CODE]
    assert [c.load for c in codes] == [reloadconfirm.CODE_VA]


def test_an_unported_version_is_refused_by_name():
    with pytest.raises(ModError, match="not yet ported to Digitone II 1.13"):
        reloadconfirm.specs.pick(reloadconfirm.SPECS, "1.13", reloadconfirm.ID)
