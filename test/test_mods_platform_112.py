"""The platform on OS 1.12 (issue #382): the same loader and area, at 1.12's places.

The 1.11 platform is unchanged (test_mods_platform.py, test_mods_bus.py). These read the user's own
stock 1.12 image and skip without it."""

import pathlib
import struct

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import ModError, bus, platform
from dnfw.osport import versions
from dnfw.patch import area

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
BASE = platform.BASE

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def stock():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX)).container.find(3).unpack()


def _code(load: int, body: bytes = bytes.fromhex("4e75")) -> tuple[bytes, bytes]:
    return area.CODE, area.CodeChunk(load, body).pack()


def test_the_spec_is_chosen_from_the_image(stock):
    assert platform.spec_for(stock)["os"] == "Digitone II 1.12"
    assert platform.spec_for(stock)["stock_length"] == versions.V112.main_length


def test_join_puts_the_loader_in_the_1_12_cave_and_the_area_at_its_stock_end(stock):
    spec = platform.SPECS["1.12"]
    out = platform.join(stock, [_code(0x46F00000)])
    link = spec["link_va"] - BASE
    loader = bytes.fromhex(spec["loader"])
    assert out[link:link + len(loader)] == loader and spec["link_va"] == 0x4028DFB0
    calls = spec["calls_va"] - BASE
    assert out[calls:calls + 8] == b"\x4e\xb9" + struct.pack(">I", 0x4028DFB0) + b"\x4e\x71"
    assert out[versions.V112.main_length:versions.V112.main_length + 4] == area.MAGIC
    # nothing else of stock changed
    changed = [i for i in range(len(stock)) if out[i] != stock[i]]
    assert all(calls <= i < calls + 8 or link <= i < link + len(loader) for i in changed)


def test_split_gives_back_stock_and_the_chunks(stock):
    chunk = _code(0x46F00000)
    out = platform.join(stock, [chunk])
    base, chunks = platform.split(out)
    assert base == platform.join(stock, [])[:len(stock)]          # stock, with the loader
    assert chunks == [chunk]


def test_a_bus_subscription_hooks_the_1_12_site(stock):
    spec = platform.SPECS["1.12"]
    out = platform.join(stock, [_code(0x46F00000), bus.subscribe(b"PSLT", 0x46F00000)])
    site = bus.site(spec, b"PSLT")
    assert site == 0x400DC18E                                     # 1.11's 0x400dc02a, +0x164
    entry = spec["bus"]["symbols"]["ev_param_slot"]
    assert out[site - BASE:site - BASE + 8] == b"\x4e\xf9" + struct.pack(">I", entry) + b"\x4e\x71"
    base, chunks = platform.split(out)
    assert base[site - BASE:site - BASE + 8].hex() == bus.EVENTS[b"PSLT"]["stock"]


def test_a_1_11_spec_never_lands_on_a_1_12_image(stock):
    with pytest.raises(ModError):
        platform.join(stock[:versions.V111.main_length - 1], [])     # neither length: refused
