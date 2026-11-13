"""transients on OS 1.12 (issue #382). Reads the user's own stock images and skips without them.

transients writes section 7, the DSP image, which is byte for byte the same in 1.11 and 1.12,
and it locates its bank and table through that image's boot stream. So on 1.12 it needs no
change: the same samples give the same section 7 as on 1.11. The 1.11 tests are
test_transients_table.py's."""

import math
import pathlib
import struct
import wave

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import transients

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIRMWARE = resources_dir(ROOT) / "00_Firmware"
STOCKS = {"1.11": FIRMWARE / "Digitone_II_OS1.11_dist.zip", "1.12": FIRMWARE / "Digitone_II_OS1.12.syx"}

pytestmark = pytest.mark.skipif(not all(p.exists() for p in STOCKS.values()), reason="no stock images")


def _load(os):
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCKS[os]))


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    path = tmp_path_factory.mktemp("transients") / "click.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"".join(struct.pack("<h", int(20000 * math.exp(-i / 300) * math.sin(i / 3)))
                               for i in range(3000)))
    return path


def test_section_7_is_the_same_on_both():
    assert _load("1.11").container.find(7).unpack() == _load("1.12").container.find(7).unpack()


@pytest.mark.parametrize("equal", [False, True])
def test_the_same_samples_give_the_same_section_7(sample, equal):
    out = {os: transients.apply(_load(os), [sample], equal=equal).payloads[transients.SECTION]
           for os in STOCKS}
    assert out["1.11"] == out["1.12"]
