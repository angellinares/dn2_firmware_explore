"""Today's mods rebuild the last build that passed on the instrument.

wrl2b (main334's 12 mods, with the level builder in L2, #335) passed its device test on 2026-11-03.
Before it, firstarg1 (2026-11-02, #327), modinfo512 (2026-11-02, #322).
Before it, lfo4fix4 (2026-10-29, #301), lfo4fix2 (2026-10-27), batcha1 (2026-10-22) and
fmdepth2 (2026-10-20). `dnfw mods apply` of the same mods must give the same image. The one allowed
difference is the /modinfo record's build part (commit, image id, hash). When a later build
passes on the instrument, it replaces FLASHED here.

The record also holds the hash of each mod's code (`*_code.json`). When one of them differs from
today's, the bytes cannot match, and the test is an expected failure that names the changed mods.

This replaces test_lfo4_mod's byte equality with out/lfo4-fast: that build is from 2026-09-27,
before lfo4 1.0.1 moved its state arrays (fbac7a3), so the check had failed since 2026-10-11.
"""

import pathlib
import subprocess
import sys

import pytest
from dnfw.checkout import resources_dir  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
STOCK_111 = resources_dir(ROOT) / "00_Firmware/Digitone_II_OS1.11_dist.zip"
FLASHED = resources_dir(ROOT) / "02_Builds/wrl2b-waverider-layermidi-arpmodes-lfowaves-bootscreen-lfo4-fxmod-lfolength-reloadconfirm-songguard-arpplocks-usbprobe_DN2_1.11.syx"
MODS = ["waverider", "layermidi", "arpmodes", "lfowaves", "bootscreen", "lfo4", "fxmod", "lfolength", "reloadconfirm",
        "songguard", "arpplocks", "usbprobe"]
PROBE_TAG = "wrl2b"
BOOT = resources_dir(ROOT) / "08_MyBuilds/waverider_glyph_boot.pgm"


def _sections(path: pathlib.Path) -> dict[int, bytes]:
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return {s.id: s.unpack() or s.raw_payload for s in load(read_image(path)).container.sections}


def _changed_since_flash() -> list[str]:
    """The mods whose code hash in FLASHED's /modinfo record is not today's (dnfw.cli.mods._modinfo).
    shortcut: the platform's own code has no hash in the record, so a platform change still fails."""
    from dnfw.mods import modinfo
    from dnfw.waverider.store import xxh32
    main = _sections(FLASHED)[3]
    flashed = dict(modinfo.parse(modinfo.record(main, modinfo.find(main)))["mods"])
    changed = []
    for mod in MODS:
        code = ROOT / "src/dnfw/mods" / f"{mod}_code.json"
        # the record keeps the first 11 characters of a name
        if flashed[mod[:11]] != (xxh32(code.read_bytes()) if code.exists() else 0):
            changed.append(mod)
    return changed


def test_the_flashed_build_rebuilds(tmp_path):
    if not (STOCK_111.exists() and FLASHED.exists() and BOOT.exists()):
        pytest.skip("stock 1.11, the flashed build or its boot image is not in 00_Resources")
    from dnfw.mods import modinfo
    changed = _changed_since_flash()
    if changed:
        pytest.xfail(f"changed since the flash, so the bytes differ: {', '.join(changed)}")
    out = tmp_path / "rebuilt_DN2_1.11.syx"
    done = subprocess.run([sys.executable, "-c", "import sys; from dnfw.cli.main import main; sys.exit(main(sys.argv[1:]))",
                           "mods", "apply", *[a for m in MODS for a in ("--mod", m)], "--probe-tag", PROBE_TAG, "--boot-image", str(BOOT),
                           str(STOCK_111), "-o", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout[-800:] + done.stderr[-800:]
    want, got = _sections(FLASHED), _sections(out)
    assert sorted(want) == sorted(got)
    at = modinfo.find(want[3])
    assert at is not None and at == modinfo.find(got[3])
    size = modinfo.size_at(want[3], at)
    for sid in want:
        a, b = bytearray(want[sid]), bytearray(got[sid])
        if sid == 3:
            for x in (a, b):
                x[at + 20:at + 24] = bytes(4)                 # the image id
                x[at + 56:at + 68] = bytes(12)                # the commit
                x[at + size - 4:at + size] = bytes(4)         # the hash
        assert a == b, f"section {sid} differs from the flashed build"
