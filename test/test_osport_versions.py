"""dnfw.osport.versions: the stock images the mods know, read from the user's own files (issue #382)."""

import pathlib
import struct

import pytest

from dnfw.checkout import resources_dir
from dnfw.osport import versions as V

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIRMWARE = resources_dir(ROOT) / "00_Firmware"
IMAGES = {"1.11": FIRMWARE / "Digitone_II_OS1.11_dist.zip", "1.12": FIRMWARE / "Digitone_II_OS1.12.syx"}


def _main_os(path: pathlib.Path) -> bytes:
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    if not path.exists():
        pytest.skip(f"no stock image {path.name}")
    return load(read_image(path)).container.find(3).unpack()


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_identify_names_each_stock_image(name):
    main = _main_os(IMAGES[name])
    v = V.identify(main)
    assert v.name == name and len(main) == v.main_length


def test_identify_refuses_anything_else():
    main = _main_os(IMAGES["1.11"])
    changed = bytearray(main)
    changed[0x1000] ^= 1                                        # one bit: no longer stock
    with pytest.raises(V.UnknownImage):
        V.identify(bytes(changed))
    with pytest.raises(V.UnknownImage):
        V.identify(main[:-2])


def test_an_appended_area_still_names_its_stock_part():
    main = _main_os(IMAGES["1.12"])
    assert V.by_length(main + b"DNFW" + bytes(60)).name == "1.12"
    assert V.by_length(main[:-1]) is None


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_the_constants_match_each_image(name):
    """The reset clear's end is a literal in its own image only; the loader cave is 138 zero bytes;
    the DMA section's start is the lowest uncached-window literal"""
    main = _main_os(IMAGES[name])
    v = V.VERSIONS[name]
    words = {struct.unpack_from(">I", main, i)[0] for i in range(0, len(main) - 3, 2)}
    assert v.clear_end in words
    other = next(o for o in V.VERSIONS.values() if o.name != name)
    assert other.clear_end not in words
    cave = v.loader_cave - V.BASE
    assert main[cave:cave + 138] == bytes(138)
    window = sorted(w for w in words if 0x4E6B0000 <= w < 0x4E6D0000 and w & 0xFFF == 0)
    assert window[0] == v.dma[0] + 0x08000000


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_a_modded_main_os_still_names_its_version(name):
    """An edit anywhere and an appended area: the version comes from where the area starts"""
    main = bytearray(_main_os(IMAGES[name]))
    main[0x2000] ^= 0xFF                                       # an edit: no longer stock
    assert V.of_main_os(bytes(main)).name == name               # stock length, no area
    assert V.of_main_os(bytes(main) + b"DNFW" + bytes(4092)).name == name


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_the_build_stamp_names_the_firmware(name):
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    if not IMAGES[name].exists():
        pytest.skip(f"no stock image {IMAGES[name].name}")
    assert V.of_firmware(load(read_image(IMAGES[name]))).name == name
