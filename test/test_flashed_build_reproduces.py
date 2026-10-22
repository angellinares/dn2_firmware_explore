"""Today's mods rebuild the last build that passed on the instrument.

fmdepth2 (fxmod, Waverider 0.3.6, usbprobe and lfo4) passed its device test on 2026-10-20 and is
on the owner's unit. `dnfw mods apply` of the same mods must give the same image. The one allowed
difference is the /modinfo record's build part (commit, image id, hash). When a later build
passes on the instrument, it replaces FLASHED here.

This replaces test_lfo4_mod's byte equality with out/lfo4-fast: that build is from 2026-09-27,
before lfo4 1.0.1 moved its state arrays (fbac7a3), so the check had failed since 2026-10-11.
"""

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
FLASHED = ROOT / "00_Resources/02_Builds/fmdepth2-fxmod-lfo4-waverider-usbprobe_DN2_1.11.syx"
MODS = ["fxmod", "waverider", "usbprobe", "lfo4"]
PROBE_TAG = "fmdepth2-fxmod"


def _sections(path: pathlib.Path) -> dict[int, bytes]:
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return {s.id: s.unpack() or s.raw_payload for s in load(read_image(path)).container.sections}


def test_the_flashed_build_rebuilds(tmp_path):
    if not (STOCK_111.exists() and FLASHED.exists()):
        pytest.skip("stock 1.11 or the flashed build is not in 00_Resources")
    from dnfw.mods import modinfo
    out = tmp_path / "rebuilt_DN2_1.11.syx"
    done = subprocess.run([sys.executable, "-c", "import sys; from dnfw.cli.main import main; sys.exit(main(sys.argv[1:]))",
                           "mods", "apply", *[a for m in MODS for a in ("--mod", m)], "--probe-tag", PROBE_TAG,
                           str(STOCK_111), "-o", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-800:]
    want, got = _sections(FLASHED), _sections(out)
    assert sorted(want) == sorted(got)
    at = want[3].find(modinfo.MAGIC + bytes([0, 1, 1, 0]))
    assert at >= 0 and at == got[3].find(modinfo.MAGIC + bytes([0, 1, 1, 0]))
    for sid in want:
        a, b = bytearray(want[sid]), bytearray(got[sid])
        if sid == 3:
            for x in (a, b):
                x[at + 20:at + 24] = bytes(4)                 # the image id
                x[at + 56:at + 68] = bytes(12)                # the commit
                x[at + 252:at + 256] = bytes(4)               # the hash
        assert a == b, f"section {sid} differs from the flashed build"
