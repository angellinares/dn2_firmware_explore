"""bootscreen on OS 1.12 (issue #382). Reads the user's own stock images and skips without them.

On 1.12 stock's DMA section runs to 0x46709340, over 1.11's stamp at 0x46708000, so the stamp
moves to 0x467e8000 (docs/mod-memory-regions.md). The 1.11 build is test_bootscreen_mark.py's
and the platform tests'."""

import pathlib
import struct

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import bootscreen, ramcheck

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
SPEC, ONE_ELEVEN = bootscreen.SPECS["1.12"], bootscreen.SPECS["1.11"]

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


@pytest.fixture(scope="module")
def applied(firmware):
    mark = bootscreen.image_from_pixels({(x, x // 2) for x in range(128)})
    return bootscreen.apply(firmware, [mark])


def test_the_stamp_is_above_1_12_s_dma_section():
    assert SPEC["load"] == 0x467E8000 and ONE_ELEVEN["load"] == 0x46708000
    lo, hi = 0x466C0000, 0x46709340
    assert lo <= ONE_ELEVEN["load"] and ONE_ELEVEN["load"] + 320 <= hi       # why it moved
    assert SPEC["load"] >= hi


def test_the_sites_are_1_11_s_mapped():
    for key in ("intro_va", "tunnel_x_va", "tunnel_y_va", "area_va"):
        assert SPEC[key] == osport.addr("1.12", ONE_ELEVEN[key]), key


def test_the_code_differs_only_in_its_addresses():
    """The same 320 bytes but for six address words, each 1.11's on 1.12"""
    old, new = bytes.fromhex(ONE_ELEVEN["code"]), bytes.fromhex(SPEC["code"])
    assert len(old) == len(new)
    moved = {0x42C4568C: 0x42C4668C, 0x400D388E: 0x400D39F2, 0x40114D94: 0x40115074,
             0x42C4567C: 0x42C4667C, 0x401157FC: 0x40115ADC}
    for a, b in moved.items():
        assert old.count(struct.pack(">I", a)) == new.count(struct.pack(">I", b)) >= 1, hex(a)
    patched = old
    for a, b in moved.items():
        patched = patched.replace(struct.pack(">I", a), struct.pack(">I", b))
    assert patched == new


def test_applies_and_hooks_the_intro(applied):
    content = applied.payloads[bootscreen.SECTION]
    at = SPEC["intro_va"] - bootscreen.BASE
    assert content[at:at + 8] == b"\x4e\xf9" + struct.pack(">I", 0x467E8000) + b"\x4e\x71"


def test_nothing_of_ours_is_in_stock_s_dma_section(firmware, applied):
    stock = firmware.container.find(bootscreen.SECTION).unpack()
    content = applied.payloads[bootscreen.SECTION]
    assert ramcheck.in_stock_dma(stock, content, bootscreen.ram("1.12")) == []
    assert ramcheck.undeclared(stock, content, bootscreen.ram("1.12")) == []
