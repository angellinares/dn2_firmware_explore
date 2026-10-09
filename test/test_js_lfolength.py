"""The browser LFO ONE/HALF length mod (`site/js/mods/lfolength.js`) against the Python one:
the same MAIN OS byte for byte from stock 1.11, a rebuilt image that verifies,
and a refusal on an image already patched. `scripts/js_lfolength_check.mjs` runs
the browser side under node."""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_lfolength_check.mjs"
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


def test_browser_mod_matches_the_python(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the browser mod cannot be checked")
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    from dnfw.mods import lfolength
    raw = read_image(STOCK_111)
    syx = tmp_path / "stock.syx"
    syx.write_bytes(raw)
    py = tmp_path / "py.bin"
    py.write_bytes(lfolength.apply(load(raw)).payloads[lfolength.SECTION])
    done = subprocess.run([node, str(HARNESS), "--syx", str(syx), "--py-content", str(py)],
                          capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.count("OK  ") == 3
