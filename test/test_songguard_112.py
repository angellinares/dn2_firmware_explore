"""songguard on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it."""

import pathlib

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import songguard

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


def test_the_edit_lands_at_1_12_s_song_load():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    fw = load(read_image(STOCK_SYX))
    main = fw.container.find(3).unpack()
    at = songguard.SITES["1.12"] - songguard.BASE
    assert main.count(songguard.STOCK) == 1 and main[at:at + 54] == songguard.STOCK
    out = songguard.apply(fw).payloads[3]
    assert out[at:at + 54] == songguard.NEW
    assert [e.start for e in songguard.extents(fw)] == [at]
