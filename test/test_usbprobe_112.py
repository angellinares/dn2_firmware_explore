"""usbprobe on OS 1.12 (issue #382). Reads the user's own stock 1.12 image and skips without it.
The 1.11 build is test_usbprobe_mod.py's."""

import pathlib
import subprocess
import sys

import pytest

from dnfw.checkout import resources_dir
from dnfw.mods import usbprobe

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_SYX = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.12.syx"
SPEC = usbprobe.SPECS["1.12"]

pytestmark = pytest.mark.skipif(not STOCK_SYX.exists(), reason="no stock 1.12 image")


@pytest.fixture(scope="module")
def firmware():
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return load(read_image(STOCK_SYX))


def test_applies_on_1_12_with_the_tag(firmware):
    out = usbprobe.apply(firmware, tag="t112").payloads[usbprobe.SECTION]
    at = SPEC["tag"]["va"] - usbprobe.BASE
    assert out[at:at + 5] == b"t112\x00"


def test_the_hooks_and_caves_are_1_12_s():
    sites = sorted(e["va"] for e in SPEC["edits"])
    assert sites == [0x40000438, 0x40025E3E, 0x40027B82, 0x4012197A, 0x402CFA6C, 0x402D0BA8]


def test_the_probe_names_1_12_s_data():
    """The router's header, the frame and sample counts, the TCBs and the timebase: map_1.12.json"""
    code = bytes.fromhex(next(e["new"] for e in SPEC["edits"] if e["va"] == 0x402CFA6C))
    for va in (0x40207F9E, 0x4058F8D4, 0x4664BCDC):
        assert va.to_bytes(4, "big") in code, hex(va)
    for va in (0x40207AE6, 0x4058E8D4, 0x4664ACDC):
        assert va.to_bytes(4, "big") not in code, hex(va)


def test_the_include_is_generated():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/gen_dn2_header.py"), "--os", "1.12",
                        "--inc", "csrc/usbprobe/dn2_111.inc", "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
