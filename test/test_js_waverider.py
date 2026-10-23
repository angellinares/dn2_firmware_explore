"""The browser Waverider mod against the Python one, in the test suite.

`js_waverider_check.mjs` applies `site/js/mods/waverider.js` to stock 1.11 and compares
sections 3 and 7 with `dnfw.mods.waverider.apply`'s; the refusal of an image it already
patched must be worded the same on both sides. `waverider-code.js` must be current: its
section 7 data replays to what `dnfw.waverider.dsp.section7` makes today.
"""

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HARNESS = ROOT / "scripts" / "js_waverider_check.mjs"
CODE_JS = ROOT / "site/js/mods/waverider-code.js"
STOCK_111 = ROOT / "00_Resources/00_Firmware/Digitone_II_OS1.11_dist.zip"


@pytest.fixture(scope="module")
def fw():
    if not STOCK_111.exists():
        pytest.skip("Digitone II 1.11 is not in 00_Resources")
    from dnfw.cli.files import read_image
    from dnfw.firmware.load import load
    return read_image(STOCK_111), load(read_image(STOCK_111))


@pytest.fixture(scope="module")
def run(fw, tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH; the browser mods cannot be checked")
    from dnfw.cli.mods import _staged
    from dnfw.mods import ModError, waverider
    raw, firmware = fw
    tmp = tmp_path_factory.mktemp("js_waverider")
    (tmp / "stock.syx").write_bytes(raw)
    result = waverider.apply(firmware)
    (tmp / "main.bin").write_bytes(result.payloads[3])
    (tmp / "dsp.bin").write_bytes(result.payloads[7])
    try:
        waverider.apply(_staged(firmware, result.payloads))
        twice = None
    except ModError as exc:
        twice = str(exc)
    done = subprocess.run([node, str(HARNESS), "--syx", str(tmp / "stock.syx"),
                           "--py-main", str(tmp / "main.bin"), "--py-dsp", str(tmp / "dsp.bin"),
                           "--refusals-out", str(tmp / "refusals.json")],
                          capture_output=True, text=True, cwd=ROOT)
    rows = [line.split("  ", 1) for line in done.stdout.splitlines()
            if line.startswith(("OK  ", "FAIL  "))]
    js = tmp / "refusals.json"
    return {"code": done.returncode, "stderr": done.stderr, "rows": [(r[1], r[0] == "OK") for r in rows],
            "python": {"waverider_twice": twice},
            "js": json.loads(js.read_text()) if js.exists() else {}}


def test_the_harness_ran_at_all(run):
    assert run["rows"], run["stderr"]


def test_every_check_passes(run):
    failed = [name for name, ok in run["rows"] if not ok]
    assert not failed, f"{failed}\nstderr:\n{run['stderr']}"
    assert run["code"] == 0


def test_the_refusal_is_worded_the_same(run):
    assert run["python"]["waverider_twice"], run["python"]
    assert run["js"]["waverider_twice"] == run["python"]["waverider_twice"]


def test_the_transients_page_applies_to_a_waverider_image(run):
    """Waverider keeps the transient bank as stock has it, so the transients page applies to a
    Waverider image (2026-10-23; before, it refused it)."""
    assert run["js"]["transients_after"] is None, run["js"]


def test_the_browser_data_is_current(fw):
    sys.path.insert(0, str(ROOT / "scripts"))
    from gen_waverider_js import replay
    from dnfw.mods import waverider
    from dnfw.waverider import dsp
    code = json.loads(CODE_JS.read_text(encoding="utf-8").split("export const CODE = ", 1)[1].rstrip().rstrip(";"))
    stock = fw[1].container.find(7).unpack()
    assert replay(stock, code["dsp"]) == dsp.section7(stock)
    assert code["edits"] == waverider.SPEC["edits"] and code["guards"] == waverider.SPEC["guards"]
    assert code["chunk"]["code"] == waverider.SPEC["chunk"]["code"]
    assert code["drive"]["code"] == waverider.SPEC["drive"]["code"]
