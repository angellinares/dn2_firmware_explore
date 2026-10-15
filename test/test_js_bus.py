"""The browser hook bus against the Python one, in the test suite.

`js_bus_check.mjs` chains fxmod, lfo4 and Waverider the way the site does (each
page's download loaded into the next), in the orders that apply, and compares
every MAIN OS with the Python's (`dnfw.mods.bus`).
"""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_bus_check.mjs"
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"
ORDERS = (("fxmod", "waverider"), ("waverider", "fxmod"), ("lfo4", "waverider"),
          ("waverider", "lfo4"), ("fxmod", "waverider", "lfo4"))


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the browser mods cannot be checked")
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")

    from dnfw.cli.files import read_image
    from dnfw.cli.mods import _staged
    from dnfw.firmware.load import load
    from dnfw.mods import fxmod, lfo4, waverider

    tmp = tmp_path_factory.mktemp("js_bus")
    syx = tmp / "image.syx"
    syx.write_bytes(read_image(STOCK_111))
    firmware = load(syx.read_bytes())
    mods = {"fxmod": fxmod, "lfo4": lfo4, "waverider": waverider}
    for order in ORDERS:
        payloads = {}
        for mid in order:
            payloads.update(mods[mid].apply(_staged(firmware, payloads)).payloads)
        (tmp / ("-".join(order) + ".bin")).write_bytes(payloads[3])

    done = subprocess.run([node, str(HARNESS), "--syx", str(syx), "--py-dir", str(tmp)],
                          capture_output=True, text=True, cwd=ROOT)
    rows = [line.split("  ", 1) for line in done.stdout.splitlines()
            if line.startswith(("OK  ", "FAIL  "))]
    return {"code": done.returncode, "stderr": done.stderr,
            "rows": [(r[1], r[0] == "OK") for r in rows]}


def test_the_harness_ran_every_chain(run):
    assert sum(name.endswith("MAIN OS == Python") for name, _ in run["rows"]) == len(ORDERS), run["stderr"]


def test_every_check_passes(run):
    failed = [name for name, ok in run["rows"] if not ok]
    assert not failed, f"{failed}\nstderr:\n{run['stderr']}"
    assert run["code"] == 0
