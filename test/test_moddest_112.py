"""moddest on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.

moddest finds its table by signature, not by address, so 1.12 needs no spec of its own. This
checks that the table it finds is where the map puts 1.11's, and that the 13 records it opens
are the ones it opens on 1.11. The 1.11 build is test_moddest_mod.py's."""

import pathlib

import pytest

from dnfw import osport
from dnfw.checkout import resources_dir
from dnfw.mods import moddest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
BASE = 0x40000400

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def main_os():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX)).container.find(moddest.SECTION).unpack()


def test_the_table_is_where_the_map_puts_1_11_s(main_os):
    start, count = moddest.find_table(main_os)
    assert BASE + start == osport.addr("1.12", 0x401F7F94)
    assert count == 321


def test_the_thirteen_masks_sit_where_they_do_on_1_11(main_os):
    """The same records: each mask the same distance into the table as on 1.11"""
    one_eleven = (0x401F87B0, 0x401F87EC, 0x401F8E04, 0x401F90D4)     # the first four on 1.11
    start, _ = moddest.find_table(main_os)
    found = [at - start for at, _ in moddest._targets(main_os)]
    assert len(found) == 13
    assert found[:4] == [va - 0x401F7F94 for va in one_eleven]


def test_applies_on_1_12():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    out = moddest.apply(load(read_image(STOCK_SYX))).payloads[moddest.SECTION]
    assert len(out) == 3_196_288
